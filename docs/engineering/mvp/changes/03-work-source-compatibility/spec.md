# P03 — 보호된 작업 원본 호환 경계

Revision: 1 · 상태: 설계 후보 · 2026-10-19 · 작업: Issue #3

공통 실행/리뷰/증거 규칙은 [변경 계약](../README.md)을 따른다.
이 PR은 project v2를 읽되 legacy 작업 의미를 보존하는 최소 전환 경계다.
전체 WorkBinding·native 관계·Projects 구현은 선행 조건이 아니다.

## 1. 목적·책임·범위

| 항목 | 계약 |
| --- | --- |
| 목적 | 첫 native 질문/중단/재개 흐름이 구버전 실행기와 혼용되지 않게 한다. |
| 책임 | 보호된 프로젝트 정책이 원본 의미를 선택하고 코어가 모든 효과 앞에서 확인한다. |
| 동작 | exact default-branch 계약 읽기 → version/source 분기 → 지원 경로만 호출. |
| 실패·복구 | unknown·지원 부족은 해당 효과 보류; 이전 pending/ownership은 원래 계약으로 대사. |
| 완료 | v1 회귀 유지, v2+legacy의 정상 실행, stale/unsupported 원본에서 금지 효과 0회. |
| 범위 | reader/guard와 TC만 변경. 사용자 프로젝트 정책 migration·새 worker·관계 변환 없음. |

## 2. 요구와 입력·출력

- **P03-R01**: 현행 v1 closed fields, 네 필드 intake, exact intake_digest, progress v1 의미를 보존한다.
- **P03-R02**: v2의 work_source/planning은 [WR §10](../../contracts/work-records.md#10-변경종료버전-호환)을 따른다.
  `legacy_issue`는 기존 parser를 쓰며, 구현되지 않은 `github_native` 실행은 unsupported다.
- **P03-R03**: 새 효과 직전 현재 보호된 정책과 pinned contract/source·installed capability를 대조한다.
  candidate worktree의 `.hydra.toml`, label, 최신 comment가 선택권을 갖지 않는다.
- **P03-R04**: 버전/source 변경은 기존 unknown effect·owner를 자동 인수하거나 승인하지 않는다.
  구버전 writer 종료와 원래 효과 대사 없이 migration/downgrade하지 않는다.

입력은 `GitHub.repository/file/ref`, pinned contract revision, 기존 Issue/progress와 host ownership이다.
출력은 기존 config에 검증한 원본 선택을 포함한 내부 값 또는 명시적 invalid/unsupported/policy_changed다.
새 public progress 필드나 별도 capability DB는 추가하지 않는다.
WR의 schema를 이 PR 문서에서 복제하지 않고 같은 validator를 이후 P09/P11이 사용한다.

## 3. 선행과 수정할 접점

기존 accepted GitHub workflow와 admission/ownership 구현을 사용한다.
설계 수용 후 구현할 PR이며, 실제 프로젝트에서 v2 정책을 채택하는 효과는 별도 보호 review 대상이다.

| 경로 | 구체 책임 |
| --- | --- |
| `hydra_sdlc/project.py:load_project` | v1/v2 closed field 검증 분리; 지원되지 않은 source를 legacy로 fallback하지 않음 |
| `hydra_sdlc/project.py:parse_intake` | v1 및 v2+legacy의 기존 결과/거절 의미 유지 |
| `hydra_sdlc/runner.py:_work_config/_latest` | current 정책/source guard와 pinned completion 예외의 좁은 보존 |
| `hydra_sdlc/native.py` | source 선택에 맞는 기존 begin/continue 진입; 아직 미구현 native work path 거절 |
| `hydra_sdlc/workspace.py`, `execution_boundary.py`, `codex.py` | parent-only preflight callback을 실제 검증 command·SDK thread/turn grant 경계까지 전달 |
| `tests/test_project.py`, `tests/test_policy_completion.py` | 현행 parser/완료 대사 회귀 확장 |
| `tests/test_work_source_compatibility.py` | 새 계획 파일; mixed reader·source drift·금지 효과 spy |

### 3.1 구현 경계 보충 — revision 1 범위 내

보호된 정책의 source와 기존 `execution_mode=native`는 별개다. v2+legacy는 CLI 및
기존 native 실행기를 모두 사용할 수 있고, v2+github_native는 읽기만 지원한다.
호출별 내부 context에 repository와 검증한 정책을 묶으며 public permission이나 새 저장소를 만들지 않는다.
새 효과는 current protected policy preflight → 기존 짧은 admission guard → effect 순서다.
보호된 정책을 읽는 remote I/O를 admission lock 안에 넣거나 실행 전체 동안 lock을 유지하지 않는다.
이는 서로 다른 저장소의 정책과 효과를 하나의 원자적 transaction으로 만드는 보장이 아니다.

native ticket 기록, progress intent, 최종 `native_task` 반환에는 각각 경계가 있다.
사이에 source/Pause가 바뀌면 이미 기록된 ticket·intent를 유지하고 정확한 recovery identity와
waiting을 반환한다. 실행 허가가 반환되지 않았다는 이유로 기존 ticket을 자동 삭제하지 않는다.
CLI는 기존 intent 기록 후 재검사 및 실행 종료 확인을 유지한다. source 변경 후 종료된 결과는
새 실행/검증/발행으로 채택하지 않으며, 기존 exact ended proof에 근거한 checkpoint와 미답변
product decision 보존 경로만 사용할 수 있다.

`Workspace.verify(before_command=...)`와 `codex.execute(before_dispatch=...)`는 신뢰된
parent의 동기 callback을 받으며 기본값은 기존 독립 호출을 보존한다. Runner는 항상 현재
policy 검사를 제공한다. callback은 assignment JSON·worker·환경변수로 전달하지 않는다.
검증은 순수 storage argv 구성 뒤 실제 command spawn와 Linux launch grant 직전에 확인한다.
SDK worker는 각 thread/start·thread/resume·turn/start 요청을 검증한 뒤 local admission lock
밖에서 확인하고, callback 이후 stop/deadline 및 admission을 다시 검사한다. 빈번한 stop poll이나
cleanup에서는 remote policy를 읽지 않는다.

policy 거절은 이후 grant를 계속 막는다. raw provider 오류는 bounded reason으로 바꾸며,
실제 thread identity·grant·worker 종료/cleanup 증거가 갖춰진 때만 known-clean hold로 처리한다.
cleanup unknown은 policy 거절보다 우선한다. 검증 command 1의 변경은 command 2를 보류하기 전에
종료가 확인된 경우 기존 pinned checkpoint에 보존하며, 이를 성공 검증이나 재발행 허가로 보지 않는다.
native ticket/intent 뒤 최종 조회 실패도 exact recovery tuple을 보존하는 waiting이며 grant가 아니다.

최초 dispatch가 parent 정책 검사에서 거절됐고 grant·관측 identity·terminal이 없으며 cleanup이
확인되면 worker의 무응답·비정상 결과와 무관하게 parent가 `stopped_before_dispatch`와 bounded
policy reason을 반환한다. worker 문구를 거절 근거로 채택하지 않는다. 이미 전달됐을 수 있는
grant, 모순된 identity/terminal 또는 cleanup unknown은 이 known-clean 경로로 정규화하지 않는다.
worker 결과에만 남은 identity·terminal·cleanup unknown·transport unknown도 기존 미확정 경로에 보존한다.
검증 preflight 중 deadline이 지나 command를 spawn하지 않았다면 `command_unavailable`로
보류한다. 실행 결과·검증 실패 receipt·correction을 만들지 않으며 실제 spawn 뒤 timeout의
종료 확인과 실패 검증 의미는 유지한다.

기존 pinned post-merge completion은 해당 완료 대사만 허용하며 active native 결과 채택에는
사용할 수 없다. exact stopped ticket 정리는 기존 조건을 유지한다. admission이 설치된 경로는
기존 worktree만 사용하고, admission 미설치 legacy 경로의 기존 workspace 복구 조건도 유지한다.
새 worker·source migration·권한 확대는 이 보충에 포함하지 않는다.

### 3.2 정책 조회 지연과 실제 실행 증거 — revision 1 범위 내

정책 callback은 read-only이며 감독 event loop나 admission lock을 점유하지 않는다.
parent에서 repository와 pinned 정책의 독립 snapshot을 고정한 뒤, admission/ownership
ContextVar를 상속하지 않는 단일 관측에서 확인한다. GitHub client의 read budget과 인증
fingerprint는 다른 관측·monitor와 공유하지 않는다. 기존 전체 정책 validator와 actor 권한
검사를 유지하고, 실행의 남은 absolute monotonic deadline과 최대 15초, pinned actor 수에
필요한 유한 요청 수로 조회를 제한한다. 이 관측은 새로운 권한이나 실행 grant가 아니다.

신뢰된 executor owner마다 동시에 하나의 관측만 허용한다. Stop·취소·deadline은 조회가
끝나기를 기다리지 않고 owned worker의 종료·수집을 진행한다. 관측한 중단은 해당 실행에 고정하며,
바로 Resume되어도 미완료·중단된 조회를 성공으로 사용하지 않는다. 늦게 끝난 조회 결과는 폐기하고
다음 호출은 새로 조회한다. 남은 read-only 관측을 강제 종료했다고 주장하지 않으며, 그 thread가
실제로 끝나지 않았으면 cleanup unknown/hold를 유지하고 추가 관측을 만들지 않는다.
관측 thread는 interpreter 종료를 막지 않는 daemon이며, thread 종료 자체가 이미 held 상태인
Runner의 명시적 recovery 조건을 대신하지 않는다. 기존 unknown effect의 해제를 일반화하지 않는다.

sync 호출도 원래 caller에서 Stop을 계속 확인하고 deadline을 제한한다. 짧은 admission guard를
획득한 뒤 process 등록/Popen, Linux launch 또는 SDK grant/ACK 직전 Stop/deadline을 다시 검사한다.
helper가 존재한다는 사실은 verifier argv 실행 증거가 아니다. exact no-child cancellation receipt,
helper exit 0, output/control EOF와 exact ticket retirement가 확인되면 command_unavailable이며
실행 결과·검증 실패 receipt·correction을 만들지 않는다. 실제 argv 시작 뒤 timeout은 기존
실패 검증 의미를 유지한다. receipt 모순·유실·cleanup/retirement 실패는 unknown이 우선한다.

### 3.3 native retirement와 현재 정책 확인의 통합

진행 기록의 native 필드 제거·정확한 read-back·배정 티켓 해제·consumed 표시는 하나의
고정된 동기 retirement로 묶는다. 세 기존 경로(오래된 verification review, 정상 review,
write checkpoint)의 admission barrier를 유지한다. 현재 보호 정책은 이 고정 연산의 guard
직전에 잠금 밖에서 확인하며, 연산 내부에는 다른 callback·검증·workspace·새 배정을 넣지 않는다.
record 정규화와 review 완료 필드의 순수 계산만 공유한다. 일반 효과의 정책 검사를 생략하는
플래그나 재사용 가능한 grant를 만들지 않는다.

티켓은 변경된 checkpoint head가 아니라 원 배정의 native_head·attempt·step·contract와
현재 coordinator owner에 묶는다. 완료 필드로 이 identity를 교체할 수 없다. Pause가 preflight
중 적용되면 guard가 retirement를 보류하고 원 ticket/진행/edits를 보존한다. admission 뒤
원격 정책이 바뀌더라도 해당 retirement만 끝낼 수 있으며 이후 효과는 정책을 새로 확인한다.
이것은 원격 정책과 local admission의 원자적 transaction 보장이 아니다. record ACK·read-back·
해제 실패에서는 confirmed ticket release 이전에 consumed를 표시하지 않는다.

## 4. 구현 순서

1. 기존 v1 유효/오류 fixture의 결과를 먼저 고정한다. 구버전 reader의 version=2 거절도 fixture로 보존한다.
2. v2+legacy와 unsupported native source의 기대 TC를 추가해 의도한 실패를 확인한다.
3. config validator를 좁게 분리하고 legacy intake 함수의 입력 의미를 유지한다.
4. current policy 확인을 native/CLI의 신규 효과 진입점에 연결한다. read-only projection은 unsupported를 표시할 수 있다.
5. 이전 contract의 pending completion을 처리하는 현행 예외가 새 dispatch/위임으로 확대되지 않는지 검증한다.
6. 신규 기능이 완성될 때 같은 source discriminator로 연결하도록 한다. 별도 feature flag/전환 journal을 만들지 않는다.

## 5. 결정적 TC와 oracle

WR-D01/46/47/67을 재사용하며 다음 순서를 고정한다.
Oracle은 고정 TOML/Issue 값과 fake transport·worker의 호출 기록이다. 대상 parser가 기대값을 생성하지 않는다.

| ID | 사건 | 기대 결과·금지 효과 |
| --- | --- | --- |
| P03-D01 | 같은 유효 v1 fixture를 변경 전/후 reader에 입력 | 동일 spec/priority/dependencies·intake digest, 추가 native 호출 0회 |
| P03-D02 | v2+legacy와 유효 legacy Issue | 기존 intake로 정상 진행; 새 binding/Projects 생성 0회 |
| P03-D03 | v2+native지만 관련 implementation 미설치 | unsupported, legacy dispatch 0회, 원본 표시 가능 |
| P03-D04 | source 누락/unknown/boolean version/legacy+Projects | schema 거절, side effect 0회 |
| P03-D05 | 시작 후 보호된 source/계약 변경 | 다음 효과 hold, pinned pending/edits 보존 |
| P03-D06 | candidate worktree에서 v2/source를 조작 | protected default-branch 원본만 사용, 권한 상승 0회 |
| P03-D07 | old writer/unknown publish가 남은 migration | 자동 소유 해제·중복 publish·downgrade 0회 |
| P03-D08 | 원래 계약의 좁은 post-merge completion | 기존 증거로 대사 가능, 새 구현/새 범위 dispatch 0회 |

## 6. 검증 명령·판단·실제 관측

아래는 구현 시 실행할 명령이며 이 문서 작성에서 실행하지 않았다.
workspace의 등록된 자원 lifecycle wrapper 안에서 실행한다.

~~~sh
python3 -m unittest discover -s tests -p 'test_project.py' -v
python3 -m unittest discover -s tests -p 'test_policy_completion.py' -v
python3 -m unittest discover -s tests -p 'test_work_source_compatibility.py' -v
~~~

앞의 두 파일은 현재 존재하며 마지막은 이 PR에서 추가할 계획 파일이다.
최종 통합 후보는 기존 전체 `python3 -m unittest discover -s tests -v`와 해당 CI를 통과해야 한다.
L 평가: N/A. 제품 의미를 모델이 판단하는 변화가 없으며 schema/호환은 D oracle로 검증한다.
독립 code/security review는 별도로 exact diff의 fallback·보호 우회·완료 예외 확대를 검사한다.
O 관측: 허용된 fixture의 실제 protected config read와 old/new reader 분기만 확인한다.
실제 v2 migration/재개는 후속 첫 흐름 시험에 연결하고 여기서 설치·운영 성공으로 선언하지 않는다.

## 7. 완료·호환·복구

완료는 accepted revision, P03-D 결과, v1 회귀, 독립 review와 최종 head CI 링크다.
v2+legacy가 새 native decision 흐름의 입력으로 쓰일 수 있음을 확인하되 그 흐름 전체 수용과 구별한다.
실제 정책 변경은 기존 효과/owner를 대사한 후 보호 절차로 수행한다.
rollback은 v2 데이터를 v1로 바꾸는 행위가 아니다. 지원 reader와 원래 기록을 보존하고 해당 source 실행을 보류한다.
구버전은 version=2를 계속 거절해야 하며 unknown outcome을 실패로 지워 재시도하지 않는다.
