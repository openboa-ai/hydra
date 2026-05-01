defmodule SymphonyElixir.Workflow do
  @moduledoc """
  Loads workflow configuration and prompt from WORKFLOW.md.
  """

  alias SymphonyElixir.WorkflowStore

  @workflow_file_name "WORKFLOW.md"

  @spec workflow_file_path() :: Path.t()
  def workflow_file_path do
    Application.get_env(:hydra_elixir, :workflow_file_path) ||
      Path.join(File.cwd!(), @workflow_file_name)
  end

  @spec set_workflow_file_path(Path.t()) :: :ok
  def set_workflow_file_path(path) when is_binary(path) do
    Application.put_env(:hydra_elixir, :workflow_file_path, path)
    maybe_reload_store()
    :ok
  end

  @spec clear_workflow_file_path() :: :ok
  def clear_workflow_file_path do
    Application.delete_env(:hydra_elixir, :workflow_file_path)
    maybe_reload_store()
    :ok
  end

  @type loaded_workflow :: %{
          config: map(),
          prompt: String.t(),
          prompt_template: String.t()
        }

  @spec current() :: {:ok, loaded_workflow()} | {:error, term()}
  def current do
    case Process.whereis(WorkflowStore) do
      pid when is_pid(pid) ->
        WorkflowStore.current()

      _ ->
        load()
    end
  end

  @spec load() :: {:ok, loaded_workflow()} | {:error, term()}
  def load do
    load(workflow_file_path())
  end

  @spec load(Path.t()) :: {:ok, loaded_workflow()} | {:error, term()}
  def load(path) when is_binary(path) do
    case File.read(path) do
      {:ok, content} ->
        parse(content, path)

      {:error, reason} ->
        {:error, {:missing_workflow_file, path, reason}}
    end
  end

  defp parse(content, path) do
    {front_matter_lines, prompt_lines} = split_front_matter(content)

    with {:ok, front_matter} <- front_matter_yaml_to_map(front_matter_lines),
         {:ok, project_settings} <- project_settings_config(path) do
      prompt = Enum.join(prompt_lines, "\n") |> String.trim()

      {:ok,
       %{
         config: deep_merge(front_matter, project_settings),
         prompt: prompt,
         prompt_template: prompt
       }}
    else
      {:error, :workflow_front_matter_not_a_map} ->
        {:error, :workflow_front_matter_not_a_map}

      {:error, {:project_settings_parse_error, _settings_path, _reason} = reason} ->
        {:error, reason}

      {:error, reason} ->
        {:error, {:workflow_parse_error, reason}}
    end
  end

  defp split_front_matter(content) do
    lines = String.split(content, ~r/\R/, trim: false)

    case lines do
      ["---" | tail] ->
        {front, rest} = Enum.split_while(tail, &(&1 != "---"))

        case rest do
          ["---" | prompt_lines] -> {front, prompt_lines}
          _ -> {front, []}
        end

      _ ->
        {[], lines}
    end
  end

  defp front_matter_yaml_to_map(lines) do
    yaml = Enum.join(lines, "\n")

    if String.trim(yaml) == "" do
      {:ok, %{}}
    else
      case YamlElixir.read_from_string(yaml) do
        {:ok, decoded} when is_map(decoded) -> {:ok, decoded}
        {:ok, _} -> {:error, :workflow_front_matter_not_a_map}
        {:error, reason} -> {:error, reason}
      end
    end
  end

  defp project_settings_config(path) do
    settings_path = project_settings_path(path)

    case File.read(settings_path) do
      {:ok, content} ->
        parse_project_settings(content, settings_path)

      {:error, :enoent} ->
        {:ok, %{}}

      {:error, reason} ->
        {:error, {:project_settings_parse_error, settings_path, reason}}
    end
  end

  defp project_settings_path(path), do: Path.join(Path.dirname(path), "settings.yml")

  defp parse_project_settings(content, settings_path) do
    if String.trim(content) == "" do
      {:ok, %{}}
    else
      case YamlElixir.read_from_string(content) do
        {:ok, decoded} when is_map(decoded) -> {:ok, settings_to_workflow_config(decoded)}
        {:ok, _decoded} -> {:error, {:project_settings_parse_error, settings_path, :settings_not_a_map}}
        {:error, reason} -> {:error, {:project_settings_parse_error, settings_path, reason}}
      end
    end
  end

  defp settings_to_workflow_config(settings) do
    %{}
    |> put_if_present(
      ["ui", "project_name"],
      setting_value(settings, ["project", "name"]) || setting_value(settings, ["project_name"])
    )
    |> put_if_present(["ui", "title"], setting_value(settings, ["ui", "title"]) || setting_value(settings, ["name"]))
    |> put_if_present(
      ["ui", "description"],
      setting_value(settings, ["ui", "description"]) || setting_value(settings, ["description"])
    )
    |> put_if_present(["ui", "color"], setting_value(settings, ["ui", "color"]) || setting_value(settings, ["color"]))
    |> put_if_present(["tracker", "project_slug"], setting_value(settings, ["linear", "project_slug"]))
    |> put_if_present(["server", "port"], setting_value(settings, ["runtime", "dashboard_port"]))
    |> put_if_present(["server", "host"], setting_value(settings, ["runtime", "dashboard_host"]))
    |> put_if_present(["workspace", "root"], setting_value(settings, ["runtime", "workspace_root"]))
    |> put_if_present(["agent", "max_concurrent_agents"], setting_value(settings, ["agent", "max_concurrent_agents"]))
    |> put_if_present(["agent", "max_turns"], setting_value(settings, ["agent", "max_turns"]))
  end

  defp setting_value(settings, path) do
    Enum.reduce_while(path, settings, fn key, current ->
      case current do
        %{} -> {:cont, Map.get(current, key)}
        _ -> {:halt, nil}
      end
    end)
  end

  defp put_if_present(config, _path, nil), do: config

  defp put_if_present(config, path, value) do
    put_nested(config, path, value)
  end

  defp put_nested(config, [key], value) do
    Map.put(config, key, value)
  end

  defp put_nested(config, [key | rest], value) do
    nested =
      case Map.get(config, key) do
        %{} = existing -> existing
        _ -> %{}
      end

    Map.put(config, key, put_nested(nested, rest, value))
  end

  defp deep_merge(left, right) when is_map(left) and is_map(right) do
    Map.merge(left, right, fn _key, left_value, right_value ->
      deep_merge(left_value, right_value)
    end)
  end

  defp deep_merge(_left, right), do: right

  defp maybe_reload_store do
    if Process.whereis(WorkflowStore) do
      _ = WorkflowStore.force_reload()
    end

    :ok
  end
end
