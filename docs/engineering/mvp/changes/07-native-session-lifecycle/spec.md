# P07 — 같은 책임의 native 세션을 이어가고 정확히 중단하기

Revision: 4 · 상태: 설계 후보 · 2026-10-19 · 번호는 계획 ID이며 실제 PR 번호가 아니다.
공통 시작·리뷰·전달 기준은 [PR 규약](../README.md)을 따른다. 실제 lifecycle qualification: NOT RUN.
이 명세를 유지·개정하며 아래 구현 단계를 여러 PR로 전달할 수 있다. PR마다 해당 단계·요구와 정확한 명세 판본을 고정한다.

## 1. 목적·요구·범위

기존 task를 재사용하고 필요한 경우에만 허용된 새 task를 만들며, 원본에서 실행·소유·종료를
확인한다. R01/R06/R09/R12–16, [CS](../../contracts/codex-sessions.md)의 CS-R2–6/8,
[NC](../../contracts/native-capability.md)와 [EX §3–6/9](../../contracts/execution.md)가 정본이다.
현재 `NativeRunner._model`의 assignment 반환은 실제 native task 생성·실행의 증거가 아니다.

| 여섯 설계 항목 | 이 명세의 결과 |
| --- | --- |
| 목적 | 세션 증식·중복 writer·Stop 접수만으로 소유 해제하는 오류 제거 |
| 책임 | native provider가 task/turn과 원본, Hydra가 현재 scope·admission·연결·receipt 검증 |
| 동작 | 충분한 inventory → exact owner 선택 → 허용 조작 → 원본 read-back → 같은 책임 계속 |
| 실패·복구 | source에서 요청/owner를 재발견; 유실·부분 조회는 보존하고 자동 재생성/해제하지 않음 |
| 완료 | reuse·authorized create·실행 중 interrupt·controller restart의 실제 양성 흐름 |
| 범위 | 한 host writer 1개. 신규 engine/daemon/세션 DB, 다른 host 자동 failover, 전체 task wrapper 없음 |

native Plan 모드와 저장소 계획·Goal을 구분하는 CS §3.1을 적용한다. 상태 읽기와 명시적 Goal
생성/교체를 분리하고 idle continuation·입력 대기·pause·budget의 실제 동작을 qualified 표면에서
확인한다. Plan-only에서 실행을 시작하거나 reconnect로 예산을 초기화하지 않는다. 임의 mode
전환을 구현하지 않으며 추가 예산·새 Goal·새 task의 실제 도구 권한을 보존한다.

## 2. 선행과 입력·출력

기존 유효한 legacy task/assignment로 시험할 수 있다. P09 전체 WorkBinding 전환이나 P04
질문 적용을 전역 선행으로 두지 않는다. 새 command를 쓰는 부분만 P02/CP의 admission 계약을
소비한다. project source/version 선택과 기존 progress 의미는 해당 소유 계약 그대로다.

- 입력은 현재 위임, exact work/attempt/step, qualified native source/actor/version, 현재 ticket·admission이다.
- 출력은 EX §6의 기존 provider record와 CP의 native observation이다. 공개 progress에 private ID를 추가하지 않는다.
- configured locator·task 제목·path 유사성은 후보 탐색에만 쓴다. 원본 owner와 실제 task/turn 연결을 별도로 확인한다.
- 생성 전 기존 연결을 충분히 조회할 수 있어야 하고 같은 요청의 생성 결과 재발견도 지원해야 한다.
- 실제 app 도구의 명시적 신규 task 요청·다른 task 메시지 권한을 보존한다. 일반 목표로 이를 합성하지 않는다.
- native-mediated와 직접 adapter 중 실제 지원 경로를 선택한다. 외부 Hydra가 현재 앱 도구를 호출할 수 있다고 전제하지 않는다.

### 활성화 전 닫아야 하는 native_control profile

CP의 `native_control` 행은 제품 조작 목록이며 현재 완성된 provider 입력 schema가 아니다.
P07은 qualified actor/version의 실제 source를 읽고 resume/interrupt별 target·expected·source revision,
owner/assignment 연결, 허용 필드·형식·default·오류, 접수와 실제 상태의 `CommandReplyV1` 매핑을
고정한 profile을 CP에 연결해야 한다. 존재하지 않는 native 필드·서명·CAS를 발명하지 않는다.
opaque source에 version/revision이 없으면 그 한계와 재조회 guard를 명시하고 동등한 보장을 주장하지 않는다.
이 producer/consumer 계약이 닫히기 전 해당 조작은 비활성이다. profile이 부족하다는 이유로 legacy
continuation·메시지·handoff의 부작용을 resume/interrupt 대체 경로로 호출하지 않는다.

### 구현 단계와 후속 인계

| 단계 | 시작 조건·구현 범위 | 완료 증거와 후속 소비 |
| --- | --- | --- |
| 연결 사실 확인 | 이미 위임된 exact task/owner에서 NC §2.2/3의 caller·surface·version·권한·coverage·transport와 조작별 원본을 특정한다. | 위 native_control profile의 확인된 입력·출력·한계를 CP에 연결한다. 정적 schema·새 서버의 성공은 기존 owner 제어의 증거가 아니다. |
| 최소 양성 실증 | 기존 owner의 원본 접근과 별도 제어 주체를 확인하고 해당 대상의 좁은 실제 제어가 위임돼 있어야 한다. 최소 adapter 구현을 포함할 수 있다. | 아래 reuse·실행 중 interrupt·restart와 별도 허용 create의 원본 증거를 조작별로 남긴다. 각 조작의 미지원/미확인을 다른 조작에 전이하지 않는다. |
| adapter와 소비자 연결 | 실증된 profile과 §5의 fixture/oracle을 고정하고 core guard에 연결한다. | 실제 producer→core→각 지원 consumer의 reply가 접수·실행·종료를 구분한다. 조작별 D/O가 충족된 경로만 활성화하고 후속 P08/P15에 정확한 능력·한계를 인계한다. |

이 순서는 실제 활성화의 근거 순서다. 독립 fixture·guard·비활성 adapter 구현은 실증과 병행할 수
있으며, 실증에 필요한 최소 adapter도 관련 D를 통과한 판본만 사용한다.

최소 실증 입력은 **위임된 기존 work/assignment 하나, exact owned task/turn, 현재 ticket과
admission, 원격 제어 caller와 실제 owner에 도달하는 지원 경로**다. 대상별 허용 조작·대기
timeout·호출 한도·실패 후 조회 경로를 먼저 기록한다. controller와 별도로 실행 중 제어를
수신하는 주체를 확인하며, 실행 worker가 다음 Hydra 호출을 할 때까지 기다리는 경로는
interrupt 실증으로 인정하지 않는다.

1. idle인 기존 task를 재발견해 허용된 다음 step에 재사용하고, 원래 task·assignment와 실제 실행을 read-back한다. 새 task/중복 dispatch는 0이다.
2. 허용된 실행 중 정확한 turn에 별도 caller로 interrupt를 요청한다. ACK와 실제 ended, child/process coverage를 각각 관측한다. 종료 미확인 동안 ticket을 해제하지 않는다.
3. controller 재시작 뒤 원본에서 같은 task·현재 실행 상태·남은 책임을 복원한다. 다른 owner·현재 step을 바꾸거나 Goal 예산을 초기화하지 않는다.
4. 신규 create는 실제 도구 조건에 맞는 별도 명시 위임이 있을 때만 한 번 수행하고 생성 결과를 원본에서 재발견한다. 이 위임이 없으면 create 시험만 NOT RUN으로 남기며 기존 task의 reuse/interrupt 결과는 유지한다.

조작별 실제 원본과 기대 결과가 일치하면 PASS다. 실행된 시험에서 target 오인·중복 실행·
ACK만으로 해제 등의 위반은 FAIL이다. owner 접근·권한 부족은 BLOCKED, 특정 source/version의
확인된 미지원은 해당 capability의 한계와 시험 BLOCKED로 기록한다. 실행하지 않은 사례는
NOT RUN이다. ACK 유실·late ended·경합은 §5의 결정적 fixture로 반드시 검증하고 실제 장애
주입을 기본 효과로 추가하지 않는다. NC §3/VF의 기존 검증 기록에서 정확한 소스·명세 판본,
현재 조건·원본 관측·판정·남은 책임을 연결한다. provider 필드가 없으면 새 필드로 보충하지 않는다.

P08은 실제로 확인된 exact owner/restart 능력만 소비한다. P15의 실제 정리·별도 host handoff와
전체 앱 화면은 이 최소 실증의 선행 조건이 아니다. interrupt 경로가 없으면 remote busy 제어를
완료로 표시하지 않고 해당 경로만 보류한다. 독립 guard·read-only projection·다른 조작은 계속
구현할 수 있다. 새 engine·credential·세션 저장소가 필요하면 현재 설계의 불충족을 보고하고
새 선택의 결정 전에는 도입하지 않는다.

## 3. source와 구현 순서

| source | 변경 책임 |
| --- | --- |
| `hydra_sdlc/native.py` | 기존 assignment와 provider 관측 연결; current identity와 stale 결과 검증 |
| `hydra_sdlc/control.py` | source별 lifecycle capability·coverage·접수/실제 종료를 분리한 projection |
| `hydra_sdlc/mcp.py`, bridge의 기존 command consumer | 같은 core handler의 negotiated profile·typed reply 검증. 새 tool은 추가하지 않음 |
| `hydra_sdlc/execution_boundary.py`, `hydra_sdlc/operations.py` | 기존 ticket/host writer/admission 재사용; native receipt만으로 임의 release 금지 |
| `plugins/hydra/skills/sdlc/SKILL.md` | 현재 task 재사용·원본 재조회·인계·독립 reviewer의 실제 역할 |
| 기존 native/restart/control suite, 예정 `tests/test_native_sessions.py` | source/조작/재시작과 실제 consumer까지 검증 |

1. NC qualification에서 사용할 actor·target owner·정확한 source/버전·각 조작을 고정한다. 미지원 조작은 개별 분리한다.
2. fake provider에 실제 source 형태의 공개-safe fixture와 독립 expected를 둔다. reuse/create/stop 양성도 먼저 실패하게 만든다.
3. bounded inventory→exact 연결→CS 선택표를 구현한다. partial lookup을 complete-empty로 바꾸지 않는다.
4. 같은 assignment의 dispatch/관측/interrupt를 기존 guard 안에 연결한다. 요청 전에 현재 권한·admission을 재검사한다.
5. ACK 유실 뒤 원본 조회로 같은 자원을 재사용한다. 원본에서 연결이 복원되지 않으면 추가 create/dispatch를 막는다.
6. 실제 ended와 필요한 child/process coverage 후 exact stopped checkpoint를 연결한다. archive나 timer로 종료를 대신하지 않는다.
7. source consumer·CLI/control 회귀와 독립 리뷰 뒤 허용된 owner 하나에서 실제 lifecycle을 시험한다.

내부 adapter 클래스·함수 분해는 구현 재량이다. 지원되지 않은 create key 저장, task metadata,
interrupt endpoint를 제품 의미에서 만들어내는 것은 재량이 아니다. 그 부분은 source qualification 공백이다.

## 4. 구체 선택·실패·회복

| 상황 | 결과와 다음 행동 |
| --- | --- |
| 같은 책임의 valid idle task | 재사용하고 다음 허용 step까지 진행; 새 task 0 |
| 같은 task의 active exact turn | 현재 실행 관측/허용된 steer; 동일 step 재전송 0 |
| 충분한 조회에 적합 task 없음 | 실제 명시 권한과 생성 재발견 경로가 있을 때 한 create; 새 identity read-back 뒤 진행 |
| create/dispatch ACK 유실 | 원래 요청/작업 source로 조회→같은 task/step 확인→계속; unknown이면 추가 create 0 |
| foreign/duplicate/잘린 history | 원본 충돌 표시·해당 효과 hold; 최신 task 자동 채택/타 자원 archive 0 |
| Stop 접수·ended 미확인 | admission 차단 유지, ticket/edits 보존; 실제 종료 또는 지원 control 경로 필요 |
| exact ended·checkpoint 보존 | matching ticket만 해제; unrelated step과 writer 불변 |
| controller restart/compact | 현재 원본을 다시 읽어 같은 assignment 복원; summary만으로 authority 재구성 0 |
| host handoff | 이전 owner의 종료·보존·대상 권한/원본 접근 확인 후 같은 책임; unknown 자동 failover 0 |

fork/compact/handoff는 CS 선택표의 필요·권한이 있을 때만 사용한다. 독립 review는 exact candidate의
읽기 책임으로 연결하며 fork 생성만으로 독립성·CODEOWNER 승인을 얻지 않는다. 실제 자원 archive와
보존/retirement는 [P15](../15-resource-retirement/spec.md)의 별도 결과다. P15 완료를 P07의 기본 reuse 시험 선행으로 두지 않는다.

## 5. TC·검증·oracle

CS의 provider 제약을 다음 fixture에 포함한다. 이들 fixture 성공은 실제 기존 owner 접근의
qualification을 대체하지 않는다.

| 추가 사례 | 독립 oracle |
| --- | --- |
| P07-S01: default sourceKinds·loaded-only·ephemeral/archived 누락 | 전체 부재/새 task 생성 0, coverage 한계 보존; 알려진 정상 기존 task는 재사용 |
| P07-S02: 서로 다른 thread가 같은 session root 공유 | 반환된 identity 유지, thread ID로 owner/root 추정 0 |
| P07-S03: 원격 창구 같지만 실행 host/cloud 환경 변경 | 재qualification, 옛 writer 해제·같은 checkout 주장 0 |
| P07-S04: reconnect/status/Goal 복원 | objective·누적 사용량 보존, budget reset/increase 0; 실제 교체는 위임 변경으로 구분 |
| P07-S05: 외부 method 문자열·archive 실패·read 실패·hook timeout | 임의 RPC/영구 delete/resume·exec fallback 0; 실제 guard 유지 |

| 연결 ID | 사건 | PASS oracle / 금지 효과 |
| --- | --- | --- |
| EX-D01/03, NC-D06 | same/foreign task·동시 begin·중복 wake | 정상 exact owner로 한 번 진행, writer 1; 제목 기반 채택·중복 dispatch 0 |
| NC-D05, EX-D02/03 | create/assignment 전송 전후 ACK 유실 | 원본 read-back으로 같은 task 복원→다음 행동; 추가 create/ticket 0 |
| NC-D04/09 | partial page·scope가 다른 cursor·403·새 enum | partial/unknown 유지, false empty·자동 downgrade 0 |
| NC-D02/07, EX-D04/13/14 | Stop→late ended A, 현재 B; Pause 경합 | exact stopped만 release; barrier 뒤 신규 dispatch·현재 B 변조 0 |
| NC-D08, EX-D18/22 | parent ended/child active·foreign resource·archive ACK | 전체 종료/cleanup 성공 추정 0; 원본 복구 뒤 같은 책임 계속 |
| EX-D03/09, CS-R5/6 | restart·compact·review head 변경 | 같은 owner/context 복원·stale review 거절; 새 task나 자기평가로 대체 0 |
| NC-D10 | private identity·대화·path canary | 공개 DTO/log/fixture 유출 0, 허용된 lifecycle 의미 유지 |
| NC-D03/09, CP-D01/15/17 | 실제 qualified field fixture→core→native MCP/bridge 각각의 정상 reply, unknown field·stale expected·다른 owner | 양쪽 consumer가 같은 접수/실제 상태를 정확히 해석; malformed reply·미지원 profile은 거절, legacy/메시지/handoff fallback 0 |

| 상태 | 검증 명령·관측 |
| --- | --- |
| 기존 회귀 | `python3 -m unittest discover -s tests -p 'test_native*.py' -v` |
| 기존 회귀 | `python3 -m unittest discover -s tests -p 'test_restart_ownership.py' -v` |
| 기존 회귀 | `python3 -m unittest discover -s tests -p 'test_control.py' -v` |
| 예정; 생성·수집 확인 후 | `python3 -m unittest discover -s tests -p 'test_native_sessions.py' -v` |
| O 예정 | EX-O01/O02: 기존 owned task의 reuse·active interrupt·exact ended·restart, 명시 허용된 create/유실 재발견 |

공통 규약의 지정 runner에서 실행하며 이번 설계에서는 실행하지 않았다. D는 필수다. L은 이 단위의
typed lifecycle 판정에는 N/A다. 자연어 역할·인계 packet의 충실성은 VF L05/06 및 독립 리뷰에서
확인하지만 owner·종료 판정을 모델에게 맡기지 않는다. O는 필수이며 standalone 새 서버 시험이
기존 desktop owner 제어를 증명하지 않는다. app/host restart는 controller restart와 별도 기록한다.

## 6. 리뷰·호환·끝조건

reviewer는 실제 source의 authority, positive lookup, ACK/actual 구분, writer 경합, 현재 도구 조건,
복구 뒤 정상 진행을 확인한다. source-only merge는 live capability를 꺼 둔 상태로 가능하지만
reuse/create/interrupt/restart의 실제 양성 증거가 남으면 P07 capability와 v1은 완료가 아니다.
미지원 feature를 단순 `unsupported`로 반환하는 D만으로 O를 대체하지 않는다. 기존 다섯 MCP의
continuation 의미와 progress v1을 유지한다. 실패 시 기존 task·edits·ticket·원본 참조를 보존하며
자동 새 세션·legacy fallback·도구 권한 확대 없이 원래 책임에서 복구한다.
