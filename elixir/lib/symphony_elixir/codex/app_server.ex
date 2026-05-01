defmodule SymphonyElixir.Codex.AppServer do
  @moduledoc """
  Minimal client for the Codex app-server JSON-RPC 2.0 stream over stdio.
  """

  require Logger
  alias SymphonyElixir.{Codex.DynamicTool, Config, PathSafety, SSH}

  @initialize_id 1
  @thread_start_id 2
  @turn_start_id 3
  @port_line_bytes 1_048_576
  @max_stream_log_bytes 1_000
  @non_interactive_tool_input_answer "This is a non-interactive session. Operator input is unavailable."

  @type session :: %{
          port: port(),
          metadata: map(),
          approval_policy: String.t() | map(),
          auto_approve_requests: boolean(),
          thread_sandbox: String.t(),
          turn_sandbox_policy: map(),
          thread_id: String.t(),
          workspace: Path.t(),
          host_workspace: Path.t(),
          worker_host: String.t() | nil
        }

  @spec ensure_runtime_ready() :: :ok | {:error, term()}
  def ensure_runtime_ready do
    if sbx_worker_enabled?() do
      ensure_sbx_ready()
    else
      :ok
    end
  end

  @spec run(Path.t(), String.t(), map(), keyword()) :: {:ok, map()} | {:error, term()}
  def run(workspace, prompt, issue, opts \\ []) do
    opts = Keyword.put_new(opts, :issue, issue)

    with {:ok, session} <- start_session(workspace, opts) do
      try do
        run_turn(session, prompt, issue, opts)
      after
        stop_session(session)
      end
    end
  end

  @spec start_session(Path.t(), keyword()) :: {:ok, session()} | {:error, term()}
  def start_session(workspace, opts \\ []) do
    worker_host = Keyword.get(opts, :worker_host)
    issue = Keyword.get(opts, :issue)

    with {:ok, expanded_workspace} <- validate_workspace_cwd(workspace, worker_host),
         {:ok, port, codex_workspace} <- start_port(expanded_workspace, worker_host, issue) do
      metadata = port_metadata(port, worker_host, expanded_workspace, codex_workspace)
      put_port_metadata(port, metadata)

      with {:ok, session_policies} <- session_policies(codex_workspace, worker_host),
           {:ok, thread_id} <- do_start_session(port, codex_workspace, session_policies) do
        {:ok,
         %{
           port: port,
           metadata: metadata,
           approval_policy: session_policies.approval_policy,
           auto_approve_requests: session_policies.approval_policy == "never",
           thread_sandbox: session_policies.thread_sandbox,
           turn_sandbox_policy: session_policies.turn_sandbox_policy,
           thread_id: thread_id,
           workspace: codex_workspace,
           host_workspace: expanded_workspace,
           worker_host: worker_host
         }}
      else
        {:error, reason} ->
          stop_port(port)
          {:error, reason}
      end
    end
  end

  @spec run_turn(session(), String.t(), map(), keyword()) :: {:ok, map()} | {:error, term()}
  def run_turn(
        %{
          port: port,
          metadata: metadata,
          approval_policy: approval_policy,
          auto_approve_requests: auto_approve_requests,
          turn_sandbox_policy: turn_sandbox_policy,
          thread_id: thread_id,
          workspace: workspace
        } = session,
        prompt,
        issue,
        opts \\ []
      ) do
    on_message = Keyword.get(opts, :on_message, &default_on_message/1)
    host_workspace = Map.get(session, :host_workspace, workspace)

    tool_executor =
      Keyword.get(opts, :tool_executor, fn tool, arguments ->
        DynamicTool.execute(tool, arguments, workspace: host_workspace)
      end)

    case start_turn(port, thread_id, prompt, issue, workspace, approval_policy, turn_sandbox_policy) do
      {:ok, turn_id} ->
        session_id = "#{thread_id}-#{turn_id}"
        Logger.info("Codex session started for #{issue_context(issue)} session_id=#{session_id}")

        emit_message(
          on_message,
          :session_started,
          %{
            session_id: session_id,
            thread_id: thread_id,
            turn_id: turn_id
          },
          metadata
        )

        case await_turn_completion(port, on_message, tool_executor, auto_approve_requests) do
          {:ok, result} ->
            Logger.info("Codex session completed for #{issue_context(issue)} session_id=#{session_id}")

            {:ok,
             %{
               result: result,
               session_id: session_id,
               thread_id: thread_id,
               turn_id: turn_id
             }}

          {:error, reason} ->
            Logger.warning("Codex session ended with error for #{issue_context(issue)} session_id=#{session_id}: #{inspect(reason)}")

            emit_message(
              on_message,
              :turn_ended_with_error,
              %{
                session_id: session_id,
                reason: reason
              },
              metadata
            )

            {:error, reason}
        end

      {:error, reason} ->
        Logger.error("Codex session failed for #{issue_context(issue)}: #{inspect(reason)}")
        emit_message(on_message, :startup_failed, %{reason: reason}, metadata)
        {:error, reason}
    end
  end

  @spec stop_session(session()) :: :ok
  def stop_session(%{port: port}) when is_port(port) do
    stop_port(port)
  end

  defp validate_workspace_cwd(workspace, nil) when is_binary(workspace) do
    expanded_workspace = Path.expand(workspace)
    expanded_root = Path.expand(Config.settings!().workspace.root)
    expanded_root_prefix = expanded_root <> "/"

    with {:ok, canonical_workspace} <- PathSafety.canonicalize(expanded_workspace),
         {:ok, canonical_root} <- PathSafety.canonicalize(expanded_root) do
      canonical_root_prefix = canonical_root <> "/"

      cond do
        canonical_workspace == canonical_root ->
          {:error, {:invalid_workspace_cwd, :workspace_root, canonical_workspace}}

        String.starts_with?(canonical_workspace <> "/", canonical_root_prefix) ->
          {:ok, canonical_workspace}

        String.starts_with?(expanded_workspace <> "/", expanded_root_prefix) ->
          {:error, {:invalid_workspace_cwd, :symlink_escape, expanded_workspace, canonical_root}}

        true ->
          {:error, {:invalid_workspace_cwd, :outside_workspace_root, canonical_workspace, canonical_root}}
      end
    else
      {:error, {:path_canonicalize_failed, path, reason}} ->
        {:error, {:invalid_workspace_cwd, :path_unreadable, path, reason}}
    end
  end

  defp validate_workspace_cwd(workspace, worker_host)
       when is_binary(workspace) and is_binary(worker_host) do
    cond do
      String.trim(workspace) == "" ->
        {:error, {:invalid_workspace_cwd, :empty_remote_workspace, worker_host}}

      String.contains?(workspace, ["\n", "\r", <<0>>]) ->
        {:error, {:invalid_workspace_cwd, :invalid_remote_workspace, worker_host, workspace}}

      true ->
        {:ok, workspace}
    end
  end

  defp start_port(workspace, nil, issue) do
    if sbx_worker_enabled?() do
      start_sbx_port(workspace, issue)
    else
      with {:ok, port} <- start_local_port(workspace) do
        {:ok, port, workspace}
      end
    end
  end

  defp start_port(workspace, worker_host, _issue) when is_binary(worker_host) do
    remote_command = remote_launch_command(workspace)

    with {:ok, port} <- SSH.start_port(worker_host, remote_command, line: @port_line_bytes) do
      {:ok, port, workspace}
    end
  end

  defp start_local_port(workspace) do
    executable = System.find_executable("bash")

    if is_nil(executable) do
      {:error, :bash_not_found}
    else
      port =
        Port.open(
          {:spawn_executable, String.to_charlist(executable)},
          [
            :binary,
            :exit_status,
            :stderr_to_stdout,
            args: [~c"-lc", String.to_charlist(Config.settings!().codex.command)],
            cd: String.to_charlist(workspace),
            line: @port_line_bytes
          ]
        )

      {:ok, port}
    end
  end

  defp start_sbx_port(workspace, issue) do
    executable = System.find_executable("bash")
    branch = sbx_branch(issue)

    cond do
      is_nil(executable) ->
        {:error, :bash_not_found}

      is_nil(System.find_executable("sbx")) ->
        {:error, :sbx_not_found}

      true ->
        with :ok <- ensure_sbx_ready(),
             {:ok, create_action} <- prepare_sbx_sandbox(workspace),
             :ok <- maybe_create_sbx_sandbox(create_action, workspace, branch),
             {:ok, codex_workspace} <- sbx_codex_workspace(workspace, branch) do
          port =
            Port.open(
              {:spawn_executable, String.to_charlist(executable)},
              [
                :binary,
                :exit_status,
                :stderr_to_stdout,
                args: [~c"-lc", String.to_charlist(sbx_exec_command(workspace, codex_workspace))],
                cd: String.to_charlist(workspace),
                line: @port_line_bytes
              ]
            )

          {:ok, port, codex_workspace}
        end
    end
  end

  defp remote_launch_command(workspace) when is_binary(workspace) do
    [
      "cd #{shell_escape(workspace)}",
      "exec #{Config.settings!().codex.command}"
    ]
    |> Enum.join(" && ")
  end

  defp port_metadata(port, worker_host), do: port_metadata(port, worker_host, nil, nil)

  defp port_metadata(port, worker_host, workspace, codex_workspace) when is_port(port) do
    base_metadata =
      case :erlang.port_info(port, :os_pid) do
        {:os_pid, os_pid} -> %{codex_app_server_pid: to_string(os_pid)}
        _ -> %{}
      end

    runtime_metadata =
      if is_binary(workspace) do
        workspace
        |> worker_runtime_metadata(worker_host)
        |> Map.put(:workspace_path, workspace)
        |> maybe_put_codex_workspace(workspace, codex_workspace)
      else
        %{}
      end

    Map.merge(base_metadata, runtime_metadata)
  end

  defp maybe_put_codex_workspace(metadata, workspace, codex_workspace)
       when is_binary(codex_workspace) and codex_workspace != workspace do
    Map.put(metadata, :codex_workspace, codex_workspace)
  end

  defp maybe_put_codex_workspace(metadata, _workspace, _codex_workspace), do: metadata

  defp put_port_metadata(port, metadata) when is_port(port) and is_map(metadata) do
    Process.put({__MODULE__, :port_metadata, port}, metadata)
    :ok
  end

  defp send_initialize(port) do
    payload = %{
      "method" => "initialize",
      "id" => @initialize_id,
      "params" => %{
        "capabilities" => %{
          "experimentalApi" => true
        },
        "clientInfo" => %{
          "name" => "hydra-orchestrator",
          "title" => "Hydra Orchestrator",
          "version" => "0.1.0"
        }
      }
    }

    send_message(port, payload)

    with {:ok, _} <- await_response(port, @initialize_id) do
      send_message(port, %{"method" => "initialized", "params" => %{}})
      :ok
    end
  end

  defp session_policies(workspace, nil) do
    Config.codex_runtime_settings(workspace)
  end

  defp session_policies(workspace, worker_host) when is_binary(worker_host) do
    Config.codex_runtime_settings(workspace, remote: true)
  end

  defp do_start_session(port, workspace, session_policies) do
    case send_initialize(port) do
      :ok -> start_thread(port, workspace, session_policies)
      {:error, reason} -> {:error, reason}
    end
  end

  defp start_thread(port, workspace, %{approval_policy: approval_policy, thread_sandbox: thread_sandbox}) do
    send_message(port, %{
      "method" => "thread/start",
      "id" => @thread_start_id,
      "params" => %{
        "approvalPolicy" => approval_policy,
        "sandbox" => thread_sandbox,
        "cwd" => workspace,
        "dynamicTools" => DynamicTool.tool_specs()
      }
    })

    case await_response(port, @thread_start_id) do
      {:ok, %{"thread" => thread_payload}} ->
        case thread_payload do
          %{"id" => thread_id} -> {:ok, thread_id}
          _ -> {:error, {:invalid_thread_payload, thread_payload}}
        end

      other ->
        other
    end
  end

  defp start_turn(port, thread_id, prompt, issue, workspace, approval_policy, turn_sandbox_policy) do
    send_message(port, %{
      "method" => "turn/start",
      "id" => @turn_start_id,
      "params" => %{
        "threadId" => thread_id,
        "input" => [
          %{
            "type" => "text",
            "text" => prompt
          }
        ],
        "cwd" => workspace,
        "title" => "#{issue.identifier}: #{issue.title}",
        "approvalPolicy" => approval_policy,
        "sandboxPolicy" => turn_sandbox_policy
      }
    })

    case await_response(port, @turn_start_id) do
      {:ok, %{"turn" => %{"id" => turn_id}}} -> {:ok, turn_id}
      other -> other
    end
  end

  defp await_turn_completion(port, on_message, tool_executor, auto_approve_requests) do
    receive_loop(
      port,
      on_message,
      Config.settings!().codex.turn_timeout_ms,
      "",
      tool_executor,
      auto_approve_requests
    )
  end

  defp receive_loop(port, on_message, timeout_ms, pending_line, tool_executor, auto_approve_requests) do
    receive do
      {^port, {:data, {:eol, chunk}}} ->
        complete_line = pending_line <> to_string(chunk)
        handle_incoming(port, on_message, complete_line, timeout_ms, tool_executor, auto_approve_requests)

      {^port, {:data, {:noeol, chunk}}} ->
        receive_loop(
          port,
          on_message,
          timeout_ms,
          pending_line <> to_string(chunk),
          tool_executor,
          auto_approve_requests
        )

      {^port, {:exit_status, status}} ->
        {:error, {:port_exit, status}}
    after
      timeout_ms ->
        {:error, :turn_timeout}
    end
  end

  defp handle_incoming(port, on_message, data, timeout_ms, tool_executor, auto_approve_requests) do
    payload_string = to_string(data)

    case Jason.decode(payload_string) do
      {:ok, payload} ->
        handle_decoded_payload(
          port,
          on_message,
          payload,
          payload_string,
          timeout_ms,
          tool_executor,
          auto_approve_requests
        )

      {:error, _reason} ->
        handle_malformed_stream_line(port, on_message, payload_string, timeout_ms, tool_executor, auto_approve_requests)
    end
  end

  defp handle_decoded_payload(
         port,
         on_message,
         %{"method" => "turn/completed"} = payload,
         payload_string,
         _timeout_ms,
         _tool_executor,
         _auto_approve_requests
       ) do
    emit_turn_event(on_message, :turn_completed, payload, payload_string, port, payload)
    {:ok, :turn_completed}
  end

  defp handle_decoded_payload(
         port,
         on_message,
         %{"method" => "turn/failed", "params" => params} = payload,
         payload_string,
         _timeout_ms,
         _tool_executor,
         _auto_approve_requests
       ) do
    emit_turn_event(on_message, :turn_failed, payload, payload_string, port, params)
    {:error, {:turn_failed, params}}
  end

  defp handle_decoded_payload(
         port,
         on_message,
         %{"method" => "turn/cancelled", "params" => params} = payload,
         payload_string,
         _timeout_ms,
         _tool_executor,
         _auto_approve_requests
       ) do
    emit_turn_event(on_message, :turn_cancelled, payload, payload_string, port, params)
    {:error, {:turn_cancelled, params}}
  end

  defp handle_decoded_payload(
         port,
         on_message,
         %{"method" => "error"} = payload,
         payload_string,
         _timeout_ms,
         _tool_executor,
         _auto_approve_requests
       ) do
    details = Map.get(payload, "params") || payload
    emit_turn_event(on_message, :turn_failed, payload, payload_string, port, details)
    {:error, {:codex_error, details}}
  end

  defp handle_decoded_payload(
         port,
         on_message,
         %{"method" => method} = payload,
         payload_string,
         timeout_ms,
         tool_executor,
         auto_approve_requests
       )
       when is_binary(method) do
    handle_turn_method(
      port,
      on_message,
      payload,
      payload_string,
      method,
      timeout_ms,
      tool_executor,
      auto_approve_requests
    )
  end

  defp handle_decoded_payload(port, on_message, payload, payload_string, timeout_ms, tool_executor, auto_approve_requests) do
    emit_message(
      on_message,
      :other_message,
      %{payload: payload, raw: payload_string},
      metadata_from_message(port, payload)
    )

    receive_loop(port, on_message, timeout_ms, "", tool_executor, auto_approve_requests)
  end

  defp handle_malformed_stream_line(port, on_message, payload_string, timeout_ms, tool_executor, auto_approve_requests) do
    log_non_json_stream_line(payload_string, "turn stream")

    if protocol_message_candidate?(payload_string) do
      emit_message(
        on_message,
        :malformed,
        %{payload: payload_string, raw: payload_string},
        metadata_from_message(port, %{raw: payload_string})
      )
    end

    receive_loop(port, on_message, timeout_ms, "", tool_executor, auto_approve_requests)
  end

  defp emit_turn_event(on_message, event, payload, payload_string, port, payload_details) do
    emit_message(
      on_message,
      event,
      %{
        payload: payload,
        raw: payload_string,
        details: payload_details
      },
      metadata_from_message(port, payload)
    )
  end

  defp handle_turn_method(
         port,
         on_message,
         payload,
         payload_string,
         method,
         timeout_ms,
         tool_executor,
         auto_approve_requests
       ) do
    metadata = metadata_from_message(port, payload)

    case maybe_handle_approval_request(
           port,
           method,
           payload,
           payload_string,
           on_message,
           metadata,
           tool_executor,
           auto_approve_requests
         ) do
      :input_required ->
        emit_message(
          on_message,
          :turn_input_required,
          %{payload: payload, raw: payload_string},
          metadata
        )

        {:error, {:turn_input_required, payload}}

      :approved ->
        receive_loop(port, on_message, timeout_ms, "", tool_executor, auto_approve_requests)

      :approval_required ->
        emit_message(
          on_message,
          :approval_required,
          %{payload: payload, raw: payload_string},
          metadata
        )

        {:error, {:approval_required, payload}}

      :unhandled ->
        if needs_input?(method, payload) do
          emit_message(
            on_message,
            :turn_input_required,
            %{payload: payload, raw: payload_string},
            metadata
          )

          {:error, {:turn_input_required, payload}}
        else
          emit_message(
            on_message,
            :notification,
            %{
              payload: payload,
              raw: payload_string
            },
            metadata
          )

          Logger.debug("Codex notification: #{inspect(method)}")
          receive_loop(port, on_message, timeout_ms, "", tool_executor, auto_approve_requests)
        end
    end
  end

  defp maybe_handle_approval_request(
         port,
         "item/commandExecution/requestApproval",
         %{"id" => id} = payload,
         payload_string,
         on_message,
         metadata,
         _tool_executor,
         auto_approve_requests
       ) do
    approve_or_require(
      port,
      id,
      "acceptForSession",
      payload,
      payload_string,
      on_message,
      metadata,
      auto_approve_requests
    )
  end

  defp maybe_handle_approval_request(
         port,
         "item/tool/call",
         %{"id" => id, "params" => params} = payload,
         payload_string,
         on_message,
         metadata,
         tool_executor,
         _auto_approve_requests
       ) do
    tool_name = tool_call_name(params)
    arguments = tool_call_arguments(params)

    result =
      tool_name
      |> tool_executor.(arguments)
      |> normalize_dynamic_tool_result()

    send_message(port, %{
      "id" => id,
      "result" => result
    })

    event =
      case result do
        %{"success" => true} -> :tool_call_completed
        _ when is_nil(tool_name) -> :unsupported_tool_call
        _ -> :tool_call_failed
      end

    emit_message(on_message, event, %{payload: payload, raw: payload_string}, metadata)

    :approved
  end

  defp maybe_handle_approval_request(
         port,
         "execCommandApproval",
         %{"id" => id} = payload,
         payload_string,
         on_message,
         metadata,
         _tool_executor,
         auto_approve_requests
       ) do
    approve_or_require(
      port,
      id,
      "approved_for_session",
      payload,
      payload_string,
      on_message,
      metadata,
      auto_approve_requests
    )
  end

  defp maybe_handle_approval_request(
         port,
         "applyPatchApproval",
         %{"id" => id} = payload,
         payload_string,
         on_message,
         metadata,
         _tool_executor,
         auto_approve_requests
       ) do
    approve_or_require(
      port,
      id,
      "approved_for_session",
      payload,
      payload_string,
      on_message,
      metadata,
      auto_approve_requests
    )
  end

  defp maybe_handle_approval_request(
         port,
         "item/fileChange/requestApproval",
         %{"id" => id} = payload,
         payload_string,
         on_message,
         metadata,
         _tool_executor,
         auto_approve_requests
       ) do
    approve_or_require(
      port,
      id,
      "acceptForSession",
      payload,
      payload_string,
      on_message,
      metadata,
      auto_approve_requests
    )
  end

  defp maybe_handle_approval_request(
         port,
         "item/tool/requestUserInput",
         %{"id" => id, "params" => params} = payload,
         payload_string,
         on_message,
         metadata,
         _tool_executor,
         auto_approve_requests
       ) do
    maybe_auto_answer_tool_request_user_input(
      port,
      id,
      params,
      payload,
      payload_string,
      on_message,
      metadata,
      auto_approve_requests
    )
  end

  defp maybe_handle_approval_request(
         _port,
         _method,
         _payload,
         _payload_string,
         _on_message,
         _metadata,
         _tool_executor,
         _auto_approve_requests
       ) do
    :unhandled
  end

  defp normalize_dynamic_tool_result(%{"success" => success} = result) when is_boolean(success) do
    output =
      case Map.get(result, "output") do
        existing_output when is_binary(existing_output) -> existing_output
        _ -> dynamic_tool_output(result)
      end

    content_items =
      case Map.get(result, "contentItems") do
        existing_items when is_list(existing_items) -> existing_items
        _ -> dynamic_tool_content_items(output)
      end

    result
    |> Map.put("output", output)
    |> Map.put("contentItems", content_items)
  end

  defp normalize_dynamic_tool_result(result) do
    %{
      "success" => false,
      "output" => inspect(result),
      "contentItems" => dynamic_tool_content_items(inspect(result))
    }
  end

  defp dynamic_tool_output(%{"contentItems" => [%{"text" => text} | _]}) when is_binary(text), do: text
  defp dynamic_tool_output(result), do: Jason.encode!(result, pretty: true)

  defp dynamic_tool_content_items(output) when is_binary(output) do
    [
      %{
        "type" => "inputText",
        "text" => output
      }
    ]
  end

  defp approve_or_require(
         port,
         id,
         decision,
         payload,
         payload_string,
         on_message,
         metadata,
         true
       ) do
    send_message(port, %{"id" => id, "result" => %{"decision" => decision}})

    emit_message(
      on_message,
      :approval_auto_approved,
      %{payload: payload, raw: payload_string, decision: decision},
      metadata
    )

    :approved
  end

  defp approve_or_require(
         _port,
         _id,
         _decision,
         _payload,
         _payload_string,
         _on_message,
         _metadata,
         false
       ) do
    :approval_required
  end

  defp maybe_auto_answer_tool_request_user_input(
         port,
         id,
         params,
         payload,
         payload_string,
         on_message,
         metadata,
         true
       ) do
    case tool_request_user_input_approval_answers(params) do
      {:ok, answers, decision} ->
        send_message(port, %{"id" => id, "result" => %{"answers" => answers}})

        emit_message(
          on_message,
          :approval_auto_approved,
          %{payload: payload, raw: payload_string, decision: decision},
          metadata
        )

        :approved

      :error ->
        reply_with_non_interactive_tool_input_answer(
          port,
          id,
          params,
          payload,
          payload_string,
          on_message,
          metadata
        )
    end
  end

  defp maybe_auto_answer_tool_request_user_input(
         port,
         id,
         params,
         payload,
         payload_string,
         on_message,
         metadata,
         false
       ) do
    reply_with_non_interactive_tool_input_answer(
      port,
      id,
      params,
      payload,
      payload_string,
      on_message,
      metadata
    )
  end

  defp tool_request_user_input_approval_answers(%{"questions" => questions}) when is_list(questions) do
    answers =
      Enum.reduce_while(questions, %{}, fn question, acc ->
        case tool_request_user_input_approval_answer(question) do
          {:ok, question_id, answer_label} ->
            {:cont, Map.put(acc, question_id, %{"answers" => [answer_label]})}

          :error ->
            {:halt, :error}
        end
      end)

    case answers do
      :error -> :error
      answer_map when map_size(answer_map) > 0 -> {:ok, answer_map, "Approve this Session"}
      _ -> :error
    end
  end

  defp tool_request_user_input_approval_answers(_params), do: :error

  defp reply_with_non_interactive_tool_input_answer(
         port,
         id,
         params,
         payload,
         payload_string,
         on_message,
         metadata
       ) do
    case tool_request_user_input_unavailable_answers(params) do
      {:ok, answers} ->
        send_message(port, %{"id" => id, "result" => %{"answers" => answers}})

        emit_message(
          on_message,
          :tool_input_auto_answered,
          %{payload: payload, raw: payload_string, answer: @non_interactive_tool_input_answer},
          metadata
        )

        :approved

      :error ->
        :input_required
    end
  end

  defp tool_request_user_input_unavailable_answers(%{"questions" => questions}) when is_list(questions) do
    answers =
      Enum.reduce_while(questions, %{}, fn question, acc ->
        case tool_request_user_input_question_id(question) do
          {:ok, question_id} ->
            {:cont, Map.put(acc, question_id, %{"answers" => [@non_interactive_tool_input_answer]})}

          :error ->
            {:halt, :error}
        end
      end)

    case answers do
      :error -> :error
      answer_map when map_size(answer_map) > 0 -> {:ok, answer_map}
      _ -> :error
    end
  end

  defp tool_request_user_input_unavailable_answers(_params), do: :error

  defp tool_request_user_input_question_id(%{"id" => question_id}) when is_binary(question_id),
    do: {:ok, question_id}

  defp tool_request_user_input_question_id(_question), do: :error

  defp tool_request_user_input_approval_answer(%{"id" => question_id, "options" => options})
       when is_binary(question_id) and is_list(options) do
    case tool_request_user_input_approval_option_label(options) do
      nil -> :error
      answer_label -> {:ok, question_id, answer_label}
    end
  end

  defp tool_request_user_input_approval_answer(_question), do: :error

  defp tool_request_user_input_approval_option_label(options) do
    options
    |> Enum.map(&tool_request_user_input_option_label/1)
    |> Enum.reject(&is_nil/1)
    |> case do
      labels ->
        Enum.find(labels, &(&1 == "Approve this Session")) ||
          Enum.find(labels, &(&1 == "Approve Once")) ||
          Enum.find(labels, &approval_option_label?/1)
    end
  end

  defp tool_request_user_input_option_label(%{"label" => label}) when is_binary(label), do: label
  defp tool_request_user_input_option_label(_option), do: nil

  defp approval_option_label?(label) when is_binary(label) do
    normalized_label =
      label
      |> String.trim()
      |> String.downcase()

    String.starts_with?(normalized_label, "approve") or String.starts_with?(normalized_label, "allow")
  end

  defp await_response(port, request_id) do
    with_timeout_response(port, request_id, effective_read_timeout_ms(), "")
  end

  defp effective_read_timeout_ms do
    read_timeout_ms = Config.settings!().codex.read_timeout_ms

    if sbx_worker_enabled?() do
      max(read_timeout_ms, sbx_startup_timeout_ms())
    else
      read_timeout_ms
    end
  end

  defp with_timeout_response(port, request_id, timeout_ms, pending_line) do
    receive do
      {^port, {:data, {:eol, chunk}}} ->
        complete_line = pending_line <> to_string(chunk)
        handle_response(port, request_id, complete_line, timeout_ms)

      {^port, {:data, {:noeol, chunk}}} ->
        with_timeout_response(port, request_id, timeout_ms, pending_line <> to_string(chunk))

      {^port, {:exit_status, status}} ->
        {:error, {:port_exit, status}}
    after
      timeout_ms ->
        {:error, :response_timeout}
    end
  end

  defp handle_response(port, request_id, data, timeout_ms) do
    payload = to_string(data)

    case Jason.decode(payload) do
      {:ok, %{"id" => ^request_id, "error" => error}} ->
        {:error, {:response_error, error}}

      {:ok, %{"id" => ^request_id, "result" => result}} ->
        {:ok, result}

      {:ok, %{"id" => ^request_id} = response_payload} ->
        {:error, {:response_error, response_payload}}

      {:ok, %{} = other} ->
        Logger.debug("Ignoring message while waiting for response: #{inspect(other)}")
        with_timeout_response(port, request_id, timeout_ms, "")

      {:error, _} ->
        log_non_json_stream_line(payload, "response stream")
        with_timeout_response(port, request_id, timeout_ms, "")
    end
  end

  defp log_non_json_stream_line(data, stream_label) do
    text =
      data
      |> to_string()
      |> String.trim()
      |> String.slice(0, @max_stream_log_bytes)

    if text != "" do
      if String.match?(text, ~r/\b(error|warn|warning|failed|fatal|panic|exception)\b/i) do
        Logger.warning("Codex #{stream_label} output: #{text}")
      else
        Logger.debug("Codex #{stream_label} output: #{text}")
      end
    end
  end

  defp protocol_message_candidate?(data) do
    data
    |> to_string()
    |> String.trim_leading()
    |> String.starts_with?("{")
  end

  defp issue_context(%{id: issue_id, identifier: identifier}) do
    "issue_id=#{issue_id} issue_identifier=#{identifier}"
  end

  defp stop_port(port) when is_port(port) do
    case :erlang.port_info(port) do
      :undefined ->
        :ok

      _ ->
        try do
          Port.close(port)
          :ok
        rescue
          ArgumentError ->
            :ok
        end
    end
  end

  defp emit_message(on_message, event, details, metadata) when is_function(on_message, 1) do
    message = metadata |> Map.merge(details) |> Map.put(:event, event) |> Map.put(:timestamp, DateTime.utc_now())
    on_message.(message)
  end

  defp metadata_from_message(port, payload) do
    metadata = Process.get({__MODULE__, :port_metadata, port}) || port_metadata(port, nil)
    maybe_set_usage(metadata, payload)
  end

  defp maybe_set_usage(metadata, payload) when is_map(payload) do
    usage = Map.get(payload, "usage") || Map.get(payload, :usage)

    if is_map(usage) do
      Map.put(metadata, :usage, usage)
    else
      metadata
    end
  end

  defp maybe_set_usage(metadata, _payload), do: metadata

  defp ensure_sbx_ready do
    case System.find_executable("sbx") do
      nil -> {:error, :sbx_not_found}
      sbx_executable -> run_sbx_readiness_check(sbx_executable)
    end
  end

  defp run_sbx_readiness_check(sbx_executable) do
    case System.cmd(sbx_executable, ["secret", "ls"], stderr_to_stdout: true) do
      {output, 0} ->
        cond do
          not sbx_secret_present?(output, "openai") ->
            {:error, {:sbx_openai_secret_missing, "Docker Sandboxes OpenAI secret is missing. Run hydra sandbox openai or hydra setup sandbox.", sanitize_sbx_diagnostic(output)}}

          not sbx_secret_present?(output, "github") ->
            {:error, {:sbx_github_secret_missing, "Docker Sandboxes GitHub secret is missing. Run hydra sandbox github or hydra setup sandbox.", sanitize_sbx_diagnostic(output)}}

          true ->
            :ok
        end

      {output, _status} ->
        {:error, classify_sbx_readiness_error(output)}
    end
  end

  defp classify_sbx_readiness_error(output) when is_binary(output) do
    diagnostic = sanitize_sbx_diagnostic(output)
    normalized = String.downcase(diagnostic)

    if String.contains?(normalized, "not authenticated") or String.contains?(normalized, "sbx login") do
      {:sbx_not_authenticated, "Docker Sandboxes is not authenticated. Run hydra sandbox login or hydra setup sandbox.", diagnostic}
    else
      {:sbx_readiness_check_failed, "Docker Sandboxes readiness check failed. Run hydra sandbox status.", diagnostic}
    end
  end

  defp prepare_sbx_sandbox(workspace) when is_binary(workspace) do
    name = sbx_sandbox_name(workspace)
    lifecycle = sbx_lifecycle()
    sandbox_info = sbx_sandbox_info(name)

    cond do
      lifecycle == "reuse" and match?({:ok, _sandbox}, sandbox_info) ->
        {:ok, :reuse}

      lifecycle == "repair" and repairable_sbx_sandbox?(sandbox_info) ->
        {:ok, :reuse}

      sandbox_info == :missing ->
        {:ok, :create}

      true ->
        recreate_sbx_sandbox(name)
    end
  end

  defp repairable_sbx_sandbox?({:ok, %{status: status}}), do: status in ["running", "stopped"]
  defp repairable_sbx_sandbox?(_sandbox_info), do: false

  defp recreate_sbx_sandbox(name) do
    case remove_existing_sbx_sandbox(name) do
      :ok -> {:ok, :create}
      {:error, _reason} = error -> error
    end
  end

  defp maybe_create_sbx_sandbox(:reuse, _workspace, _branch), do: :ok
  defp maybe_create_sbx_sandbox(:create, workspace, branch), do: create_sbx_sandbox(workspace, branch)

  defp create_sbx_sandbox(workspace, branch) when is_binary(workspace) do
    case System.find_executable("sbx") do
      nil ->
        {:error, :sbx_not_found}

      sbx ->
        create_sbx_sandbox(sbx, workspace, branch)
    end
  end

  defp create_sbx_sandbox(sbx, workspace, branch) do
    case System.cmd(sbx, sbx_create_args(workspace, branch), stderr_to_stdout: true) do
      {_output, 0} ->
        :ok

      {output, _status} ->
        {:error, {:sbx_create_failed, "Docker Sandboxes failed to create sandbox #{sbx_sandbox_name(workspace)}.", sanitize_sbx_diagnostic(output)}}
    end
  end

  defp remove_existing_sbx_sandbox(name) when is_binary(name) do
    case System.find_executable("sbx") do
      nil ->
        {:error, :sbx_not_found}

      sbx ->
        remove_existing_sbx_sandbox(sbx, name)
    end
  end

  defp remove_existing_sbx_sandbox(sbx, name) do
    case System.cmd(sbx, ["rm", "--force", name], stderr_to_stdout: true) do
      {_output, 0} ->
        :ok

      {output, _status} ->
        {:error, {:sbx_remove_failed, "Docker Sandboxes failed to remove stale sandbox #{name}.", sanitize_sbx_diagnostic(output)}}
    end
  end

  defp sbx_create_args(workspace, branch) when is_binary(workspace) do
    config = sbx_worker_config()
    agent = worker_config_string(config, "agent", "codex")

    ["create", "--quiet", "--name", sbx_sandbox_name(workspace)]
    |> append_optional_sbx_arg("--branch", branch)
    |> append_optional_sbx_arg("--template", worker_config_string(config, "template", nil))
    |> append_repeated_sbx_args("--kit", worker_config_list(config, "kits") ++ worker_config_list(config, "kit"))
    |> append_optional_sbx_arg("--cpus", worker_config_string(config, "cpus", nil))
    |> append_optional_sbx_arg("--memory", worker_config_string(config, "memory", nil))
    |> Kernel.++([agent | sbx_workspace_mounts(workspace)])
  end

  defp append_optional_sbx_arg(args, _flag, value) when value in [nil, ""], do: args
  defp append_optional_sbx_arg(args, flag, value), do: args ++ [flag, to_string(value)]

  defp append_repeated_sbx_args(args, flag, values) when is_list(values) do
    Enum.reduce(values, args, fn
      value, acc when value in [nil, ""] -> acc
      value, acc -> acc ++ [flag, to_string(value)]
    end)
  end

  defp sbx_exec_command(workspace, codex_workspace)
       when is_binary(workspace) and is_binary(codex_workspace) do
    [
      "exec sbx exec -i",
      "-w #{shell_escape(codex_workspace)}",
      shell_escape(sbx_sandbox_name(workspace)),
      sbx_codex_env_command(),
      "codex",
      codex_cli_args()
    ]
    |> Enum.reject(&(&1 in [nil, ""]))
    |> Enum.join(" ")
  end

  defp codex_cli_args do
    Config.settings!().codex.command
    |> String.trim()
    |> strip_codex_executable()
  end

  defp strip_codex_executable("codex"), do: ""
  defp strip_codex_executable("codex " <> rest), do: String.trim(rest)
  defp strip_codex_executable(command), do: command

  defp sbx_codex_env_command do
    case sbx_codex_runtime_env() do
      [] ->
        nil

      env ->
        "env " <> Enum.map_join(env, " ", fn {key, value} -> "#{key}=#{shell_escape(value)}" end)
    end
  end

  defp sbx_codex_runtime_env do
    [
      {"CODEX_HOME", System.get_env("HYDRA_CODEX_HOME")},
      {"HOME", System.get_env("HYDRA_CODEX_USER_HOME")}
    ]
    |> Enum.map(fn {key, value} -> {key, normalize_runtime_env_path(value)} end)
    |> Enum.reject(fn {_key, value} -> value in [nil, ""] end)
  end

  defp normalize_runtime_env_path(value) when is_binary(value) do
    trimmed = String.trim(value)

    cond do
      trimmed == "" -> nil
      String.contains?(trimmed, ["\n", "\r", <<0>>]) -> nil
      true -> Path.expand(trimmed)
    end
  end

  defp normalize_runtime_env_path(_value), do: nil

  defp sbx_codex_runtime_mounts do
    Enum.map(sbx_codex_runtime_env(), fn {_key, path} -> path end)
  end

  defp sbx_workspace_mounts(workspace) when is_binary(workspace) do
    [workspace | sbx_codex_runtime_mounts() ++ Enum.map(sbx_extra_workspaces(), &format_sbx_workspace_mount/1)]
    |> Enum.reject(&(&1 in [nil, ""]))
    |> Enum.uniq()
  end

  defp sbx_extra_workspaces do
    case Map.get(sbx_worker_config(), "extra_workspaces") do
      values when is_list(values) -> values
      _ -> []
    end
  end

  defp format_sbx_workspace_mount(%{"path" => path} = workspace) when is_binary(path) do
    cond do
      String.ends_with?(path, ":ro") -> path
      Map.get(workspace, "writable") == true or Map.get(workspace, "readonly") == false -> path
      true -> path <> ":ro"
    end
  end

  defp format_sbx_workspace_mount(path) when is_binary(path) do
    if String.ends_with?(path, ":ro"), do: path, else: path <> ":ro"
  end

  defp format_sbx_workspace_mount(_workspace), do: nil

  defp sbx_branch(issue) do
    case worker_config_string(sbx_worker_config(), "branch", nil) do
      value when value in [nil, ""] -> default_sbx_branch(issue)
      value -> normalize_sbx_branch_config(value)
    end
  end

  defp default_sbx_branch(%{branch_name: branch_name}) when is_binary(branch_name) and branch_name != "" do
    sanitize_git_branch(branch_name)
  end

  defp default_sbx_branch(%{identifier: identifier}) when is_binary(identifier) and identifier != "" do
    "codex/#{safe_git_branch_segment(identifier)}"
  end

  defp default_sbx_branch(_issue), do: nil

  defp normalize_sbx_branch_config(value) when is_binary(value) do
    case String.downcase(String.trim(value)) do
      disabled when disabled in ["false", "off", "none", "direct"] -> nil
      "auto" -> "auto"
      _ -> sanitize_git_branch(value)
    end
  end

  defp sbx_codex_workspace(workspace, branch) when branch in [nil, ""], do: {:ok, workspace}

  defp sbx_codex_workspace(_workspace, "auto") do
    {:error, {:unsupported_sbx_branch, "auto", "Hydra app-server mode requires a deterministic branch name."}}
  end

  defp sbx_codex_workspace(workspace, branch) when is_binary(workspace) and is_binary(branch) do
    path =
      Path.join([
        workspace,
        ".sbx",
        "#{sbx_sandbox_name(workspace)}-worktrees"
        | String.split(branch, "/", trim: true)
      ])

    {:ok, Path.expand(path)}
  end

  defp sbx_lifecycle, do: sbx_lifecycle(sbx_worker_config())

  defp sbx_lifecycle(config) do
    case String.downcase(worker_config_string(config, "lifecycle", "fresh")) do
      lifecycle when lifecycle in ["fresh", "reuse", "repair"] -> lifecycle
      _ -> "fresh"
    end
  end

  defp sbx_sandbox_info(name) when is_binary(name) do
    with sbx when is_binary(sbx) <- System.find_executable("sbx"),
         {output, 0} <- System.cmd(sbx, ["ls", "--json"], stderr_to_stdout: true),
         {:ok, %{"sandboxes" => sandboxes}} when is_list(sandboxes) <- Jason.decode(output),
         %{} = sandbox <- Enum.find(sandboxes, &(Map.get(&1, "name") == name)) do
      {:ok,
       %{
         name: Map.get(sandbox, "name"),
         agent: Map.get(sandbox, "agent"),
         status: Map.get(sandbox, "status"),
         workspaces: Map.get(sandbox, "workspaces", [])
       }}
    else
      nil -> :missing
      _ -> sbx_sandbox_info_from_table(name)
    end
  end

  defp sbx_sandbox_info_from_table(name) do
    case System.find_executable("sbx") do
      nil ->
        :missing

      sbx ->
        sbx_sandbox_info_from_table(sbx, name)
    end
  end

  defp sbx_sandbox_info_from_table(sbx, name) do
    case System.cmd(sbx, ["ls"], stderr_to_stdout: true) do
      {output, 0} -> find_sbx_sandbox_in_table(output, name)
      _ -> :missing
    end
  end

  defp find_sbx_sandbox_in_table(output, name) do
    output
    |> String.split("\n", trim: true)
    |> Enum.find_value(:missing, &parse_sbx_sandbox_table_line(&1, name))
  end

  defp parse_sbx_sandbox_table_line(line, name) do
    case String.split(line, ~r/\s+/, parts: 4, trim: true) do
      [^name, agent, status | _] -> {:ok, %{name: name, agent: agent, status: status, workspaces: []}}
      _ -> nil
    end
  end

  defp sbx_sandbox_name(workspace) when is_binary(workspace) do
    worker_config_string(sbx_worker_config(), "name", default_sbx_name(workspace))
  end

  defp default_sbx_name(workspace) when is_binary(workspace) do
    project =
      case System.get_env("HYDRA_PROJECT") do
        value when is_binary(value) and value != "" -> value
        _ -> "project"
      end

    ["hydra", project, Path.basename(workspace)]
    |> Enum.map(&safe_sbx_name_part/1)
    |> Enum.reject(&(&1 == ""))
    |> Enum.join("-")
  end

  defp sbx_sandbox_status(name) when is_binary(name) do
    case sbx_sandbox_info(name) do
      {:ok, %{status: status}} when is_binary(status) -> status
      {:ok, _sandbox} -> "unknown"
      :missing -> "missing"
    end
  end

  defp sbx_secret_present?(output, secret) when is_binary(output) and is_binary(secret) do
    Regex.match?(Regex.compile!("(^|\\s)#{Regex.escape(secret)}(\\s|$)", "i"), output)
  end

  defp sbx_startup_timeout_ms do
    config = sbx_worker_config()

    worker_config_positive_integer(config, "startup_timeout_ms") ||
      worker_config_positive_integer(config, "read_timeout_ms") ||
      120_000
  end

  defp sbx_worker_config, do: Config.settings!().worker.sbx

  defp sbx_worker_enabled?, do: worker_enabled?(sbx_worker_config())

  @spec worker_runtime_metadata(Path.t()) :: map()
  def worker_runtime_metadata(workspace), do: worker_runtime_metadata(workspace, nil)

  @spec worker_runtime_metadata(Path.t(), String.t() | nil) :: map()
  def worker_runtime_metadata(_workspace, worker_host) when is_binary(worker_host) do
    %{worker_host: worker_host}
  end

  def worker_runtime_metadata(workspace, nil) when is_binary(workspace) do
    if sbx_worker_enabled?() do
      config = sbx_worker_config()
      name = sbx_sandbox_name(workspace)

      %{
        worker_host: "sbx",
        sandbox: %{
          name: name,
          agent: worker_config_string(config, "agent", "codex"),
          lifecycle: sbx_lifecycle(config),
          status: sbx_sandbox_status(name),
          template: worker_config_string(config, "template", nil),
          kits: worker_config_list(config, "kits"),
          cpus: worker_config_string(config, "cpus", nil),
          memory: worker_config_string(config, "memory", nil),
          branch: worker_config_string(config, "branch", nil),
          network_policy: worker_config_string(config, "network_policy", nil),
          workspace_mounts: sbx_workspace_mounts(workspace)
        }
      }
    else
      %{}
    end
  end

  defp worker_config_string(config, key, default) when is_map(config) do
    config
    |> worker_config_value(key)
    |> worker_value_to_string()
    |> case do
      nil -> default
      value -> value
    end
  end

  defp worker_config_list(config, key) when is_map(config) do
    case worker_config_value(config, key) do
      values when is_list(values) -> Enum.map(values, &worker_value_to_string/1) |> Enum.reject(&is_nil/1)
      value -> value |> worker_value_to_string() |> List.wrap() |> Enum.reject(&is_nil/1)
    end
  end

  defp worker_config_positive_integer(config, key) do
    case worker_config_value(config, key) do
      value when is_integer(value) and value > 0 -> value
      value when is_binary(value) -> parse_positive_integer(value)
      _ -> nil
    end
  end

  defp worker_config_value(config, key) do
    Map.get(config, key) || Map.get(config, String.to_atom(key))
  end

  defp worker_enabled?(%{} = config) do
    case worker_config_value(config, "enabled") do
      true -> true
      value when is_binary(value) -> String.downcase(String.trim(value)) in ["1", "true", "yes", "on"]
      _ -> false
    end
  end

  defp worker_value_to_string(value) when is_binary(value) do
    case String.trim(value) do
      "" -> nil
      trimmed -> trimmed
    end
  end

  defp worker_value_to_string(value) when is_integer(value), do: Integer.to_string(value)
  defp worker_value_to_string(nil), do: nil
  defp worker_value_to_string(value) when is_atom(value), do: Atom.to_string(value)
  defp worker_value_to_string(_value), do: nil

  defp parse_positive_integer(value) when is_binary(value) do
    case Integer.parse(String.trim(value)) do
      {integer, ""} when integer > 0 -> integer
      _ -> nil
    end
  end

  defp safe_git_branch_segment(value) when is_binary(value) do
    value
    |> String.downcase()
    |> String.replace(~r/[^a-z0-9._-]+/, "-")
    |> String.trim("-.")
    |> case do
      "" -> "issue"
      segment -> segment
    end
  end

  defp safe_sbx_name_part(value) do
    value
    |> to_string()
    |> String.downcase()
    |> String.replace(~r/[^a-z0-9_.-]+/, "-")
    |> String.trim("-")
  end

  defp sanitize_git_branch(value) when is_binary(value) do
    value
    |> String.trim()
    |> String.replace(~r/\s+/, "-")
    |> String.replace(~r/[^A-Za-z0-9._\/-]+/, "-")
    |> String.replace(~r/\.lock$/, "-lock")
    |> String.trim("/.")
    |> case do
      "" -> nil
      branch -> branch
    end
  end

  defp sanitize_sbx_diagnostic(output) when is_binary(output) do
    output
    |> String.replace(~r/\e\[[0-9;]*[A-Za-z]/, "")
    |> String.trim()
    |> String.slice(0, 500)
  end

  defp shell_escape(value) when is_binary(value) do
    "'" <> String.replace(value, "'", "'\"'\"'") <> "'"
  end

  defp default_on_message(_message), do: :ok

  defp tool_call_name(params) when is_map(params) do
    case Map.get(params, "tool") || Map.get(params, :tool) || Map.get(params, "name") || Map.get(params, :name) do
      name when is_binary(name) ->
        case String.trim(name) do
          "" -> nil
          trimmed -> trimmed
        end

      _ ->
        nil
    end
  end

  defp tool_call_name(_params), do: nil

  defp tool_call_arguments(params) when is_map(params) do
    Map.get(params, "arguments") || Map.get(params, :arguments) || %{}
  end

  defp tool_call_arguments(_params), do: %{}

  defp send_message(port, message) do
    line = Jason.encode!(message) <> "\n"
    Port.command(port, line)
  end

  defp needs_input?(method, payload)
       when is_binary(method) and is_map(payload) do
    String.starts_with?(method, "turn/") && input_required_method?(method, payload)
  end

  defp needs_input?(_method, _payload), do: false

  defp input_required_method?(method, payload) when is_binary(method) do
    method in [
      "turn/input_required",
      "turn/needs_input",
      "turn/need_input",
      "turn/request_input",
      "turn/request_response",
      "turn/provide_input",
      "turn/approval_required"
    ] || request_payload_requires_input?(payload)
  end

  defp request_payload_requires_input?(payload) do
    params = Map.get(payload, "params")
    needs_input_field?(payload) || needs_input_field?(params)
  end

  defp needs_input_field?(payload) when is_map(payload) do
    Map.get(payload, "requiresInput") == true or
      Map.get(payload, "needsInput") == true or
      Map.get(payload, "input_required") == true or
      Map.get(payload, "inputRequired") == true or
      Map.get(payload, "type") == "input_required" or
      Map.get(payload, "type") == "needs_input"
  end

  defp needs_input_field?(_payload), do: false
end
