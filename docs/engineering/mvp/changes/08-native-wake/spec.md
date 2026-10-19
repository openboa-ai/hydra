# P08 — 턴이 끝난 뒤 같은 책임으로 제한된 재진입

Revision: 4 · 상태: 설계 후보 · 2026-10-19 · 번호는 계획 ID이며 실제 PR 번호가 아니다.
공통 시작·리뷰·전달 기준은 [PR 규약](../README.md)을 따른다. 실제 wake/schedule qualification: NOT RUN.
이 명세를 유지·개정하며 아래 구현 단계를 여러 PR로 전달할 수 있다. PR마다 해당 단계·요구와 정확한 명세 판본을 고정한다.

## 1. 목적·요구·범위

외부 결과를 기다린 뒤 native가 같은 책임을 다시 읽고 허용된 다음 결과까지 진행한다.
R01/R06–08/R12–16, [EX §7.4/9](../../contracts/execution.md),
[NC](../../contracts/native-capability.md), [CS-R7/8](../../contracts/codex-sessions.md)가 정본이다.
현재 `control.py`의 schedule coverage는 unverified다. 이 문서는 설치된 자동 재진입을 주장하지 않는다.

| 여섯 설계 항목 | 이 명세의 결과 |
| --- | --- |
| 목적 | 사람이 매번 깨우지 않아도 대기 책임을 잇고 불필요한 예약·중복 실행을 끝냄 |
| 책임 | native scheduler가 예약과 실행 원본, Hydra가 위임·원본 변화·admission·다음 행동 검증 |
| 동작 | 기다릴 조건 고정 → 허용된 native 재진입 → 현재 source 대사 → 한 다음 결과 또는 bounded wait/종료 |
| 실패·복구 | schedule 요청 유실/host offline/중복 tick을 원본에서 대사; 새 schedule/attempt로 덮지 않음 |
| 완료 | turn 뒤 실제 wake→허용 결과, 완료/종료 뒤 불필요한 예약 책임 없음의 실제 증거 |
| 범위 | 기존 native 기능만 사용. 숨은 timer/cron/daemon, 고정 coordinator task, 무기한 유지보수 제외 |

CS §7의 native Goal continuation과 외부 사건/미래 시점의 예약을 구분한다. 활성 Goal이 지금
진행할 수 있는 일을 위해 추가 heartbeat를 만들지 않는다. 고정 30분 예약을 모든 작업의
기본값으로 강제하지 않는다. 실제 선택은 현재 위임·지원 surface·대기 조건에 연결하고 질문만
남거나 책임이 끝난 예약의 pause/retire를 관측한다.

## 2. 선행·입출력·선택

P07의 exact task/owner/restart 능력 또는 이를 이미 제공하는 qualified 경로가 필요하다.
전체 P09 전환이나 모든 UI 완료를 선행으로 두지 않는다. 위임은 목표·허용 효과·대기 조건·재평가
한계·끝조건을 포함한다. 실제 scheduler source/actor/권한과 원본 재발견을 확인한 뒤에만 켠다.

입출력은 EX의 provider record와 현재 work/goal 참조, CP의 coverage/command receipt를 재사용한다.
schedule ID·원문 prompt·실행 이력을 Hydra DB 또는 public progress에 복제하지 않는다.
지원되는 source에서 책임↔schedule 연결과 현재 상태를 다시 찾을 수 있어야 한다.

| 현재 상황 | 선택 |
| --- | --- |
| 즉시 가능한 위임 내 작업 | 같은 turn에서 계속; 예약 생성 0 |
| 외부 CI/review 등 유효 대기 조건 | 지원 이벤트 또는 기존 책임의 bounded native 예약; 실제 지원되는 하나의 경로만 |
| 인간 답변만 필요 | 원 질문 창구 유지; 전용 polling 예약 중지/정리 또는 공유 대상에서 제외할 권한·source 확인 |
| 독립 가능한 다른 작업 존재 | current writer가 없고 그 작업 위임/guard가 유효하면 진행; 높은 우선순위 대기로 starvation 없음 |
| 완료·취소·위임 종료·유용한 조건 없음 | 새 작업 0, 해당 예약 책임 종료를 P15로 연결 |
| partial inventory·owner unknown | 재생성 0, coverage unknown 유지; 전체 schedule 0으로 추정하지 않음 |

기존 대화 예약은 같은 책임 재진입의 우선 후보다. 독립 예약은 매 실행 새 chat을 만들 수 있으므로
이를 자동 대체재로 선택하지 않는다. 현재 앱의 예약 조건이 실제 권한을 제공하는지 확인하고,
지원되지 않는 event API를 발명하지 않는다. [공식 예약](https://learn.chatgpt.com/docs/automations)

### 구현 단계와 후속 인계

| 단계 | 시작 조건·구현 범위 | 완료 증거와 후속 소비 |
| --- | --- | --- |
| 연결 사실 확인 | NC §3에 따라 caller·surface·설치/version·권한·turn 뒤 실행 주체·source coverage·transport를 고정한다. 책임↔예약, 별도로 제안/전달/거절 원본을 특정한다. | 현재 지원되는 경로 하나와 미확인 의미를 기존 검증 기록에 남긴다. Goal continuation·외부 wake·발견 제안의 증거를 구별한다. |
| 최소 양성 실증 | P07의 필요한 owner/restart 능력과 해당 예약·효과·종료의 위임이 있어야 한다. 필요한 최소 adapter 구현을 포함할 수 있다. | 아래 실제 turn 종료→재진입→한 결과→원본 종료의 증거를 남긴다. 제안 원본은 별도 양성·restart 실증으로 판정한다. |
| adapter와 소비자 연결 | 실증된 source 의미와 §5의 독립 oracle을 고정한다. | 기존 guard·coverage·원본 대사를 연결하고 P15와 실제 종료를 검증한다. fixture 통과와 실제 지원이 모두 있는 경로만 활성화한다. |

이 순서는 실제 활성화의 근거 순서다. 독립 fixture·guard·비활성 adapter 구현은 실증과 병행할 수
있으며, 실증에 필요한 최소 adapter도 관련 D를 통과한 판본만 사용한다.

최소 실증 입력은 **위임된 기존 책임 하나, exact task/owner, 실제 대기 조건 하나, 지원되는
기존 예약 또는 명시적으로 생성이 허용된 예약, 다음 허용 효과 하나, 종료 조건**이다. native
요청을 하기 전에 대기 timeout·호출/비용 한도·종료 권한과 ACK 유실 때 확인할 원본을 고정한다.
지원 종료 경로가 없는 예약을 먼저 만들지 않는다. 하나의 경로로 검증하며 timer와 event를
동시에 만들지 않는다. 이미 유효한 예약이 있으면 재사용한다.

1. 원래 turn을 끝낸 후 지원 native 주체가 같은 책임으로 실제 재진입하는 것을 관측한다. 같은 turn 안의 반복이나 수동 메시지는 이 증거를 대신하지 않는다.
2. 재진입 직후 현재 원본·admission·기존 실행/효과를 대사하고, 충족된 조건의 다음 허용 결과를 한 번 수행해 read-back한다.
3. 실제 미전송이 확인된 경계에서 controller를 재시작하고 같은 책임을 복원한다. 전송 여부가 unknown이면 재전송보다 원본 확인을 먼저 한다.
4. 위임된 정상 끝조건에 도달하면 P15의 종료 계약에 따라 해당 예약 책임을 종료하고 native 원본에서 read-back한다. 시험 전에 정한 다음 실행 가능 시점까지 관측한 추가 wake 수와 관측 범위를 기록한다. 무기한 무실행이나 전체 scheduler 부재를 주장하지 않는다.

발견 제안은 별도 위임된 관찰 범위·유용한 근거·원래 native 기록을 입력으로 한다. 실제
미전송이 확인된 첫 제안을 허용 창구로 한 번 전달하고 결과를 원본에서 읽은 뒤 controller를
재시작한다. 같은 근거의 재알림은 0이어야 한다. 기존의 실제 거절/재검토 조건은 원본에서
재발견하고, 거절·새 근거·응답 유실의 변형은 §5의 D/L로 검증한다. 시험을 위해 사람의 거절을
꾸며내거나 별도 위임 없이 알림·Issue를 생성하지 않는다. 일반 wake와 이 제안 실증은 서로의
PASS를 대신하지 않는다.

실제 같은 책임의 진전·재발견·종료를 관측하면 해당 시험은 PASS다. 중복 효과·거절 재알림·
다른 책임 종료 같은 위반은 FAIL이다. 접근·권한·종료 경로가 부족하면 해당 시험은 BLOCKED,
실행하지 않은 시험은 NOT RUN이다. 확인된 미지원은 해당 surface/version/capability에만
기록한다. NC §3/VF의 기존 기록으로 정확한 소스·명세 판본, 입력·허용 효과·관측·판정·남은
예약/책임을 연결한다. 앱/host 재시작은 controller 재시작과 별도 증거다.

예약이 확인됐지만 제안 원본이 부족하면 기존 위임 작업의 wake만 진행하고 발견 알림은
보류한다. 예약 경로가 부족해도 독립 guard·중복 대사 TC는 진행할 수 있다. 별도 scheduler·
proposal ledger·DB가 필요하다는 발견은 요구 불충족과 필요한 결정을 보고하는 것으로 끝내며
임의로 새 저장소를 채택하거나 v1의 proactive 요구를 낮추지 않는다.

## 3. source와 구현 순서

| source | 변경 책임 |
| --- | --- |
| `hydra_sdlc/native.py` | 재진입의 exact 책임·기존 step 대사, 다음 허용 행동 연결 |
| `hydra_sdlc/control.py` | scope별 schedule coverage와 owner·admission·native 실제 상태 projection |
| `hydra_sdlc/operations.py`, `hydra_sdlc/execution_boundary.py` | 기존 admission/ticket을 모든 wake에 적용; 새 lease/스케줄 저장소 없음 |
| `plugins/hydra/skills/sdlc/SKILL.md` | bounded 재진입 instruction, 질문/완료/취소의 종료 조건 |
| 기존 control/native suite, 예정 `tests/test_native_wake.py` | clock/provider fixture, schedule consumer·종료 경계 |

1. actor·source·대상 task·현재 예약 조회/변경·턴 뒤 실행 경로를 NC에서 특정한다. 외부 호출 가능성과 앱 tool 노출을 분리한다.
2. 실제 원본 의미의 schedule/현재 work/사건 fixture를 만들고 정상 변화와 self-update/no-change를 구분하는 oracle을 먼저 작성한다.
3. 재진입의 첫 동작을 현재 원본·위임·admission·pending 효과 대사로 고정한다. 새 작업을 먼저 만들지 않는다.
4. 현재 미완료 책임·충족한 조건·기존 효과/step을 대사하여 다음 행동을 선택한다. 원본 변화가 없어도 미전송이 확인된 eligible 행동은 진행한다. 늦거나 중복된 tick은 현재 한 상태로 합친다.
5. 지원된 기존 예약을 재사용/갱신한다. 생성 응답 유실은 원래 source 조회 후에만 확정하고 임의 두 번째 예약을 만들지 않는다.
6. 끝조건과 P15 종료/정리 consumer를 연결한다. schedule 접수와 적용, 현재 turn 종료를 각각 읽는다.
7. fixture 회귀/독립 리뷰 뒤 한 허용 task에서 턴 종료→실제 wake→결과→해당 예약 책임 종료를 관측한다.

정상 재진입 prompt는 원본 참조·범위·확인할 조건·허용 행동·종료 기준을 담는다. 원문 대화나
private 값 전체를 복사하지 않는다. 모델이 이 prompt를 읽었다는 사실은 human approval이 아니다.

## 4. 비용·종료·복구의 정확한 의미

native 예약 tick 자체가 모델 turn을 열 수 있다. 원본 변화와 실행 가능한 미완료 책임이 모두
없을 때 **추가 Hydra 작업/배정 0**은 전체 모델 비용 0이 아니다. 기다리는 유효 조건이 남으면 위임된 한계 안에서 기다리고, 유용한
조건이 없거나 한계/목표가 끝나면 예약 책임도 끝낸다. 자기 progress·UI refresh는 의미 있는 사건이 아니다.
완료한 Issue reopen만으로 과거 goal/예약을 자동 활성화하지 않는다. 새 요구는 변경 guard를 따른다.

| 장애/제어 | 보존·회복 |
| --- | --- |
| missed ticks·host offline | 복귀 뒤 최신 원본 한 번 대사. 놓친 횟수만큼 새 turn/Issue/attempt replay 0 |
| duplicate wake·active step | 기존 step 관측; 같은 assignment 재전송 0 |
| CI 성공 관측 뒤 dispatch 직전 crash | 같은 원본의 조건이 여전히 유효하고 이전 미전송이 확인되면 한 다음 step 진행. 전송 여부 unknown이면 먼저 원본 대사 |
| schedule create/update ACK 유실 | exact source read-back; applied/unknown 구분, 조회 불가 상태에서 새 identity로 재시도 0 |
| Pause/Stop·권한 철회 | barrier 이후 신규 Hydra 업무 효과 0; native turn/tick이 이미 시작됐는지는 별도 관측 |
| cancel·완료·질문만 남음 | 현재 책임의 불필요한 wake 종료와 보존/정리를 P15로 전달. 공유 책임은 유지 |
| shutdown·원본 소실·partial inventory | 마지막 정상값으로 zero-active 추정 0. 같은 책임 pending/unknown 보존 |

EX/CP의 기본 continuation은 paused/stopped의 retirement도 보류한다. 따라서 Stop 적용만으로
예약이 삭제되었거나 향후 native tick이 0이라고 표시하지 않는다. 별도의 명시적 정리 요청은
[P15](../15-resource-retirement/spec.md)의 제한된 cleanup 경로로 admission을 그대로 유지하며
해당 owned 예약만 종료할 수 있다. 실제 disable/책임 분리/retirement read-back을 확인해야 한다.
qualified 종료 경로가 없으면 capability는 BLOCKED이며 임의 Resume·무허가 삭제로 해결하지 않는다.
지원된 종료가 확인된 뒤에는 끝난 책임의 추가 wake 0을 검증한다. 이미 시작된 native turn의
실제 interrupt는 P07의 별도 효과이며 schedule 종료 ACK로 대신하지 않는다.

## 5. TC·D/L/O와 검증

제품의 발견·제안 흐름도 이 재진입 계약으로 운영한다. 기존 native 책임 기록에서 관찰 범위,
근거 변화, 이전 제안/거절·재검토 조건, 비용/끝조건을 재발견한다. 동일 근거·동일 결과의 제안은
다시 알리거나 Issue로 생성하지 않는다. 원본 복원 불가는 duplicate 판정 unknown이며 전송을
보류한다. 새 근거로 제안할 때도 P10의 채택/권한 전에 외부 업무 효과를 만들지 않는다.
새 notification ledger나 proposal DB를 만들지 않는다. 기록을 못 찾으면 자동으로 재제안하지 않는다.

발견 제안을 켜기 전 NC에서 원래 native 책임 기록의 제안 참조·근거·전달 결과·사람의 거절/
재검토 조건을 보존/조회하는 실제 source와 caller를 qualification한다. 최초 미전송이 확인된
상태, 이전 전송이 확인된 상태, 전송/원본 조회 불명을 구분한다. 미전송이 확인된 첫 제안은
정상 전달하고 원본 결과를 read-back한다. 단순 검색 0건은 in-flight 전송의 부재가 아니다.
ACK 유실은 원본 대사 전 재전송하지 않으며 원본이 복구되면 실제 결과에 따라 진행한다.
이 증거가 없는 경우 발견 알림만 미지원이고 기존 위임 작업의 재진입은 독립적으로 진행한다.
일반 wake 성공만으로 제안 중복 억제까지 수용하지 않는다.

2026-10-19 공식 예약 문서상 GitHub 이벤트 trigger는 web/mobile에 한정된다. Desktop/CLI/IDE의
자동 이벤트 구독을 가정하지 않는다. 계정·surface에서 지원되고 위임된 경로 하나를 선택하며,
timer와 event를 둘 다 구현해야 v1이 되는 것은 아니다. coalesced event는 개수만큼 replay하지 않는다.

| 추가 사례 | 독립 oracle |
| --- | --- |
| P08-S01: 같은 근거 반복·자기 progress·거절된 제안 | 새 제안/질문/Issue 0; 기록 불가이면 unknown |
| P08-S02: 재검토 조건 충족·새 유의미 근거 | 한 제안 또는 기존 위임 내 한 진전, 과거 거절을 새 권한으로 해석하지 않음 |
| P08-S03: 미지원 event surface·coalesced event·offline 복귀 | 가짜 구독 0, 현재 상태 한 번 대사, 유효 작업 진행·중복 생성 0 |
| P08-S04: 최초 미전송 확인→제안 전달/read-back→restart | 첫 제안 1회, 같은 근거 재알림 0, 다른 유효 근거는 정상 판단 |
| P08-S05: 전송 ACK 유실·원본 조회 실패→원본 복구 | unknown 동안 재전송 0, 복구 뒤 원래 결과 대사·정상 진전, 단순 0건으로 재전송 0 |

L18 및 O06은 제안의 유용성과 불필요한 재질문, 실제 재진입의 진전·비용을 함께 확인한다.

| 연결 ID | 정상/장애 자극 | 독립 PASS oracle |
| --- | --- | --- |
| EX-D03/23, VF-D13/20/21 | 유효 CI 변화·self progress·변화도 eligible 책임도 없음·중복 wake | 유효 책임은 한 다음 결과로 진행; 할 일 없는 자기 변화/중복은 신규 배정 0 |
| EX-D03/23, VF-D06 | CI 성공 관측 뒤 crash, 재시작에 source unchanged·미전송 확정/전송 unknown | 확정된 미전송은 한 correct step으로 진행; unknown은 원본 대사 전 추가 dispatch 0 |
| EX-D01/23 | 높은 우선순위 blocked, 다른 work eligible | unresolved writer 없을 때 독립 유효 작업 진행; 무조건 wait 구현 실패 |
| NC-D04/05/09, EX-D03 | partial schedule 목록·ACK 유실·controller restart·missed ticks | 같은 예약/책임 재발견, 현재 한 번 대사, 새 schedule/attempt 0 |
| EX-D13/14/23 | Pause/Stop·권한 철회와 이미 전송된 wake 경합 | barrier 뒤 신규 Hydra dispatch 0; 이전 효과 read-back·native ended 별도 |
| EX-D22/23, VF-D11/13 | goal 완료·유용 조건 없음·취소·수동 Stop 후 허용된 정리 | 해당 예약 종료 read-back 뒤 추가 wake 0; 공유 책임/dirty 결과 보존 |
| EX-D23, VF L19 | verified complete Issue reopen | 기존 결과 보존, 새 요구 없으면 재구현/예약 활성화 0 |
| NC-D10 | private schedule/task/원문 canary | public 결과·log에 0, 정상 재진입 의미와 coverage 유지 |

| 상태 | 명령·관측 |
| --- | --- |
| 기존 회귀 | `python3 -m unittest discover -s tests -p 'test_native*.py' -v` |
| 기존 회귀 | `python3 -m unittest discover -s tests -p 'test_control.py' -v` |
| 예정; 생성·수집 확인 후 | `python3 -m unittest discover -s tests -p 'test_native_wake.py' -v` |
| O 예정 | EX-O06/VF O01·O06: 턴 뒤 actual wake→허용 결과→예약 책임 종료, P15 원본 read-back |

공통 규약의 runner를 사용하며 이번 설계에서는 실행하지 않았다. D는 필수다. L은 VF L09/18/19로
유효한 다음 행동·질문만 남은 상태·starvation·완료 후 재활성화를 평가한다. 고정 답 replay는 D이며 L이 아니다.
O는 실제 턴 종료 후 실행과 결과를 요구한다. read-only heartbeat 성공·mock tick만으로 대신하지 않는다.
실제 미전송이 확인되는 경계에서 controller를 재시작하고, 같은 source의 남은 책임을 한 번 진행하는 양성 복구도 관측한다. 전송 여부 unknown인 경계를 같은 결과로 간주하지 않는다.

## 6. 리뷰·호환·끝조건

reviewer는 예약 권한/소유·bounded stop 조건·tick 비용·중복 방지·종료 후 책임 보존을 확인한다.
기존 five-tool continuation과 progress v1 의미를 유지한다. tool exposure·위임·지원 경로가 부족하면
source-only 결과는 전달할 수 있지만 wake/종료 capability와 v1은 미완료다. P15와 함께 실제 정상
진행 및 필요 없는 wake 종료가 입증되어야 한다. 실패 시 같은 work/native source의 pending을
복원하며 새 scheduler·고정 coordinator·무조건 반복 요청으로 구멍을 메우지 않는다.
