# P18 — 원래 사람 지시에 따른 범위 변경·철회·취소

Revision: 2 · 상태: 설계 후보 · 2026-10-19 · 작업: Issue #3

공통 규칙은 [변경 계약](../README.md), 의미 정본은 [제품 F02/F07 §4.3](../../../../product/mvp-design.md#43-제어의-의미와-적용-시점),
정규형과 authority 계약은 [WR §7.1](../../contracts/work-records.md#71-위임-변경철회취소의-원본과-정규화)다.
제품·설계 후보이며 실제 source 연결과 구현·운영 수용을 선언하지 않는다.

## 1. 목적·책임·범위

| 항목 | 계약 |
| --- | --- |
| 목적 | 맡긴 책임을 바꾸거나 취소했을 때 예전 위임으로 계속 진행하거나 기존 결과를 지우는 오류를 막는다. |
| 책임 | 사람은 목적·권한 변경의 원천, Codex는 문맥 해석, Hydra는 현재 source/actor/scope와 효과 경계 검증. |
| 동작 | 원래 지시 재조회 → exact 책임/변경 정규화 → 현재 권한 검증 → 새 효과 gate → old effect 대사 → 필요한 중단/보존/정리. |
| 실패·복구 | 같은 source의 수정·응답 유실·부분 조회를 구분하고 old binding·pending·실제 결과를 보존한다. |
| 완료 | 명확한 변경이 정확한 책임에 적용되고 재시작 후도 유지되며 실제 종료·정리와 구별된다. |
| 범위 | 기존 native 원본·WR·P07·P15 연결. 새 DB/위임 ledger/공개 transcript/사람 계정 registry 없음. |

## 2. 요구와 입력·출력

- **P18-R01**: 현재 권한 있는 실제 사람의 원래 지시·판본·대상을 qualified source로 확인한다. 모델 주장·연결 자격은 권한이 아니다.
- **P18-R02**: 기존 위임의 정상 구현·명확한 기준 재확인은 그대로 진행한다. 양식 강제나 일상 재승인을 만들지 않는다.
- **P18-R03**: amend의 의미 변경은 old binding/attempt를 보존하고 새 reviewed binding으로 연결한다. pending 효과와 충돌하는 새 scope를 먼저 실행하지 않는다.
- **P18-R04**: withdraw는 명시 actions만 제거한다. cancel은 exact 책임의 향후 진행 철회와 owned 실행 중단 요청이다. Stop/close/Resume와 서로 대체하지 않는다.
- **P18-R05**: 취소 뒤 실제 ended·보존·P15 잔여 책임을 대사한다. 취소를 완료·merge로 만들거나 delivered 결과를 삭제하지 않는다.
- **P18-R06**: source 변경/삭제·권한 상실·partial history는 신규 효과 보류다. 과거 권한의 자동 부활·timestamp 최신 선택·모델 요약 복원 금지.
- **P18-R07**: 원본 기반 재시작·유실 복구와 모든 entry/consumer를 검증한 capability만 활성화한다.

입력은 WR의 `DelegationChangeRef`/`DelegationChangeV1`/`change_digest`, 실제 human source와 현재
protected policy, exact work/goal·old binding/attempt·pending/owner다. 정규형은 WR만 정의한다.
출력은 source에 근거한 유효 범위와 gate 적용 여부, 필요한 P07 interrupt 및 P15 잔여 책임이다.
기존 progress v1에 canceled 상태나 private source 필드를 추가하지 않는다. UI 결과는 사실별로 분리한다.

## 3. 선행·source·활성화 경계

NC의 source qualification과 P03의 v2 guard를 사용한다. legacy intake에서도 정확한 기존 책임·
위임이 확인되면 철회/취소를 적용할 수 있다. P09는 새 binding이 필요한 amend에만 선행하며,
P07/P15 미완료를 이유로 이미 유효한 철회 gate 자체를 적용하지 않는 구현은 허용하지 않는다.
실행 중단/실제 정리는 각각 해당 능력이 qualified되어야 한다. 미지원이면 gate와 남은 실행을 함께 표시한다.

이 명세는 source/authority 연결, 공통 gate·명령, 보조 앱 연결의 후속 PR에서 유지·개정한다.
필수 경로는 원격 Codex의 원래 사람 지시 → qualified source/ref → MCP → 동일 core resolver다.
각 단계의 구현 범위와 수용 판본을 고정하고, source의 실제 귀속·재조회·caller 연결을 먼저 실증한다.
core 정상 TC와 source-only 병합은 실제 위임 변경 기능 완료가 아니다. 원격 source·MCP·core 왕복이
qualified되면 그 경로를 사용할 수 있으며 앱 통합 전체를 선행으로 요구하지 않는다.

| source / 수정할 접점 | 구체 책임 |
| --- | --- |
| 실제 Codex human item와 연결된 intent | NC §2.1–2.3: 실제 actor, original request, exact target/interpretation, revision·수정 탐지, 후속 지시 coverage와 재시작 재조회 |
| `hydra_sdlc/work_records.py` | P09 계획 모듈: WR closed schema·정규 digest·reference 검사; 의미나 human authority를 parser가 발명하지 않음 |
| `hydra_sdlc/intake.py` | P10 계획 모듈: 원문 해석과 deterministic authority/adoption 구분, 같은 source의 변경 normalization/resolver |
| `hydra_sdlc/native.py`, `hydra_sdlc/mcp.py` | native/UI ingress를 같은 resolver에 연결하고 P07 owned interrupt로 넘김. 모델 전달 boolean을 인증값으로 쓰지 않음 |
| `hydra_sdlc/runner.py`, `hydra_sdlc/control.py` | 효과 직전 current authority 재검사, canceled work discovery·gate/실제 실행/잔여 의무 projection |
| `apps/mac/src-tauri/src/process.rs`, `protocol.rs`, app model·consumer tests | P12 공통 기반 위 delegation_change 전용 typed consumer 확장과 실제 wire TC. 화면의 문구·배치는 P16에 인계 |
| P15의 기존 cleanup 경로 | 유효 exact 취소의 공통 resolver 소비; 원 phase와 결과 보존, 실제 ended 뒤 보존·정리·settled 판정 |
| 계획 `tests/test_delegation_changes.py`와 기존 native/MCP/control/restart suite | producer→authority→효과 spy→strict consumer까지 정상·fault 검증 |

CP의 `delegation_change`는 P18의 명령 구현 단계가 닫을 **계획 entry**다. WR ref/digest로 같은 원본을 읽고 target을
대조한다. 실제 source/actor/version 매핑을 먼저 확인한 뒤 exact typed target/expected/result/receipt와
오류·compatibility를 CP 정본에 정의한다. source revision을 제공하지 않는 API에 필드를 만들지 않는다.
원래 human 지시 및 accepted normalization 연결의 durable 재조회가 안 되면 capability 미지원이다.
이 계약과 실제 source·MCP→core 검증 전에는 원격 tool 경로를 활성화하지 않는다. 앱 버튼은 추가로
Python→Rust→TS consumer와 P16 화면 검증을 요구하며, source qualification을 앱에서 우회하지 않는다.
receipt는 접수/gate 반영/interrupt 요청/실제 ended/cleanup을 한 success로 합치지 않는다.

## 4. 구현 순서와 실패 복구

1. 실제 지원 source 한 경로에서 읽기 범위·주체·판본·대상 연결을 확정한다. 미지원 native source를 local DB로 보충하지 않는다.
2. 독립 expected fixture로 정상 amend/withdraw/cancel과 Stop/기준 재확인을 먼저 고정한다. 사용자 자유 형식은 유지한다.
3. WR parser와 source resolver를 분리한다. 같은 source/ref/digest를 다시 읽고 현재 변경 권한을 검사한다.
4. 모든 새 effect entry에 같은 current authority gate를 연결한다. old pending은 원래 scope로 대사하며 source 변경으로 삭제하지 않는다.
5. amend는 필요한 새 reviewed binding·attempt에 연결한다. 충분한 accepted refs와 기존 TC는 재사용한다.
6. cancel은 exact owner만 P07로 interrupt한다. ACK로 ticket을 해제하지 않고 실제 ended/필요 descendant coverage 뒤 P05 보존·P15에 연결한다.
7. goal cancel은 fixed delegation으로 책임을 찾고 현재 parent 이동/Issue close와 분리한다. shared task의 다른 책임은 보존한다.
8. 각 효과 전·후·read-back 전 crash/timeout/Pause를 주입한다. complete 0은 이전 POST/interrupt의 미적용 증거가 아니다.
9. CP profile과 strict MCP consumer를 검증하고 qualified 원격 범위만 노출한다. 앱 consumer는 같은
   producer로 별도 검증하고 P16에 지원 action·source 제한·단계별 receipt를 인계한다. unsupported 상태는 정확히 표시한다.

유실 후 같은 original source를 찾지 못하면 해당 신규 효과·settled 판정을 보류한다. 새 지시/UUID로
old 요청을 덮거나 무작정 interrupt를 재전송하지 않는다. 늦게 확인된 old 결과는 old 책임에 연결한다.
취소 뒤 Resume만으로 개발을 재개하지 않는다. 유효한 새 위임이 있을 때 old 효과를 대사하고 기존
기준을 재사용할 수 있는 새 attempt로 연결한다. 종료하지 않은 실행과 cleanup pending을 숨기지 않는다.

## 5. 결정적 TC와 oracle

WR-D70–81이 canonical 요구 사례다. Oracle은 독립 human/source fixture·현재 정책 snapshot,
old/new binding과 provider의 독립 effect ledger·실제 progress read-back이다. 구현 결과를 정답으로 계산하지 않는다.

| ID / 요구 | 정상·fault 입력 | 기대 결과와 금지 효과 |
| --- | --- | --- |
| P18-D01 / R01–03 | 기존 범위 재확인과 의미 변경 amend, accepted refs 충분/부족 | 재확인은 즉시 기존 흐름; amend만 새 binding 또는 정확한 대기. 불필요 양식/승인 0 |
| P18-D02 / R03·06 | old POST pending→amend→complete 0→late applied | 원래 intent 대사, 충돌 새 scope 0, old 증거로 새 acceptance 통과 0 |
| P18-D03 / R04 | execute_work만 철회, prepare 유효 | 준비 가능·새 실행/전달 0, 현재 turn을 ended로 표시하지 않음 |
| P18-D04 / R04–05 | exact running cancel, 공유 task/foreign turn, interrupt ACK/ended | 자기 turn만 중단, ended 전 ticket 회수/정리 0, 종료 뒤 정상 보존·P15 연결 |
| P18-D05 / R04–06 | goal cancel·reparent/close·이미 전달·남은 질문/자원 | 원래 고정 책임 발견, 다른 goal 보존, delivery 유지·가짜 completed/merge 0 |
| P18-D06 / R01·06 | 위조 human·bot 요약·wrong target·source edit/delete·partial·actor 권한 상실 | authority/source 이유로 해당 effect 0, fallback 권한/최신순 선택 0 |
| P18-D07 / R06–07 | 적용 응답 유실·restart/cache 삭제·정상 원본/미지원 | 같은 scope/pending 복구 또는 unavailable, 중복 effect/새 DB/과거 권한 부활 0 |
| P18-D08 / R04·07 | Stop/close/Resume/일정 삭제와 cancel 뒤 명시적 새 위임 | 전자는 권한 변경 0, 후자만 대사 후 새 attempt; 기존 결과 보존 |
| P18-D09 / R01·07 | CP/MCP/bridge에 invalid union/digest/stale revision·private canary | strict 거절·공개 canary 0; qualified 정상 왕복은 gate 및 실제 관측을 구별해 표시 |

## 6. D·L·O 검증과 실제 명령

계획 파일은 아직 없으며 아래 명령은 구현 후 등록된 자원 환경에서 실행한다. native/mcp/control/restart는 기존 suite다.

~~~sh
python3 -m unittest discover -s tests -p 'test_delegation_changes.py' -v
python3 -m unittest discover -s tests -p 'test_native.py' -v
python3 -m unittest discover -s tests -p 'test_mcp.py' -v
python3 -m unittest discover -s tests -p 'test_control.py' -v
python3 -m unittest discover -s tests -p 'test_restart_ownership.py' -v
~~~

D는 위 TC와 P07/P15·실제 CP strict consumer 회귀를 포함한다. L은 WR-L02로 대상·취소/Stop 의미,
기존 위임 재사용·불필요 질문·injection 분리를 독립 평가한다. JSON parser 성공은 L 증거가 아니다.
O는 WR-O03에서 원격 Codex→qualified source→MCP→core의 허용된 같은 human 원본의 변경·재조회·restart, running cancel의 실제 interrupt/ended,
기존 결과 보존·P15 정리까지 관측한다. UI를 주장하면 같은 원본 연결과 화면 결과도 확인한다.
L/O를 mock으로 N/A 처리하지 않는다. source 미지원은 BLOCKED, 이번 미실행은 NOT RUN이다.

## 7. 독립 검토·완료·호환

독립 spec-fidelity review는 F02/F07→P18-R→TC→모든 effect consumer를 대조하고 별도 품질/보안 검토는
actor 위조·scope 확대·늦은 효과·shared execution·private 공개를 검사한다. final-head D/L/O와 필요한 CI/review가 완료 근거다.
source-ready와 실제 source qualification/운영 수용은 구별하며 항상 hold하는 구현도 정상 TC에서 실패한다.
원격 기능과 보조 앱의 근거를 별도로 기록하고, 유효한 철회 gate·owned interrupt·실제 ended·정리의
완료 범위를 각각 남긴다. gate 적용만으로 취소의 모든 결과나 v1 전체가 완료된 것은 아니다.
protected v2에서만 새 entry를 활성화한다. 기존 v1 위임/4-field intake/progress 의미와 기존 Pause/Stop은 유지한다.
롤백은 source·binding·pending을 보존하고, 유효한 철회/취소를 읽지 못하는 구버전 writer로 자동 복귀하지 않는다.
새 DB·receipt를 원본으로 삼는 fallback 없이 현재 원본을 읽는 지원 버전에서 대사한 뒤 이어간다.
