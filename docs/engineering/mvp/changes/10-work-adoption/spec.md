# P10 — 유용한 요구의 해석·채택·멱등 등록

Revision: 4 · 상태: 설계 후보 · 2026-10-19 · 작업: Issue #3

공통 규칙은 [변경 계약](../README.md), 원문·위임·draft·binding·anchor의 정본은
[WR](../../contracts/work-records.md)다. 이 명세는 그 타입을 호출 흐름에 연결하며 별도 tracker를 만들지 않는다.
같은 명세의 구현 단계를 PR로 전달하고 각 PR은 수용 판본과 충족하는 요구·TC를 고정한다.

## 1. 목적·책임·범위

| 항목 | 계약 |
| --- | --- |
| 목적 | 자유 형식/외부 제안도 유용한 요구로 검토하고 위임 안에서 기존 설계·작업에 연결한다. |
| 책임 | Codex는 의미·분해·중복 후보 판단, Hydra는 source/authority/schema/효과 검증, GitHub는 원본 기록. |
| 동작 | 관측 → 해석 후보 → 기존 결과 대조 → 준비/채택 → 정확한 draft 등록 → binding/attempt anchor read-back. |
| 실패·복구 | 질문·모호성·권한 부족·응답 유실을 구분하고 기존 원문/intent/생성 결과를 보존한다. |
| 완료 | 유효 제안이 실제 scoped work로 이어지고 unsafe/duplicate/무권한 효과가 발생하지 않는다. |
| 범위 | 읽기/해석/adoption/Issue·최소 comment 등록과 허용된 native 관계 준비의 조정. 범용 관계 편집·새 scheduler·모델 서버·새 credential 없음. |

요구사항은 Codex native 질문의 선택지·추가 설명·주관식 답변을 함께 해석하고 공개 가능한
수용 의미만 기존 spec/작업에 연결한다. 질문의 답변은 자동 등록/위임/권한이 아니다. 기존 설계로
알 수 있는 것을 재질문하지 않고 부분 응답은 확정 가능한 범위만 반영한다. EX §7과 VF L02/L07의
질문 품질 변형을 적용한다.

## 2. 요구와 입력·출력

- **P10-R01**: 형식·heading·label·외부 author만으로 제안을 버리지 않고 actionable/needs_info/propose/quarantined를 구분한다.
- **P10-R02**: 원문 공격 지시는 authority가 아니다. 보안 테스트 인용/정당한 CI 수정은 문맥을 평가해 유효 요구를 보존한다.
- **P10-R03**: 실제 기존 위임과 accepted 설계 안의 채택은 재사용한다. 모델 자체 승인/author 변경/ready 추론 금지.
- **P10-R04**: WorkCreateDraftRef/draft_digest/create_key로 exact title/body를 복구한다. 같은 key의 다른 payload는 conflict다.
- **P10-R05**: Issue 생성·binding·attempt anchor는 WR 순서와 read-back을 지킨다. record 미확인 상태에서 배정하지 않는다.
- **P10-R06**: complete 0건은 처리 중 POST의 부재가 아니다. 늦은 양성 결과를 원래 intent에 대사하고 중복 생성하지 않는다.
- **P10-R07**: qualified draft source와 실제 GitHub 생성 read-back의 CP typed expected/result/receipt를 정의한다. 필수 MCP/core 경로와 보조 앱 경로는 각각 해당 consumer 검증 후 활성화하며 한 경로의 성공을 다른 경로의 완료로 표시하지 않는다.
- **P10-R08**: 등록 주체는 수용 계획에 필요한 관계 준비를 WR/GI에 따라 조정한다. Issue 생성과 관계 쓰기 권한은 별도이며, 미확인 writer·관계 결과를 준비 완료로 표시하지 않는다. P11은 read/gate만 수행한다.

입력은 원래 Issue/native preparation ref, 현재 protected policy/admission, 실제 위임과 기존 설계·증거다.
출력은 검토 후보/누락 이유 또는 공개 가능한 exact draft·채택 ref다. 원문 전체·native ID·private source는 GitHub에 복제하지 않는다.
정확한 공개 명령 타입은 CP work_create, 데이터형은 WR을 재사용한다. 공개 tool/API 이름을 여기서 추가하지 않는다.

## 3. 선행과 수정할 접점

필수 MCP/core 등록 경로는 [P02](../02-project-admission/spec.md)의 공통 typed handler·정확한
target/runtime 검증·admission barrier, [P09](../09-work-binding/spec.md)의 validator 및 P03 source
guard의 수용 인터페이스 판본을 선행으로 소비한다. P02의 저장 계층만 구현된 상태는 이 조건을
충족하지 않는다. [P05](../05-checkpoint-only/spec.md)가 제공하는 additive MCP 명령 진입점·
공통 dispatch 판본을 소비하고 P10은 work_create 분기만 같은 handler에 연결한다. P05 전체
checkpoint 운영 완료를 등록의 선행으로 확대하지 않는다.
native 준비 원본은 NC/P04가 source·actor·판본·exact draft 복원을 실증한 해당 능력만 요구한다.
P04 전체 질문 기능이나 P01 진단 성공으로 draft 자격을 대신하지 않는다. 지원이 없으면
해석/읽기/guard 구현은 계속하되 생성 capability는 보류한다.
P11의 관계/입력조건 gate는 등록 이후 실제 작업 배정의 조건이며, Issue 등록 자체의 선행으로
두지 않는다. 등록과 native 실행 활성화를 구분한다.

CP의 work_create 입력만으로 명령 계약이 완성되지 않는다. P10은 실제 qualified draft reader의
source/actor/revision과 생성 후 GitHub repository ID·Issue number·create_key read-back을 연결하고,
CP 정본에 exact expected/result/receipt·unknown/conflict·호환 범위를 닫는다. response echo를 적용
receipt로 쓰거나 native provider의 없는 필드를 발명하지 않는다. 필수 MCP→core의 정상/유실/
불일치 왕복이 확인되면 그 경로의 생성 capability를 활성화할 수 있다. 보조 앱은
[P12](../12-projection-contract/spec.md)의 공통 projection·wire 기반을 소비하며 Python→Rust→TS
strict 왕복 검증까지 앱의 해당 명령을 비활성으로 둔다. P12/P16 전체 화면이나 앱 활성화는
MCP 등록의 선행이 아니다. 원본 계약·생성 handler는 하나이며 별도 앱 등록 로직은 만들지 않는다.

| 구현 단계 / PR 결과 | 선행·변경 책임 | 검증·다음 소비자 |
| --- | --- | --- |
| 해석·필수 MCP 등록 | 위 P02/P03/P09 인터페이스·P05 공통 MCP 배선과 qualified draft source. P10이 CP work_create profile, control/MCP/native handler, 생성·read-back을 연결 | P10-D01–10과 D11의 MCP/core 사례, 적용 L·실제 생성 O. P11/P14는 확인된 등록·binding 능력을 소비하며 미확인 관계 준비를 추론하지 않음 |
| 보조 앱 consumer 연결 | 검증된 core 계약과 P12 공통 wire. P10이 명령별 Rust/TS parser·receipt 소비와 TC를 함께 변경; 화면 구성은 P16 | P10-D11의 실제 Python→Rust→TS 경로. 앱 왕복 미검증은 앱만 비활성; core 성공과 별도 완료 기록 |
| 허용 관계 준비 | qualified 관계 writer·intent 복원과 실제 위임. Issue 등록 결과 재사용 | P10-D12–15와 관계 read-back O. P11 gate는 확인된 원본을 읽어 배정 가능 여부를 판정 |

| 경로 | 구체 책임 |
| --- | --- |
| `hydra_sdlc/intake.py` | 새 계획 모듈: 해석 후보→deterministic adoption/registration 조정; 모델 자체 구현/DB 없음 |
| `hydra_sdlc/github.py` | authenticated binding/draft/anchor와 create_key read-back·bounded comments 조회 |
| `hydra_sdlc/control.py`, `hydra_sdlc/native.py`, `hydra_sdlc/mcp.py` | P02 공통 handler의 work_create profile·배선, 같은 adoption handler와 native preparation source resolver |
| `apps/mac/src-tauri/src/protocol.rs`, `apps/mac/src-tauri/src/process.rs`, `apps/mac/src/model.ts` | P12 공통 wire 위의 명령별 typed 입력·결과·receipt 소비. private native payload는 renderer로 전달하지 않음 |
| `plugins/hydra/skills/sdlc/SKILL.md` | 기존 설계/TC 재사용·원문 해석·명확한 부족 정보·권한 분리 지침 |
| `tests/test_work_intake.py`, `tests/test_work_registration.py` | 새 계획 파일: 유효 진행·거절 효과·각 POST 응답 유실 fault |
| `tests/test_native.py`, `tests/test_mcp.py`, `tests/test_github.py` | 기존 진입점/인증 작성자/legacy 회귀 |
| `tests/test_control_commands.py`, Rust protocol tests, `apps/mac/tests/model.test.ts` | core 명령과 적용 앱 consumer의 정상·unknown·불일치. 실제 Python 결과를 Rust→TS에 전달하며 별도 손작성 fixture 세 개로 왕복을 대신하지 않음 |

coordinator.py는 host lock/ticket 책임을 유지한다. 원문 의미 엔진을 host 소유권 모듈 안에 넣지 않는다.

## 4. 구현 순서

1. 기존 좋은 설계, 자유 형식 버그, 외부 제안, 혼합 injection, 중복 결과의 고정 평가 입력을 준비한다.
2. 모델 후보와 deterministic validator를 분리하고 실제 authority/원본 ref 없이 effect를 호출할 수 없게 한다.
3. 기존 결과 식별/Issue 검색의 coverage를 확인하고 재사용·의미 중복·충돌을 분리한다.
4. WR의 단일 exact draft를 지원 원본에 고정한다. native preparation 재조회 실패를 local cache로 대신하지 않는다.
5. create → binding → 초기 progress → attempt anchor → assignment 이전 read-back 순서를 연결한다.
6. 각 POST 직전/후 timeout·process loss·Pause·late success fault를 넣고 다음 재진입이 같은 intent를 찾게 한다.
7. source 변경/동등성 검토는 원래 pending을 대사한 뒤 새 binding/attempt로 연결한다. 과거 기록은 보존한다.

## 5. 결정적 TC와 oracle

관계 준비는 기존 source에 있는 정확한 추가 대상·관계·허용 효과를 재발견한 native 등록
주체가 수행한다. CP work_create에 관계 쓰기를 암묵 추가하지 않는다. Issue 생성 read-back
후 현재 edge를 읽고 같은 관계는 재사용, 누락된 허용 관계만 qualified 경로로 추가한다.
다른 parent는 hold이며 replace_parent=false다. 원래 intent/응답 유실은 WR대로 대사한다.
writer가 미확인인 경우 Issue 등록 증거는 보존하고 관계 준비 capability만 unavailable로 둔다.

| 추가 TC | 독립 기대 결과 |
| --- | --- |
| P10-D12: Issue 성공→edge 실패→restart | create_key의 기존 Issue 재사용, 누락 관계만 처리, 자식 재생성 0 |
| P10-D13: edge ACK 유실→늦은 성공 | 원래 intent에 결과 연결, 확인 전 중복 전송/다른 payload 0 |
| P10-D14: 같은 edge/다른 parent/edge 불필요 | 각각 write 없이 진행/해당 준비 hold/정상 독립 진행; reparent 0 |
| P10-D15: cross-owner·403·partial·Pause 뒤 late 결과 | 지원 범위/권한/미확인 구분, 이미 발생한 효과 보존, 신규 무권한 효과 0 |

실제 O에는 하나의 허용된 Issue 생성→관계 연결→read-back→P11 gate를 포함한다. 현재 관계
writer와 durable intent 복원 시험은 NOT RUN이다. read adapter 성공으로 이를 통과시키지 않는다.

WR-D02–05/07/11–14/23–24/32/35–45/54/56/61/68/69를 재사용한다.
Oracle은 독립 작성한 scope/authority fixture, exact 저장 payload, 외부 effect spy와 read-back 순서다.

| ID | 사건 | 기대 결과·금지 효과 |
| --- | --- | --- |
| P10-D01 | 유용한 freeform + 기존 위임/accepted spec | 원문 유지 후 scoped adoption, 양식 재작성/중복 spec 0회 |
| P10-D02 | 외부 author·위임 없음/있음 | 각각 propose/검증된 채택; 원 author 위조 0회 |
| P10-D03 | 유효 bug와 secret 유출 지시 혼합 | 유효 요구 후보 보존, secret/command/권한 효과 0회 |
| P10-D04 | 같은 key 다른 target/body/source | creation_payload_conflict, 재POST 0회 |
| P10-D05 | POST 성공·응답 유실 뒤 complete 0→late 1 | intent 보존, 같은 결과 복구, duplicate 0회 |
| P10-D06 | binding 또는 anchor POST 미확인 | 새 task/ticket 0회, 생성 Issue 보존·같은 intent 대사 |
| P10-D07 | process/cache 소실 후 native draft ref 정상/미지원 | exact payload 복구/해당 생성 unavailable; body 재생성 0회 |
| P10-D08 | 2개의 같은 결과/anchor 또는 partial lookup | conflict/unknown, 임의 close·새 create·최신 채택 0회 |
| P10-D09 | Pause 이후 늦은 생성 응답 | 원래 Issue에 대사만, binding/dispatch 등 새 효과는 admission에 따름 |
| P10-D10 | source/comment 수정·과거 동등성 근거 삭제 | 현재 채택 보류, 이전 pending/원문 보존 |
| P10-D11 | qualified draft로 생성/기존 exact 결과 복구·MCP/bridge 왕복, wrong repository/Issue/key·응답 유실 | 실제 read-back만 typed receipt에 연결; strict consumer 거절/unknown, request echo·임의 success·중복 생성 0회 |

## 6. 검증 명령·의미 평가·실제 관측

구현 시 등록된 자원 lifecycle에서 실행한다. 두 work 파일은 계획 파일이며 native/mcp/github는 존재한다.

~~~sh
python3 -m unittest discover -s tests -p 'test_work_intake.py' -v
python3 -m unittest discover -s tests -p 'test_work_registration.py' -v
python3 -m unittest discover -s tests -p 'test_native.py' -v
python3 -m unittest discover -s tests -p 'test_mcp.py' -v
python3 -m unittest discover -s tests -p 'test_github.py' -v
python3 -m unittest discover -s tests -p 'test_control_commands.py' -v
~~~

앱 consumer 단계는 `apps/mac`에서 `npm test`, `npm run build`,
`cargo test --locked --manifest-path src-tauri/Cargo.toml`과 P12의 실제 producer→consumer
왕복을 실행한다. core 단계에는 적용하지 않은 앱 검증을 PASS로 채우지 않는다. 예정 selector의
0개 수집은 성공이 아니며 각 단계의 필수 사례·제외 이유를 해당 실행 기록에 남긴다.

L 평가: WR-L01의 고정 사례로 의미 충실성·불필요한 질문·과분할·중복·기존 설계 재사용을 독립 reviewer가 평가한다.
구조화 JSON 성공·authoritative처럼 쓰인 prose를 L 통과로 세지 않는다. D와 별도 결과를 남긴다.
O 관측: WR-O01에서 허용된 공개 fixture 한 요청의 채택/생성/응답 유실 대사를 확인한다.
source/native preparation 지원 부족은 사실대로 남긴다. 원문 재작성·비공개 내용 공개·무단 task 생성은 허용하지 않는다.
독립 code/security review는 authority 승격·prompt injection·duplicate intent·public/private 경계를 집중 검토한다.

## 7. 완료·호환·복구

각 PR 완료는 accepted revision, 단계에 해당하는 D/L/O 결과와 명시된 지원 범위,
final-head CI·독립 review다. P10 전체 완료에는 세 단계의 필수 증거와 후속 책임 연결이 필요하다.
실제 시험은 아직 NOT RUN이며 소스 병합·MCP 활성화·앱 활성화·관계 준비를 서로 대신하지 않는다.
v1 작업을 자동 채택하지 않고 v2 source 선택 안에서만 새 경로를 사용한다. progress v1 schema는 유지한다.
unknown 요청은 새 key로 바꿔 재시도하지 않는다. 이전 결과가 확인될 때까지 해당 생성만 보류한다.
롤백 시 기존 Issue/draft/binding/anchor를 삭제하지 않으며 원본을 읽어 재개할 지원 버전을 보존한다.
