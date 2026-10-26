# P06 — 같은 질문의 결정을 적용하고 원 단계 재개

Status: Design candidate, revision 7, 2026-10-26. P06 is a plan ID, not a pull-request number.
수용 판본·구현 head·D/L/O 결과는 [공통 변경 절차](../README.md)에 연결한다. 현재 모든 실행은 NOT RUN이다.
Prior review baseline: CP revision 12, EX revision 10, NC revision 9. The coordinated
delegated-profile amendments require independent technical acceptance before dependent code.

## Delegated public decision and ordinary continuation

`codex_delegated_v1` implements P04's accepted dialogue responsibility boundary.
Its technical mechanism is a candidate; implementation and D/L/O evidence are **NOT RUN**.
The existing `decision_apply` and six-role qualified-native-source path retain their
original meaning. Agent proposal JSON must never be converted into qualified
`DecisionSelection`, `DecisionSnapshot` or `DecisionCallCoverage` facts.

The new native-only `workflow_step.decision_submit` accepts public text and exact
current work/basis pins through CommandV1 and trusted WorkflowBinding. CP owns the
closed schema and grant. The server independently verifies accepted project/spec/intake,
service actor, repository identity, the waiting source attempt and current admission.
Round 1 is supported; a conflicting proposal or later amendment is held, not overwritten.

The server constructs the canonical version-2 public context with
`profile: codex_delegated_v1`, the existing key/basis fields and a deterministic resume
UUID derived from the canonical proposal and accepted basis. The exact version-2 receipt
pins the context digest. Version 1 keeps its original profile. Reuse strict byte/actor/
unedited-record/read-back validation; a mixed profile or conflicting payload is not a match.
No private dialogue, answer hash, native locator or claimed human identity is published.

`decision_submit` may POST one context and one receipt per invocation, each followed by
read-back. Across recovery invocations, persisted lifetime limits are three context
POSTs and three receipt POSTs for the original exact intent. Before each POST, increment
and fsync its counter on the same existing ownership inode. Failed persistence means no
dispatch. Counters never decrease or reset after unknown responses, empty reads or reboot.
An exact append-only duplicate may be folded into one semantic intent; a different body
cannot replace the owned intent. Every recovery invocation needs fresh current guards.

Publication cannot write progress, create a ticket/assignment, invoke native work or
change admission. Its terminal result is the existing decision receipt after exact pair
read-back; partial confirmed references and ownership remain visible on uncertainty.
The delegated decision and continuation receipt variants carry only the additional
closed `profile: codex_delegated_v1` discriminator. CP owns its target/progress/ref
proof requirements and paired Python/Rust/TS qualification; original v1 variants
remain unqualified. A tag is not a grant or independently authenticated human answer.

Only a separately authorized typed `continue` can consume the pair. Re-read the exact
GitHub pair, current work/policy and admission, compute the full intended resumed progress
record, and durably bind its canonical digest plus exact context/root before the one
mutable resume PATCH. Recovery hashes the authenticated actual full progress record;
it does not reconstruct overwritten carried fields from current policy. No second PATCH,
new resume UUID or assignment is permitted while the original result remains unknown.
Exact confirmed root/progress can retire the matching owner and reuse the result.

The actual `WorkDecisionGuard` consumer resolves a v2 decision directly from authenticated
GitHub evidence. Before consumption require one exact intent for the waiting attempt and
complete bounded relevant collection; afterward require the exact stored native root.
Do not select the newest comment, accept the legacy root-null fallback or call the old
provider's six-role/technical-history methods for a normal v2 continuation. Legacy
begin/advance cannot initially consume an unconsumed v2 pair to bypass WorkflowBinding.
Already consumed v2 work must revalidate its exact pair/root during ordinary effects.

This increment cannot dispatch a delegated technical successor. Its replan path is
explicitly unsupported; it must not fabricate zero-effect coverage to satisfy the old
`native_replan` consumer. The old qualified-source profile remains intact. Positive
acceptance must reach an actual same-work original-phase assignment and checkpoint on
the ordinary path, rather than always waiting at a leftover provider requirement.

Independent oracles cover forged approval/authority changes, exact pins and literal
bytes, Pause between effects, every durable-counter crash boundary, exhaustion across
restarts, late results, wrong carried progress fields, profile separation and private-data
exclusion. Native remote clarification/answer and controlled real progress remain required
operational evidence. No new grant, native message, installation or execution is implied.

## 1. 목적·요구·범위

사용자의 유효한 답을 원래 책임에 적용하고, 명시적 project Resume 뒤 허용된 다음 행동을 실제로
진행한다. 답변 수신·채택·공개 결정·배정·실제 실행을 하나의 성공으로 합치지 않는다.
[R01/R06/R07/R08/R10/R12/R16](../../spec.md#3-요구사항과-판정)에 연결된다.

| 항목 | 이 변경의 경계 |
| --- | --- |
| 정본 | [EX §7](../../contracts/execution.md#7-질문결정다음-wake)의 결정 intent/receipt·resume·수정·retry 계약 |
| 입력/출력 | [CP §8](../../contracts/control-plane.md#8-command-envelope와-공통-guard)의 CommandV1/Reply·decision_apply와 continue ceiling, [NC §2.1](../../contracts/native-capability.md#21-질문과-재개를-위한-원본-연결)의 qualified 원본 |
| 포함 | 한 source attempt/질문, exact 공개 pair, preallocated resume UUID, 원 phase 진행·좁은 checkpoint |
| 제외 | 새 질문/명령 DB, 대화 복제, 모델 승인 대체, 새 scheduler, 전체 native 제어·전체 UI |
| 현재 차이 | 현행 legacy marker parser는 exact native 선택·판본·public intent 연결과 응답 유실 복구를 보장하지 않음 |

## 2. 선행과 변경 소유

[P02](../02-project-admission/spec.md), [P03](../03-work-source-compatibility/spec.md),
[P04](../04-native-answer-source/spec.md), [P05](../05-checkpoint-only/spec.md)의 관련 계약이 필요하다.
P03의 project-v2 최소 gate와 명시적 legacy source만 선행하며 전체 WR adoption은 요구하지 않는다.
P04 미확인 중에는 고정 source fixture로 parser/coordinator/D를 진행할 수 있다. 실제 자동 적용은
source/transport/권한/복원 자격 전까지 unavailable이며 source-only 병합과 이 기능의 O 완료를 구분한다.

| 현재 경로 | 구체 변경 |
| --- | --- |
| `hydra_sdlc/github.py` | EX exact 공개 body parser·서비스 actor·coverage·semantic fold·직접 ref 재조회 |
| `hydra_sdlc/runner.py`, `hydra_sdlc/native.py` | 순수 decision coordinator, 공통 begin/advance guard, pinned resume 소비 |
| `hydra_sdlc/control.py`, `hydra_sdlc/mcp.py` | 기존 CommandV1 handler의 decision_apply 및 workflow_step.continue route·개별 capability·결과 |
| P04의 qualified reader 경로 | 재조회한 선택/판본/authority/귀속/public proposal를 작은 입력 경계로 전달 |
| `tests/test_github.py`, `tests/test_native.py`, `tests/test_native_wait_identity.py`, `tests/test_checkpoint_continuation.py` | 기존 parser/진행/호환 회귀 |
| `tests/test_mvp_execution_contract.py`, `tests/test_control_commands.py` — 예정 | 결정 coordinator·effect ordering·명령/재시작 통합 |

## 3. 입력·처리·종점

wire·정규화·크기·retry 수치는 CP/EX를 복사해 재정의하지 않는다. caller proposal_ref는 읽을
대상의 제안이며 권한 증거가 아니다. source_checks의 지원 원본 판본을 실제로 재조회한다.
결정 의미는 Codex가 판단하고 Hydra는 source/authority/현재 기준/owner/admission을 검사한다.

1. read-back된 needs_decision와 retire된 write step, 현재 선택·public proposal·작업 기준을 확인한다.
2. 공개 context 자체를 append-only exact intent로 기록한다. raw private ID/답변/hash는 공개하지 않는다.
3. 서비스 actor/key/exact bytes가 같은 physical duplicates만 한 semantic intent로 접는다.
   trusted 후보의 다른 payload는 conflict, outsider marker는 채택하지 않은 데이터다.
4. exact context read-back 뒤 그 DecisionPin에서 만든 receipt를 게시·read-back하고 decision_apply를 끝낸다.
5. 다음 명시 continue/begin은 같은 public intent의 resume UUID를 기존 progress에 적용한다.
   exact record 확인 전 ticket/assignment를 만들지 않으며 같은 UUID를 재발견하면 재사용한다.
6. 원 phase의 실제 행동과 P05 candidate_ready checkpoint를 확인한다. 정상 답을 영구 대기시키면 실패다.

이 PR은 native 자동 재개의 공통 guard뿐 아니라 **CommandV1 workflow_step.continue 진입**도
소유한다. continue는 CP의 기존 위임 안에서 현재 lifecycle을 계속하는 넓은 명령이며
checkpoint_only/verify_only로 광고하지 않는다. handler가 server-owned ceiling을 선택하고,
payload에서 phase override·resume UUID·effect allowlist를 받지 않는다. P13의 verify_only·P14 전달
명령과 native_control의 실제 interrupt/resume 지원을 이 capability에 묶어 켜지 않는다.
typed continue 입력·ProgressPin·private 반환은 [CP 후속 profile](../../contracts/control-plane.md#후속-continueverify_only-profile)을
그대로 따른다. phase까지 일치하는 원본 기대값을 재검사하고 legacy 함수를 blind 호출하는
fallback이 아니라 기존 begin/advance와 같은 identity·native decision guard로 들어간다.
current assignment/unknown owner가 남아 있으면 새 배정을 하지 않고, 유효한 현재 책임이면 실제 다음 행동을 진행한다.
현재 native controller의 assignment는 지원되는 native_handoff_v1으로만 돌려준다. bridge에
private prompt/cwd를 보내거나 전달할 곳 없는 assignment를 먼저 만들지 않는다.

각 효과 직전 현재 guard를 다시 확인한다. paused 중에는 read/projection과 기존 exact stopped
보존만 허용한다. Resume ACK/답변 수신이 그 뒤의 권한을 계속 보장하지 않는다.
append-only retry는 exact 동일성·현재 guard·확인된 EX budget 아래에서만 가능하다. 호출 횟수
미확인은 0이 아니며 구별 불가능한 crash 창은 unknown이다. mutable resume PATCH에는 이
중복 규칙을 적용하지 않고 blind retry·새 round/attempt로 우회하지 않는다.

## 4. 구현 순서와 의미 있는 RED

1. P04의 실제 지원 범위와 fixed private source fixture를 분리한다. 의미/권한 판정 fixture는 독립 검토한다.
2. 기존 legacy parser가 exact native 선택 없이 재개하는 반례와 정상 연결된 답의 양성 oracle을 만든다.
3. EX body serializer/parser·actor/coverage 분류·semantic pair 결정을 순수 함수로 구현한다.
4. 최소 coordinator를 실제 GitHub adapter/공통 admission guard에 연결하고 각 dispatch/read-back을 fault 주입한다.
5. workflow_step.continue route와 개별 capability를 연결하고 모든 begin/advance/command 진입에 동일
   native decision guard를 적용한다. P03 구버전 거절과 caller-supplied ceiling 거절을 확인한다.
6. 선택 수정·restart·정상 원 phase 진행까지 연결한 뒤 qualified 환경의 첫 왕복 O를 수행한다.

| 정본 TC | 사건 | 독립 oracle / 금지 효과 |
| --- | --- | --- |
| EX-D11/12, VF-D05–08 | checkpoint→질문→Pause→답변→Resume→원 phase candidate | paused 쓰기 0, valid Resume 뒤 semantic 적용/배정 1회와 실제 진전. same-task role만으로 승인 0 |
| EX-D12/24 | trusted duplicates·다른 body·outsider 위조·private canary | exact semantic fold, trusted 충돌, outsider로 정상 pair 차단 0, 공개 누출 0 |
| EX-D12/17, VF-D06 | POST 전/후 crash·0개/partial 조회·호출 budget 소실 | 원본 확정 결과 재사용. EX 범위의 동일 POST만 bounded, unknown count 초기화·무한 retry 0 |
| EX-D12/13 | resume PATCH lost ACK·old body·late commit·Pause 경합 | same UUID read-back 전 배정 0, blind PATCH retry 0. 적용 후 신규 dispatch 0 |
| EX-D12, VF-D05/08 | 답 수정: POST 전/context 후/resolved 미소비/이미 소비 | 과거 효과 보존, EX amendment/replan 후 수정된 다음 행동까지. 최신 댓글 자동 선택·자동 rollback 0 |
| EX-D12/18 | source 소실·source attempt 변경·legacy route 시도 | 해당 경로 unknown/unsupported, marker fallback·새 task/attempt 우회 0. 독립 기능은 유지 |
| EX-D12/15, CP-D15/17 | 유효 continue와 capability 미지원/변경된 expected/임의 ceiling 입력 | 유효 현재 책임의 다음 단계 양성 진전. 무효 입력 dispatch·legacy fallback 0, 다른 lifecycle control 자동 활성화 0 |

## 5. 검증·리뷰·완료 증거

아래 루트 기준 명령은 기존 suite와 예정 suite를 구분한다. 실행은 허용된 격리 환경에서 수행한다.

```sh
# 기존 회귀
python3 -m unittest discover -s tests -p 'test_github.py' -v
python3 -m unittest discover -s tests -p 'test_native*.py' -v
python3 -m unittest discover -s tests -p 'test_checkpoint_continuation.py' -v
python3 -m unittest discover -s tests -p 'test_mcp.py' -v
# 예정 통합 / 실제 case 수집 후
python3 -m unittest discover -s tests -p 'test_mvp_execution_contract.py' -v
python3 -m unittest discover -s tests -p 'test_control_commands.py' -v
```

D는 실제 parser/serializer/controller와 재시작 후에도 남는 source fixture를 연결한다.
L07/EX-L02는 답변 선택·공개 제안·질문 판단이 바뀌는 경우 고정 입력/모델/prompt/rubric으로 평가한다.
판단 변경이 없으면 동일 판본의 기존 L 증거를 재사용하며, 새 fixed fixture의 D로 L을 대체하지 않는다.
O는 [첫 통합 흐름](../../verification.md#첫-통합-흐름--질문-대기와-project-pauseresume)의
실제 remote 답변·원본 재발견·명시 Resume·정상 checkpoint다. source 미지원이면 그 항목은 BLOCKED다.

독립 리뷰는 private/public join, outsider DoS, 호출 여부가 같은 관측으로 보이는 crash,
retry budget, native guard 우회와 정상 수정 후 진전을 확인한다. 완료 증거는 exact spec/head의
D/L 결과와 필요한 O, 원본 safe refs, installed identity, 공통 CI/리뷰다. mock 성공은 O가 아니다.

## 6. 호환·회복·인계

기존 progress v1과 기존 source/resume 연결을 유지한다. 새 native receipt는 legacy resolved
한 줄로 소비하지 않으며 P03 gate 없이 자동 적용을 켜지 않는다. private 선택·public pair·현재
후속 책임을 원본에서 재발견하고 local journal을 만들지 않는다. 미확정 PATCH는 다음 write를 보류한다.
P07/P08에는 qualified 재진입과 남은 책임, P12/P16에는 DecisionView의 원본 근거와 미지원 범위를 인계한다.

## 7. Review corrections and pre-workspace continuation

The current-progress fence is checked again after decision-source IO and before
each effect. A newly observed decision wait must remain intact. A local ticket
created in this same invocation may be released only with positive evidence that
its intent writer was never invoked and its exact ownership still matches. An
invoked writer or uncertain ownership retains its ticket for original recovery;
absence of an acknowledgment is not proof of non-dispatch.

Typed continuation shares the existing guarded begin preparation for a positively
confirmed stopped record whose ticket was already released. It may finish the
remaining native-field retirement and continue the same responsibility. Active,
foreign or unknown ownership remains held; no stop result is inferred.

The CP revision 11 pre-workspace amendment preserves existing progress with a null
head. Nullable pins and result receipts follow CP's exact rules; no new progress
store, synthetic SHA, workspace allocation or broader candidate schema is added.
Tests must prove both the waiting and subsequent positive continuation paths.
Original source read-back, admission, current policy, native provenance and
independent final-head review/CI remain required. These source corrections do not
establish installed or remote acceptance.

## 8. Authorized technical successor continuity

EX revision 9 owns the native-specific public root marker, consistent observation from one authenticated comment body and guarded technical successor contract. This change preserves a
consumed DecisionPin across legitimate replans and restart while keeping answer
amendment separate. A source-attempt-only descendant match is prohibited.

The existing native controller/runner and GitHub record writer remain the owners;
no parallel tracker, journal, scheduler or task executor is added. Technical
successor coverage is a distinct optional qualified original-source capability.
Its absence prevents that automatic write and never blocks unrelated supported
operations. Ordinary legacy replan behavior and the existing two-field source
getter remain compatible. Final acceptance requires the positive and uncertain
recovery cases in EX, normal impact tests, exact-head independent review/CI and
the separately qualified actual native flow.

## 9. Original-effect coverage and monotonic retry observations

EX revision 10 closes conflicting work after an unknown technical successor,
including restart with no local witness. Native common-entry guards and accepted
answer-amendment publication use qualified original work-effect coverage. Missing
coverage holds only the affected native operation. The implementation adds no
durable cache, reconstructed permission or caller-controlled bypass.

Retain counts from the first source observation through the guarded dispatch and
later calls. Extend the fixed source adapters to supply actual fixture history
and retain all existing acceptance assertions. New regressions must demonstrate
that cache loss cannot authorize amendment consumption and that a decreasing
source count cannot reset the three-write bound. These requirements do not claim
that an installed provider can already supply the original facts.
