# Source Provenance and Verification

**Verification date:** 2026-08-23

## Method

The initial corpus was discovered and checked through official first-party pages using the web research tool. Each URL in sources.csv was selected from the organization's own engineering, research, security, product documentation, or platform documentation domain.

The offline validator checks:

- required fields;
- source count;
- duplicate IDs and citations;
- allowed evidence grades;
- organization coverage;
- URL syntax.

It intentionally does not claim that an HTTP request is always reachable. Some publisher pages, especially OpenAI pages, may return anti-bot responses to command-line requests while remaining available in a browser or search index. Reachability is therefore a manual review item, not a release-time proof.

## Provenance map

| Organization | First-party domains used | Primary evidence focus | Caveat |
| --- | --- | --- | --- |
| OpenAI | openai.com | harness, orchestration, safety, SDK, internal adoption | Product and internal-use claims remain source-specific |
| Anthropic | anthropic.com, resources.anthropic.com | agent patterns, long-running harnesses, evals, managed agents, sandboxing | Engineering posts describe experiments, not universal guarantees |
| NVIDIA | developer.nvidia.com | autonomy risk, security controls, evaluation, skill qualification | Technical blog guidance still requires local threat modeling |
| Google/DeepMind | blog.google, research.google | managed environments, coding agents, agent topology | Product announcements are marked B/C rather than normative by default |
| GitHub | github.blog, docs.github.com | issue-to-agent flow, safe outputs, permissions, repository context | Preview documentation can change; re-check before policy adoption |
| Cursor | cursor.com | cloud-agent fleet and review artifacts | Company-reported adoption claims are grade C |
| Factory | factory.ai | agent-native inner loop and objective verification | Product framing requires local validation |
| Replit | replit.com | browser testing, long runs, snapshots, reversibility | Autonomy and cost claims are self-reported |
| Vercel | vercel.com | durable workflows, sandboxing, previews, observability, approvals | Platform implementation is an adapter, not OpenBoa policy |
| Linear | linear.app | human ownership, delegation, permissions, activity | Agent API and product behavior can evolve |
| Sourcegraph | sourcegraph.com | shared code intelligence and context provenance | Large-codebase findings need local retrieval evaluation |

## Treatment of claims

- Grade A/B evidence may support a candidate rule when corroborated and locally validated.
- Grade C claims are preserved as directional evidence and never establish a rule alone.
- No Cognition/Devin source with comparable operational detail was found in this pass; it is recorded as a source gap.
- Independent evaluations and incident reports are required before promoting vendor consensus into an approved doctrine.
