# P16 read-side foundation verification

Scope: the first source increment of P16 revision 4. This record does not accept
the full P16 specification, installed operation or the complete v1 goal.
Related work: Issue #3.

## Fixed design and source boundary

- Base: `2d23a141d354e1795e16a5ef2a26367be9693e09`.
- [P16 revision 4](spec.md), SHA-256
  `981fc80580fc9fd69859d7b6870a410ca03dc4121619f9191e0c4640a2878226`.
- [Maintained control-plane contract](../../contracts/control-plane.md), SHA-256
  `b82792481dc6042b79307f78685f7b1b8e11863e425ec6fef9c73afd65eaa291`.
- [Implementation boundary](implementation.md): existing P12 bridge and reducer,
  transient read state, inert original text and guarded original-Issue navigation.
  No new workflow, native, connection, delegation or cleanup command is enabled.

## Deterministic behavior

The DOM fixture executes the actual `index.html` and app entry point. Only the
native bridge is synthetic. Inputs reuse the publishable P12 source corpus.
The existing-host control passed before implementation; the seven missing
lifecycle outcomes failed through purpose assertions with no skipped method.
The unchanged eight methods passed after implementation. A further keyboard
recovery test reproduced one assertion failure alongside two valid controls;
the same three methods passed after correction.

| Case | Required outcome | Local result |
| --- | --- | --- |
| Existing-entry control | Actual host entry renders; no mutation | PASS |
| Overview | Actual v3 read; observed projects and delegated goal references | PASS |
| Project/work navigation | Original, readiness, question, answer, acceptance, application, delivery, result and cleanup remain separate | PASS |
| Partial/unknown activity | Missing work or reported native activity cannot imply zero active, ended execution or goal completion | PASS |
| Original markup | Literal text only; no injected DOM, script or network action | PASS |
| Scoped read failure | Keep independent records and uncertain prior observations; no private error text or fabricated empty success | PASS |
| Late source completion | Keep the currently selected project | PASS |
| Binding replacement | Clear prior source view and selection before adopting the new connection | PASS |
| Keyboard recovery | Recover the refresh control when no later interaction owns focus | PASS |
| Expired evidence | Retain source text; disable original navigation from stale evidence | PASS |
| Later keyboard interaction | Read completion cannot steal focus from another project | PASS |

Commands from `apps/mac`:

```sh
node --experimental-strip-types --test tests/tower.test.ts tests/tower-events.test.ts
npm test
npm run build
npm run verify:theme
```

Local results: 11 lifecycle methods, 363 complete frontend methods, TypeScript/Vite
build and theme verification pass. The existing suite includes actual Python
producer/TypeScript consumer fixtures, using Python 3.14.2 in this verification.
No Rust source changed. Required remote/native build checks remain part of CI;
these local results do not claim CI or independent review completion.

## Running-screen observation

The actual built frontend was rendered in a fresh headless Chromium context with
synthetic bridge replies and the public P12 frame. Page requests were fulfilled
from that build; unrelated page origins were blocked. Desktop overview/work detail,
light/dark appearance and a 390px mobile overview were captured and shared before
PR publication. The mobile document width was 390px, with no horizontal overflow.
The browser reported no page errors or external page requests. No native Hydra or
Codex operation was dispatched, and the one-shot browser was closed afterward.

Built JavaScript SHA-256:
`b12148574f5c48dc825feceb780aaaa79e7fc7798d4e8c4a68497974c11a6cce`.
Built CSS SHA-256:
`962520c3b8fd8dee16ea02c69d3cd1b02eb85d7cabaa3d1f738b19233f1b0da9`.
Overview screenshot SHA-256:
`4a271b8686033f95dc8f7f8595d6ac349c980076a2574cfb509333c5a9621367`.

This is source-fixture screen evidence. It does not establish the installed
runtime, authenticated remote answers, a real scoped command/read-back, actual
native execution, two-project operation or resource retirement.

## Delivery and remaining responsibility

Exact-head CI and independent code/security reviews are pending at preparation.
Merge and actual-main CI must be verified on their original provider records.
The PR links those changing delivery results instead of rewriting this fixed
source observation as an operating acceptance.

P16 still owns qualified typed command consumers, complete V2 read-only migration,
installed read/scoped-command observations and final operating-screen acceptance.
The full v1 goal also retains remote Q&A/Pause/restart/explicit Resume, two real
independent projects and complete owned-resource closure. Unsupported source
mappings remain visibly unconfirmed and cannot authorize these operations.
