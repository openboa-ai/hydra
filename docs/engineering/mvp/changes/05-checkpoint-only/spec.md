# P05 — 후속 실행 없이 원 단계 checkpoint 완료

Status: Design contract, revision 3, 2026-10-22. Operating acceptance remains separate.
수용 판본·구현 head·검증 결과는 [공통 변경 절차](../README.md)에 연결한다. 현재 실행 증거는 NOT RUN이다.
검토 기준은 CP revision 7·EX revision 7다. 구현 시작 때 수용한 immutable 판본을 고정한다.

## 1. 목적·요구·범위

Codex가 맡은 쓰기 단계를 마쳤거나 질문을 해야 할 때 owned edits와 원 단계 완료/대기를
확정하고 반환한다. 정상 candidate도 불필요한 Stop 없이 진전하며, 검증·다음 배정·전달은 시작하지 않는다.
[R06/R08/R10/R12/R16](../../spec.md#3-요구사항과-판정)의 exact assignment·질문·복구에 기여한다.

| 항목 | 이 변경의 경계 |
| --- | --- |
| 입출력 정본 | [CP §8](../../contracts/control-plane.md#8-command-envelope와-공통-guard)의 checkpoint_only·CommandReplyV1·checkpoint receipt |
| 단계 정본 | [EX §3–4/§7](../../contracts/execution.md)의 기존 assignment·write phase 완료·retirement |
| 포함 | design/implementation/correction의 candidate_ready/needs_decision, 기존 exact stopped 보존 |
| 제외 | failed 자동 correction, review phase, 질문 자동 적용, 검증/review/새 assignment/전달 |
| 현재 차이 | 기존 checkpoint는 retirement 뒤 원 phase 후처리를 수행하고 넓은 continuation으로 이어질 수 있음 |

## 2. 선행과 변경 소유

[P02](../02-project-admission/spec.md)의 typed admission/expected guard를 재사용한다.
P03의 project-v2 gate는 이 **standalone checkpoint**의 선행이 아니다. 기존 assignment와
progress 표현을 쓰며 새 native 결정 protocol을 소비하지 않기 때문이다. 자동 결정 재개는
P06이 P03/P04와 함께 활성화한다. P01 reader를 이 PR의 선행으로 강제하지 않는다.

| 현재 경로 | 구체 변경 |
| --- | --- |
| `hydra_sdlc/native.py` | exact binding·phase/outcome 검사, 좁은 checkpoint dispatch, 최종 record 후 retirement |
| `hydra_sdlc/runner.py` | 기존 `_finish_*`의 원 단계 검사/완료만 재사용하는 작은 helper 경계; broad continuation 유지 |
| `hydra_sdlc/control.py`, `hydra_sdlc/mcp.py` | 공통 CommandV1 handler에 좁은 route 및 additive `hydra_command_v1` 연결 |
| `tests/test_native.py`, `tests/test_checkpoint_continuation.py` | 정상 candidate·decision·correction·fault-before-retire 검증 |
| `tests/test_mcp.py`, `tests/test_native_wait_identity.py` | 정확한 tool/schema·owner/old step·기존 5 tool 회귀 |
| `tests/test_control_commands.py` — 예정 | unsupported operation/outcome·receipt·effect ceiling 사례 |

## 3. 입력·처리·종점

CP의 exact assignment·runtime/admission 기대값을 받는다. caller가 phase나 authority를 정하지
않으며 source_checks=[]이다. summary는 private 제한 내에서만 처리하고 공개 로그·progress에 넣지 않는다.
effect_key는 CP의 exact checkpoint key이며 process-local consumed set이 영속 멱등 증거는 아니다.

1. 실제 target/assignment/owner와 현재 intake/spec/policy/head를 확인한다. unsupported 입력은 효과 전에 거절한다.
2. owned edits를 기존 workspace 경로로 checkpoint하고 scoped spec·원 phase 조건을 검사한다.
3. candidate_ready는 design_done/spec_review 안내, implementation_done/verification 안내,
   correction의 정확한 completed/origin/resume 의미를 기록한다. 안내가 후속 실행은 아니다.
4. native_correction이 있으면 phase=design인 spec-only correction도 correction 분기가 우선이다.
5. needs_decision은 원 phase와 product_decision 대기를 함께 보존한다. stopped는 기존 종료/보존 증거가 필요하다.
6. 최종 head·완료/대기 record를 원본에서 read-back한 **뒤에만** exact step/ticket을 retire하고 receipt를 반환한다.

`_candidate_result` 전체·`_correct`·검증·review·advance를 호출하지 않는다. 기존 helper를 단순
호출해 우연히 제한을 지키는 것이 아니라 하위 효과도 server가 고정한 ceiling을 따르게 한다.
scope/spec 실패는 기존 진단/재계획 wait를 보존한다. candidate_ready 문자열만으로 성공하지 않는다.

## 4. 구현 순서와 의미 있는 RED

1. 독립 효과 oracle을 만들어 commit·최종 phase record·read-back·ticket release·다음 dispatch를 구별한다.
2. 현행 retirement 전후 fault를 주입해 최종 record 확인 전에 ticket이 해제되는 실패를 확인한다.
   tool 미등록·import 오류를 behavior RED로 세지 않는다. 기존 동작이 이미 맞는 사례는 보존 회귀다.
3. `_finish_*`의 원 phase 검사/기록만 작은 공유 함수로 분리하고 legacy 결과 동등성을 검증한다.
4. 좁은 controller 경로와 receipt를 연결한 뒤 MCP에 여섯 번째 도구를 추가한다.
5. 정상 진전·부분 실패·재시작을 검사하고 마지막에 기존 다섯 도구의 broad 의미를 다시 확인한다.

| 정본 TC | 사건 | 독립 oracle / 금지 효과 |
| --- | --- | --- |
| EX-D06/15, CP-D15 | 유효 candidate_ready 세 write phase | 최종 phase/head read-back 후 matching retirement. 다음 검증/배정/전달 0 |
| EX-D06/08 | spec-only correction, spec 변경·미존재·잘못된 scope | correction 귀속 보존. 실패는 checkpoint/진단 대기, 성공 phase 합성 0 |
| EX-D11 | needs_decision 뒤 같은 task의 질문 준비 | edits·origin·대기 보존. 결정 적용/답변 생성/후속 attempt 0 |
| EX-D04/14 | 현재 B에 과거 A, fake stopped, unknown 종료 | B 불변. 무권한 commit/release 0. confirmed stopped의 기존 보존 양성 사례 유지 |
| EX-D06, CP-D12 | commit·최종 record·read-back·retirement 각 경계 crash | 확인 전 owner 보존. 재시작 후 같은 효과 대사; old step/outcome 소실 시 요청 receipt는 unknown |
| EX-D05/15 | 중복 command, failed/review phase, 미지원 version | 무근거 중복 commit·legacy fallback 0. 확인된 현재 phase의 별도 continue는 다음 일을 정상 선택 |
| CP-D16/17 | private summary·tool inventory 전환 | 공개 canary 0. P01의 당시 5 tools와 P05 이후 6 tools를 판본별 검사; legacy 5 signature 불변 |

## 5. 검증·리뷰·완료 증거

아래는 루트 기준 기존 명령이다. 새 사례를 실제 수집한 후 허용된 격리 환경에서 실행한다.
신규 command suite는 파일 생성 전 실행 가능/통과로 세지 않는다.

```sh
python3 -m unittest discover -s tests -p 'test_native*.py' -v
python3 -m unittest discover -s tests -p 'test_checkpoint_continuation.py' -v
python3 -m unittest discover -s tests -p 'test_mcp.py' -v
python3 -m unittest discover -s tests -p 'test_operation*.py' -v
# 예정 suite
python3 -m unittest discover -s tests -p 'test_control_commands.py' -v
```

D는 실제 임시 Git/workspace·실제 parser/serializer·MCP SDK 경로와 제어된 외부 transport를 잇는다.
L은 N/A: 후보 판단 기준/prompt를 바꾸지 않고 기존 결과를 좁게 소비한다. source-only PR의 O는
P06 첫 실제 왕복에서 재사용하며, 실제 native 종료 능력은 이 PR의 테스트로 입증하지 않는다.
필수 MCP integration의 skip/0 case는 PASS가 아니다. 최종 전체 회귀·CI는 공통 절차를 따른다.

독립 리뷰는 정상 candidate의 진전, spec-only correction 우선순위, 최종 record 전 retirement,
ceiling 우회, legacy 호환을 확인한다. 완료 증거는 exact head의 사건열·원본 최종 record·금지 효과,
RED/GREEN·회귀/CI·독립 리뷰와 MCP input/output 계약이다.

## 6. 호환·회복·인계

기존 다섯 MCP의 이름/입력/continuation 의미는 유지한다. 새 route 실패 시 그 경로로 fallback하지 않는다.
CommandReply는 CP projection과 별도이며 NC native_context 진단을 포함하지 않는다.
최종 원 phase 완료가 확인됐어도 old request 귀속이 사라지면 해당 재요청만 unknown이다.
현재 progress와 전체 guard가 허용하는 다음 continue까지 막거나 candidate 작업을 다시 실행하지 않는다.
P06에는 exact checkpoint receipt와 effect ceiling을, P12/P16에는 명령 결과와 실제 실행의 구분을 인계한다.

## 7. 내부 구현 단계의 구체 경계

revision 2의 첫 구현 단계는 `control_commands.execute_checkpoint_command`와 원 단계 완료
core다. MCP 여섯 번째 도구·transport 인증·native 종료 증거 adapter는 후속 통합이며,
이 내부 단계의 PASS를 P05 전체 완료나 원격 Codex 운영 증거로 세지 않는다.

- 내부 caller context는 현재 repository와 operation grant를 전달하는 trusted adapter 입력이다.
  command JSON·summary·native 진단에서 만들지 않는다. checkpoint scope는 admission 쓰기를 허가하지 않는다.
- policy 관측 후 현재 context/config/runtime을 다시 확인하고, 각 실제 효과의 짧은 admission lock에서
  expected revision을 비교한다. 여러 외부 정본을 하나의 원자적 transaction으로 만들었다는 뜻은 아니다.
- `stopped` 문자열만으로 cleanup 권한이 생기지 않는다. 별도 server 주입 종료 관측이 exact target,
  host/control binding, assignment, current/complete writer·descendant 종료를 입증해야 한다.
  이 adapter는 기본 제공하지 않으며 누락·부분·stale 관측은 효과 없이 거절한다.
- `checkpoint_only`는 기존 progress의 임시 next_action이다. 최종 phase 전체 read-back 후 기존
  checkpoint 필드에 `native_complete_` 접두 marker를 쓰고 다시 읽는다. 원 checkpoint 코드는
  marker 안에 가역적으로 보존하고 retirement 시 복원한다. 별도 ledger나 persistent ID는 추가하지 않는다.
- marker 이전 ACK 유실은 exact 원본 완료 상태를 대사한다. accepted-spec 중간 record는 scope/budget
  진단보다 먼저 쓰일 수 있으므로 완료로 추정하지 않고 남은 검사를 마친다. 결과 provenance가 없는
  새 Git HEAD는 parent/message/cleanliness만으로 채택하지 않는다. 해당 요청은 reconcile 대기이며,
  독립적으로 입증된 exact stopped recovery만 현재 owned commit과 판단 맥락을 보존할 수 있다.
- 원본 progress ref는 인증된 실제 Issue comment locator다. 요청 ID나 Issue 번호로 가공해 만들지 않는다.
  progress-only writer는 discovery label 변경을 포함하지 않는다.

실행·회귀·미실행 범위와 판본은 [검증 기록](verification.md)에 남긴다.

## Standalone admission-provider wiring

Standalone STDIO main supplies P02's optional installation-scoped admission provider
using the same fixed absolute host-config locator as the controller and command core.
Only the official SDK's injected Context reaches this internal provider. It ignores
request/client/task metadata and grants only admission_set for explicitly configured
numeric scopes. create_server's embedded default remains no provider/no grant.
There is no checkpoint grant or ended-task proof in this profile; checkpoint_only
and all other operations retain their own existing authority requirements. Missing
SDK caller-context support still refuses writes. Preserve legacy tools, closed input
schema, privacy middleware, unknown-effect replies and the existing STDIO transport.
P02 owns parser/digest/revocation tests; this consumer owns actual SDK and main-wiring
tests. Neither fixture success nor policy adoption is installed/native qualification.
