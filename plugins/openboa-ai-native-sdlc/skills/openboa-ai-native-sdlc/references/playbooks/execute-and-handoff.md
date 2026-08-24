# Execute and hand off

**Change rate:** fast. This is a replaceable method, not doctrine.

Use this playbook to implement, delegate, recover, or continue long-running work.

## Execute from ground truth

1. Confirm the exact repository, base, branch or worktree, and dirty state.
2. Read the nearest instructions and inspect the affected system before changing it.
3. Work in meaningful increments that keep the final outcome coherent.
4. Verify after each risky or irreversible-to-recreate step, not after every trivial edit.
5. Keep the plan and GitHub work item aligned with discoveries that change scope, dependencies, or acceptance.

Delegate a subtask with its own input boundary, output, allowed files or systems, evidence, and integration point. Parallel collaborators must not edit the same state without an explicit coordination mechanism.

## Recover before retrying

On resume or failure:

1. Read the durable work item and latest plan.
2. Inspect the live repository, branch, checks, deployment, and external system.
3. Compare intended state with observed state.
4. Determine whether an external effect already occurred.
5. Continue from the last verified state, repair, compensate, or stop.

Bound retries, tool calls, time, cost, and subagents. Repeatedly sending the same prompt is not a recovery strategy. Change the context, test, tool, implementation, or plan when evidence shows the current approach is failing.

## Hand off only when needed

A handoff is a continuity artifact, not a substitute for finishing routine work. Use it when another collaborator must decide or continue.

Include:

- outcome and current state;
- exact repository, branch, pull request, and relevant revision;
- work completed and work remaining;
- observed checks and external effects;
- uncertainty, blocker, or decision needed;
- the next safe action and its required authority.

Do not hand off hidden reasoning or a stale chat summary. Provide facts another collaborator can re-check.
