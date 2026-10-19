# P15 — 원래 provider에서 자원 책임 종료

Revision: 3 · 상태: 설계 후보 · 2026-10-19 · 구현·시험·운영: NOT RUN

[공통 PR 인계](../README.md)를 따른다. 구현 전 accepted spec 판본·실제 base/head·dirty 후보와
기존 Issue/PR·owner를 대사하고 이 변경의 검토 범위를 고정한다. 현재 문서는 수용 전 후보다.

## 목적과 범위

완료·취소한 목표나 명시한 유휴 자원의 불필요한 세션·예약·worktree를 정리하되, 회복할 작업과
다른 책임의 자원을 보존한다. 결과 완료, 실행 종료, admission 해제, 자원 정리는 별개다.
이 PR은 [v1 요구](../../spec.md)의 R01/R06/R12/R13/R16과 W6b를 구현할 단위다.
상태·권한 정본은 [EX §9](../../contracts/execution.md#9-pausestop취소재시작정리),
capability는 [NC](../../contracts/native-capability.md), 명령은 [CP §8](../../contracts/control-plane.md#8-command-envelope와-공통-guard), 판정은 [검증 설계](../../verification.md)다.
제품 F07/F12의 명시적인 ‘정리만 수행’을 포함한다. 기본 Pause/Stop은 정리를 시작하지 않는다.
설계·Goal은 새 권한이 아니다. 새 scheduler·자원 DB·transcript mirror·강제 삭제·임의 kill은 제외한다.

## 요구와 불변조건

| ID | 필요한 결과와 이유 |
| --- | --- |
| P15-R1 | exact work/attempt와 provider instance·resource identity·현재 owner를 연결한다. 제목·경로 이름·label만으로 소유권을 만들지 않는다. |
| P15-R2 | interrupt/cancel의 잔여 execution ticket 회수는 종료/never-dispatched의 positive evidence와 필요한 보존 read-back을 요구한다. 정상 exact checkpoint의 step retirement는 EX/P05대로 유지한다. |
| P15-R3 | 미보존 diff/untracked/ignored 필요 파일·unpushed/unmerged 결과·활성 실행을 확인하고 원래 provider에 회복 가능한 보존을 확인한다. 확인 불가·foreign·미보존 dirty는 유지한다. |
| P15-R4 | 취소는 남은 개발·delivery를 멈추지만 이미 전달한 결과·미확정 효과·정리 의무를 지우지 않는다. 취소를 성공·merge로 제조하지 않는다. |
| P15-R5 | 취소된 책임에만 속하고 더 이상 답이 필요 없는 질문은 원본 취소 근거로 not-applicable 판정한다. 답변 완료로 꾸미지 않으며 다른 살아 있는 책임의 질문은 유지한다. |
| P15-R6 | full ownership/참조 범위에서 해당 책임만 끝낸다. 공유 schedule/task/worktree 전체를 삭제하지 않고, 지원되는 분리와 read-back이 없으면 보존한다. |
| P15-R7 | cleanup pending을 닫힌 원래 Issue·provider inventory에서 재발견한다. 유실·재시작·부분 조회가 새 구현 attempt·중복 Issue·삭제 재전송을 만들지 않는다. |
| P15-R8 | 기본 paused/stopped는 정리도 hold한다. 별도 명시된 cleanup-only는 원래 권한·exact target·비활성·보존 아래 열거 효과만 허용하며 admission mode/revision·업무 효과를 바꾸지 않는다. |

## 입력·출력·정본과 의존성

| 경계 | 소유 원본과 입력 | 출력·보존 위치 |
| --- | --- | --- |
| 작업 결과 | GitHub의 인증된 progress, exact source/contract/head, 실제 merge/main 또는 원래 책임의 취소 근거 | 전달 사실과 cleanup pending은 기존 work record에 유지; 취소를 legacy `completed` predicate에 억지로 넣지 않음 |
| native 실행·질문 | NC가 자격 확인한 원래 provider의 task/turn, owner, ended, 질문 귀속·취소/대체 근거 | 원본 archive/참조 상태와 coverage. private ID·답변·경로는 공개 GitHub에 넣지 않음 |
| worktree | 기존 lifecycle provider의 resource identity/owner/release, 실제 Git 상태와 보존 receipt | 같은 provider의 보존·retirement read-back; Hydra에는 두 번째 registry 없음 |
| schedule | 원래 provider의 exact schedule, 현재 owner·전체 책임 참조·현재 상태 | 원본 변경 결과. 공유 책임은 유지하고 현재 목표의 해소 여부만 파생 표시 |
| 제어·발견 | 기존 admission revision, bounded ticket, provider inventory와 GitHub active work | source별 pending/unknown/unsupported와 원본 링크를 projection; cache가 권한이나 정본이 되지 않음 |
| 정리만 요청 | 실제 UI/native의 명시적 exact target·효과 요청과 현재 권한; CP typed profile·source checks | 원래 provider의 보존/회수 결과와 좁은 요청 receipt. caller flag나 Goal 문구가 새 권한이 되지 않음 |

W4a의 exact assignment/종료 관측, W6a의 전달·실패 책임, W3의 admission/coverage와 연결한다. 취소 정리에 merge 성공을 요구하지 않는다.
Native archive/schedule/worktree는 각각 자격 확인된 capability만 켠다. 미지원이 독립 guard TC를 막지 않는다.
provider 읽기·보존/종료 guard는 독립 구현 가능하다. 원격 cleanup 명령을 연결하는 단계에는
[P02](../02-project-admission/spec.md)의 공통 typed handler·target/runtime/admission 검증과
[P05](../05-checkpoint-only/spec.md)의 `hydra_command_v1` 공통 MCP 배선이 필요하다.
P05 checkpoint 전체나 P14 전달 완료를 전역 선행으로 요구하지 않는다. P15는 그 기반 위의
cleanup profile·MCP consumer·정상/금지 효과 TC를 소유하고, provider 지원만으로 원격 정리를
활성화하지 않는다. 앱 consumer와 실제 wire TC는 P16 후속 단계가 P12 기반을 소비해 소유하며
원격 MCP 검증을 대체하지 않는다.
공유 자원의 현재 목표 참조만 해소됐다는 원본 증거가 있으면 자원은 남겨도 해당 의무는 끝난다.
참조 범위가 partial이거나 다른 책임과 분리할 수 없으면 pending이다.

## 현재 소스와 구현 변경점

`workspace.py`의 `issue_numbers()`/`completed()`는 선택적 lifecycle provider에 발견과
정리를 위임하며 `retired: true`를 요구한다. provider의 실제 보존·read-back 구현은 별도다.
`issue_numbers()`의 목록/빈 목록은 전체 coverage를 증명하지 않으므로 adapter 관측과 구분한다.
`runner.py`는 완료된 닫힌 Issue의 resource cleanup 재진입을 갖고 있다. `native.py`의
matching ticket retirement는 native task archive/실제 종료 관측과 다르다. 현재 stopped
checkpoint의 caller 선언을 NC의 ended 증거로 승격하지 않는다. `control.py`의 schedule
coverage는 unverified이며 실제 native stop/archive/schedule 정리 지원을 선언하지 않는다.

수정 소유는 `control.py`/`mcp.py`의 CP cleanup typed handler, `operations.py`/`native.py`/`runner.py`의
내부 exact cleanup effect scope, `github.py` discovery·좁은 정리 기록, `workspace.py` provider, `progress.py` 표시다.
현재 `guard(cleanup=True)`는 mode 예외일 뿐 권한이 아니다. caller boolean·broad `completed`/`advance`
callback으로 우회하지 않는다. 검증된 provider의 exact operation만 연결하며 가짜 PR/merge는 넣지 않는다.

## 구현 순서와 정상 흐름

1. 기존 discovery에서 open/closed active work, pending progress, ticket와 provider의 owned
   resource를 합쳐 읽는다. source별 coverage를 유지하며 hint만 있는 외부 자원을 채택하지 않는다.
2. 결과/권한 있는 취소 또는 명시 자원 요청과 남은 효과·관측·질문·공유 책임을 대조한다. unknown은 원래 intent로
   read-back한다. Issue close를 취소로 추정하지 않으며 취소 질문 N/A는 원본 책임에 연결한 파생 판정이다.
   완료/취소 cleanup만 기존 `next_action=resource_cleanup`·표식을 쓴다. 명시 유휴 자원 정리는 원 work의 phase/wait/next_action을 보존한다.
   cleanup-only에는 CP의 현재 명시 요청·target/provider instance/owner/operation/source pin을 검증한다.
3. interrupt/cancel 뒤 남은 execution ticket은 실제 ended 또는 qualified never-dispatched와
   exact 보존 checkpoint를 확인해 matching ticket만 회수한다. Stop ACK·Pause·close·timeout은 ended가 아니다.
   정상 candidate_ready/needs_decision의 final record read-back→step retirement는 EX/P05 소유이며 전체 turn 종료가 필요 없다. task archive/자원 정리는 별도다.
4. CP가 고정한 한 exact resource operation에서 provider의 보존→보관/회수 또는 schedule 해제만 수행한다.
   실행 비활성·보존·전체 공유 참조를 확인한다. enabled schedule 자체를 실행 중인 turn으로 보지 않는다. 실제 active면 기다리며 cleanup만으로 Stop하지 않는다.
   pause/stop 단독과 달리 별도 cleanup-only scope만 mode 예외다. 상위 gate도 바꾸지 않고 권한 철회는 존중한다.
5. coordinator와 control barrier에서 expected admission revision·권한·소유를 다시 검사하고 한 번 dispatch한다.
   scope는 provider 효과와 기존 cleanup 분기의 pending/settled·active 기록만 허용한다. 새 model/배정/commit/
   push/PR/merge/close/resume은 0회다. 필요 보존 snapshot은 provider 기능이며 새 업무 commit이 아니다.
   provider conditional guard를 사용한다. 외부 race에서 비활성/소유 보장 불가인 파괴 효과는 unsupported/hold다.
6. provider 결과를 exact target/instance에서 read-back한다. archive가 descendant를 일부만
   처리했으면 partial이다. worktree 부재·API 404·응답 성공 문자열만으로 성공을 추정하지 않는다.
7. 모든 잔여 의무가 해소된 경우만 기존 progress의 정리 상태와 active 표식을 의미 있게 갱신한다.
   일회성 목표는 끝내고 새 유지보수/task/예약을 만들지 않는다. 전체 coverage 없이는 안전한 Quit도 선언하지 않는다.

## 장애·재시작·호환

최초 현재 요청은 실제 명시 범위·권한과 source 검증으로 실행하며 새 durable first-send flag를 요구하지 않는다.
유실/재시작은 원래 request/provider intent·receipt와 동일 owned resource를 read-back한다. 원본 scope·권한·
미적용 확정·EX-D17 budget을 복원할 때만 재요청 가능하다. 이미 retire된 결과는 재사용하며 unknown은 보존한다.
request receipt는 영속 원본이 아니다. 원본이 없으면 관측만 가능하며 재생성·blind retry·횟수 초기화는 금지다.
Pause 뒤 기본 신규 dispatch 0은 유지한다. 별도 cleanup-only는 해당 effect scope만 허용하고 이전 전송은 대사한다.
disk 부재·보존 실패·archive 부분 실패는 전달 성공을 되돌리지 않고 같은 Issue의 cleanup pending을 유지한다.
외부 active 표식 유실은 provider/ticket와 대조해 orphan/unknown으로 보인다. 마지막 자원 삭제 뒤
progress 갱신이 실패해도 기존 pending work에서 재발견하며, 재시작 때 workspace를 새로 만들지 않는다.
닫힘·reparenting은 기존 attempt의 자원 책임을 새 부모로 이전하거나 소멸시키지 않는다. exact work
참조로 잔여 의무를 유지하고, 공유 관계가 바뀌면 현재 provider 참조를 다시 확인한다.
legacy progress v1과 기존 `completed()` 성공 경로는 유지한다. 새 JSON key·취소 상태·provider API를
임의로 추가하지 않고 필요 시 소유 계약의 version/capability 변경과 consumer 호환을 함께 검토한다.

취소 책임 판정은 저장 enum이 아니라 `원본의 유효한 exact work 취소`와 현재 잔여 의무의 조합이다.
그 취소가 확인된 non-completed phase도 `resource_cleanup`/active/provider hint로 closed discovery에
포함한다. settled는 pending 효과·필수 관측·유효 질문·자기 자원 책임이 모두 해소되고 그 범위의
원본 coverage가 complete일 때다. 원 phase/전달 사실을 유지한 채 `next_action=None`을 read-back하고
active 표식을 제거·read-back한다. 실패하면 같은 작업을 다시 발견하며 정상 개발을 재개하지 않는다.
`runner._issues`, GitHub active-label 처리, `progress_hint`/control은 이 취소 분기를 동일하게 소비한다.
취소 원본이 없거나 범위가 불명하면 settled를 추정하지 않는다. `completed`/가짜 merge로 호환시키지 않는다.

## 검증 사례와 오라클

각 TC는 fake provider의 독립 호출 ledger/고정 원본 snapshot, 임시 Git의 실제 보존 상태로 판정한다.
기대값을 구현 함수로 계산하지 않는다. `retired: true`를 돌려주는 mock만으로 preservation을 증명하지 않는다.

| TC / 연결 | 초기 상태·자극 | 필수 관측과 금지 효과 |
| --- | --- | --- |
| P15-T01 / P15-R1–3·7, EX-D22/O05 | 전달·main 확인 뒤 owned inactive 자원, closed Issue | 실제 provider 상태 종료·보존물 재조회·pending 해소. push/PR/merge/close 반복 0; 항상 hold 구현은 FAIL |
| P15-T02 / P15-R2·8, EX-D13/14 | 잔여 ticket의 Stop ACK/실제 ended/never-dispatched·Pause; 정상 needs_decision/candidate_ready | 잔여 회수는 positive 종료 근거만 수용. 정상 checkpoint는 turn 진행 중 step retirement→같은 task 질문 가능. 별도 정리 요청 없는 paused delete 0 |
| P15-T03 / P15-R3·6, EX-D22 | dirty/untracked/필요 ignored/unmerged, foreign/active/shared 자원 | 원본 내용·타 owner 불변. 보존 확인된 자기 자원의 정상 정리는 가능; 공유 참조 미확인은 삭제 0 |
| P15-T04 / P15-R4–7, EX-D22, VF-D11 | 일부 전달 뒤 closed 취소·non-completed phase, restart, 불필요 질문 A와 다른 책임의 질문 B | 같은 책임 발견→A만 N/A·B 보존→자기 정리→settled/active 제거 read-back. 결과 유지; 가짜 답변·merge·새 개발 0 |
| P15-T05 / P15-R7, EX-D16/17/22 | 각 provider 효과 전/성공 후 응답 전/원본 read-back 후 progress 전 crash | 같은 자원·작업 재발견, matching 결과 재사용, unknown 재전송·budget 초기화·새 attempt 0 |
| P15-T06 / P15-R1·7, EX-D18/22, NC-D08 | closed/reparented work, partial inventory/active label 유실/disk 부재/descendant 실패/미지원 | 원래 책임과 정확한 pending/unknown/unsupported 유지; zero-active·cleanup complete·Quit 성공 추정 0. 복구 후 같은 책임 진행 |
| P15-T07 / P15-R1·8, EX-D24 | private canary·위조 owner·교체된 provider instance·stale target | 공개 payload/log canary 0, foreign archive/delete 0; 정상 source 복원 후 유효 정리 가능 |
| P15-T08 / P15-R1–3·6–8, EX-D31 | 같은 paused/stopped 상태: 요청 없음/유효 cleanup-only/active·foreign·stale·권한 철회·공유/응답 유실·restart | 유효 inactive owned만 보존·정리. mode/revision·기존 phase/wait/next_action 불변·업무 효과 0. 원본 소실 replay 0; 복원 뒤 대사, 살아 있는 goal은 미완료 유지 |

현재 존재하는 회귀 명령은 `python3 -m unittest discover -s tests -p 'test_host_resources.py' -v`,
같은 형식의 `test_native.py`, `test_workspace.py`, `test_active_labels.py`, `test_operation*.py`다.
새 P15 사례는 계획된 `test_mvp_delivery_contract.py`와 영향받는 기존 suite에 구현한다.
모든 실행은 허용된 test/storage 환경에서 수행하고 실제 case 목록·수집 수·revision을 기록한다.
이번 문서 작성에서 시험은 실행하지 않았다. 0 tests/skip/미지원은 PASS가 아니다.

## 검토·완료·회복

D는 위 TC와 producer/consumer 회귀다. L은 취소 질문·Stop/정리 요청의 범위 해석과 완료 판정에 L09/EX-L02를
적용한다. 순수 provider parser/lock 분기만 바꾸면 그 변경의 L은 이유를 기록해 N/A 가능하다.
O는 EX-O05/O06·VF O06의 실제 owned task/worktree/schedule, paused/stopped 그대로 cleanup-only 성공과 restart read-back이다.
실제 adapter를 주장하는 범위에서 O는 필수이며 미지원은 BLOCKED, 미실행은 NOT RUN으로 남긴다.
독립 spec-fidelity 검토는 P15-R→TC→코드와 누락 시나리오를, 별도 품질·보안 검토는 보존·경합·
소유 위조·private 공개를 확인한다. 최종 수정 revision에서 영향 TC와 필수 CI/리뷰를 다시 연결한다.
PR의 source-ready와 보호 merge/main, 설치본 provider 수용·운영 완료를 구분한다. 필수 O가 없으면
자원 정리 운영 완료라고 하지 않는다. 실패는 원래 작업에 원인·다음 대사·남은 책임을 남기며,
구현 결함은 회귀 TC로 수정하고 계약 변경이 필요하면 해당 소유 명세를 먼저 개정·검토한다.
