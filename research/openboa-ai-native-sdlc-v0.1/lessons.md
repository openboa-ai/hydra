# Lessons from External Evidence

The 40-source corpus converges on a modest conclusion: better agent work comes from clearer goals, legible repositories, bounded execution, objective review, and feedback into the system. Longer prompts or more autonomous sessions do not remove those needs.

## What the evidence supports

### Start with a human-owned goal

A goal states the outcome, owner, acceptance evidence, dependencies, and risk. A plan organizes the work and tasks bound a reviewable change. A session, worktree, branch, or pull request is an attempt to advance the goal, not the goal itself.

This follows the issue-centered orchestration and ownership patterns in OA-02, AN-02, GH-01, and LI-01.

### Treat context and the harness as engineering surfaces

Agents perform better when repository boundaries, local commands, architecture, and acceptance checks are discoverable and executable. The harness supplies tools and context; the sandbox bounds execution. Neither should be replaced by prompt-only rules.

This is strongly supported by OA-01, OA-03, OA-05, AN-05, AN-06, AN-07, GH-04, and SG-01.

### Verify outcomes, not activity

Tests, previews, review, evals, and observed runtime behavior answer whether the outcome works. Token counts, session length, lines changed, or a plausible final message do not. When path quality matters, retain a compact trajectory of consequential tool use and decisions.

This follows OA-06, AN-03, AN-04, NV-02, RE-01, and VE-01.

### Scale autonomy inside explicit boundaries

Autonomy can grow inside a worktree or sandbox while approval remains required at boundaries such as secrets, identity, security, privacy, irreversible state, and public commitments. The connected account identifies the actor; it does not define authority.

This is supported by OA-03, AN-06, NV-01, NV-05, GH-02, LI-01, and VE-04.

### Build three loops, not a new lifecycle vocabulary

The recurring practices fit three ordinary loops:

- development turns a goal and plan into a reviewed change;
- delivery moves an approved change into its target environment and observes it;
- learning turns failures and evidence into better context, skills, tools, tests, evals, graders, or policy.

These loops summarize the corpus without proposing a new graph file format or a second issue-state system.

## Vocabulary

Use the ordinary OpenAI product terms `goal`, `plan`, `task`, `worktree`, `handoff`, `review`, `approval`, `skill`, and `plugin` for the operating guide.

Use Anthropic's `session`, `harness`, `sandbox`, `outcome`, `eval`, `grader`, and `trajectory` only when those words name a specific technical concern more accurately. Provider-specific implementations remain examples, not OpenBoa policy.

## Source grading and verification

The corpus was checked against first-party engineering, research, security, product, and platform pages on 2026-08-23. The offline validator checks fields, counts, duplicate IDs and citations, grades, organization coverage, and URL syntax; it does not claim continuous page reachability.

| Grade | Meaning | Use |
| --- | --- | --- |
| A | Reproducible implementation, evaluation, security, or operational detail | May support guidance when corroborated |
| B | Detailed first-party engineering case or technical documentation | Strong supporting evidence |
| C | Product announcement or company-reported result | Directional only; never sufficient alone |
| D | Secondary commentary | Discovery and triangulation only |

Vendor claims remain source-specific. The corpus overrepresents vendors, and independent evaluations and incident reports are still needed before stronger policy conclusions.
