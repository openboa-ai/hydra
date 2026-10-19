# P12 — 원본별 v3 projection과 실제 consumer 계약

상태: 설계 후보 · revision 3 · 2026-10-19. P12는 계획 ID이며 실제 PR 번호가 아니다.
수용 판본·구현 head·검증 결과는 [공통 변경 절차](../README.md)에 연결한다. 현재 D/L/O는 NOT RUN이다.
검토 기준은 CP revision 7·NC revision 8이다. 구현 시작 때 수용한 immutable 판본을 고정한다.

## 1. 목적·요구·범위

Hydra가 외부 원본의 현재 사실과 미확인 범위를 한 화면 모델로 전달한다. 일부 source 장애나
늦은 응답이 정상 프로젝트를 지우거나 실행 종료·완료를 만들어내지 못하게 한다.
[R01/R10/R14/R15/R16](../../spec.md#3-요구사항과-판정)의 최소 데이터·projection·근거 확인을 담당한다.

| 항목 | 이 변경의 경계 |
| --- | --- |
| wire 정본 | [CP §3–7/§9](../../contracts/control-plane.md)의 Observation/Fact/SourceValue/ProjectionV3·cache·reducer·호환 |
| 포함 | Python encoder→Rust decoder→TS model, source별 coverage/freshness/order, v2 read-only 호환 |
| 제외 | 업무 mutation·새 source 지원 날조·전체 UI·projection DB·대화 저장·scheduler |
| 현재 차이 | 세 계층이 v2 전체 snapshot 중심이며 v3 source별 Fact·DecisionView·계약 통합 시험은 아직 없음 |
| 읽기 책임 | 원본을 조회하고 표시할 뿐 progress 갱신·LLM 호출·wake·ticket release를 수행하지 않음 |

## 2. 선행과 변경 소유

GitHub·local admission의 정상 읽기는 다른 native PR과 독립적으로 시작한다. P09/P11의
binding/관계가 아직 없으면 현재 지원 원본만 projection하고 새 관계를 추측하지 않는다.
P04/P07/P08/P15의 실제 qualification이 있어야 각 native/예약/자원 Fact를 활성화한다.
P01 native_context 진단은 MCP status에만 남고 CP v2/v3 SourceValue로 유입하지 않는다.

P12는 공통 read/wire/reducer 기반의 정본이다. 후속 명령 PR은 이 명세를 참조해 자기 producer와
필수 native/MCP consumer를 함께 변경한다. 앱 consumer의 구현 소유는 아래 표로 인계하며
P12에 업무 효과를 복제하지 않는다. 공통 타입 변경이 필요하면 CP와
이 명세를 개정하고 명령 PR에 수용 판본을 연결한다. 기존 source와 독립적인 새 capability 때문에
P12 전체를 다시 완료할 필요는 없지만 영향을 받는 실제 wire 회귀는 다시 검증한다.

| 인계 대상 | P12가 제공할 것 | 해당 기능 명세의 책임 |
| --- | --- | --- |
| P02/P05/P06/P13/P14/P15 | strict 공통 명령·receipt 소비, source와 현재 Fact의 분리, 검증 벡터 형식 | exact action/schema와 producer·MCP/native consumer·정상/장애 TC. 보조 앱의 명령별 consumer/왕복 TC는 P16의 명시적 후속 단계 |
| P07/P10/P18 | 같은 공통 명령·receipt·source 기반 | 해당 명세가 명시한 명령별 producer·consumer 확장·TC와 source qualification; P16은 제공된 consumer를 화면 연결 |
| P17 | 안전한 read projection과 공통 identity/coverage 의미 | PC 별도 connection profile의 producer·wire fixture. P16이 별도 strict 앱 consumer 구현 |
| P16 | 실제 Python→Rust→TS 기반과 source별 지원/미지원 범위 | 화면 통합·qualified action 활성화·화면 관측 |

필수 원격 MCP 경로의 기능 검증과 보조 앱 wire/화면 검증은 별도다. 앱의 새 consumer가 없다는
이유로 이미 검증된 MCP 경로를 막지 않으며, MCP 성공으로 앱 소비·표시를 검증했다고 기록하지 않는다.

| 현재 경로 | 구체 변경 |
| --- | --- |
| `hydra_sdlc/control.py`, `hydra_sdlc/progress.py` | read adapter별 작은 observation, 순수 Fact/relation 조립·무효과 조회 |
| `hydra_sdlc/runtime_identity.py` | 기존 startup/config/control binding identity 재사용 |
| `apps/mac/src-tauri/src/protocol.rs`, `apps/mac/src-tauri/src/process.rs` | strict v3 decode·고정 core 호출·출력/시간 상한·메모리 cache |
| `apps/mac/src/model.ts` | source별 순서·Fact 의존 무효화·binding/clock 이벤트 reducer |
| `tests/test_control.py`, `tests/test_runtime_identity.py`, `apps/mac/tests/model.test.ts` | 기존 v2/identity 회귀 |
| `tests/test_control_projection.py`, `tests/test_control_wire_contract.py`, `apps/mac/tests/projection.test.ts` — 예정 | v3 의미와 실제 producer/consumer 연결 |
| `tests/fixtures/control-v3/` — 예정 | 공개 가능한 입력·독립 기대값, private 원문/운영 snapshot 제외 |

## 3. 입력·처리·출력

CP의 닫힌 union·nullable revision·정수/시간·상한을 그대로 구현한다. unavailable을 빈 성공
목록으로 바꾸지 않고 partial coverage를 전체 완료로 올리지 않는다. opaque revision은 같음만 비교한다.
source 관측마다 종속 Fact를 다시 계산하며 같은/null revision이라는 이유로 이전 Fact를 재사용하지 않는다.

1. 원본별 supported reader를 호출하고 source/scope·availability·coverage·observed time을 구분한다.
2. raw source는 adapter 경계에서 허용 필드로 정규화한다. raw extra key 필터와 strict wire 거절을 구분한다.
3. 최소 native metadata와 history page의 coverage를 분리한다. title/preview/body/tool arguments는 내보내지 않는다.
4. qualified source mapping 없는 DecisionView는 unknown이다. task active/userMessage로 질문·권한·실행을 만들지 않는다.
5. bounded memory cache와 source별 seq/binding을 적용한다. 재시작은 빈 cache에서 원본으로 재구성한다.
6. 실제 Python 출력이 Rust와 TS에서 같은 의미로 소비되게 한다. 세 벌의 수동 JSON fixture를 계약 시험으로 세지 않는다.

v2는 read-only 호환 view이며 빠진 축은 unsupported/unknown이다. v2에 v3 필드를 추가하거나
unknown key를 조용히 무시하지 않는다. 이 PR은 enabling 버튼을 켜지 않으며 command receipt와
현재 Fact를 섞지 않는 타입 경계만 P16에 제공한다. 명령 효과와 개별 consumer 확장은 위 인계표의 기능 명세가 소유한다.
CP5의 standard_v1과 native_handoff_v1 reply를 엄격히 구분한다. 실제 기존 NativeAssignment의
private serializer/native consumer는 P06/P13이 소유하고, 이 PR의 bridge decoder는 native-only
reply를 거절하며 renderer/cache에 cwd/prompt를 전달하지 않는다. generic payload passthrough는 없다.
CP5의 실제 progress branch/expected_head/expected_base/published_head, PR base SHA와 후속 typed
receipt도 공통 consumer 계약의 범위다. 개별 명령 PR이 해당 정상·거절 reply를 이 기반에 연결한다.
source가 제공하지 않는 pin은 null/unknown으로 남기고 명령 값으로 만들지 않는다.

## 4. 구현 순서와 의미 있는 RED

wire 검증 벡터는 예정 `tests/fixtures/control-v3/` 한 곳에서 소유하고 CP 요구/판본을 가리킨다.
각 언어별 별도 기대 JSON을 유지하지 않는다. 스키마 생성기를 새로 도입하는 것보다 현재
encoder→실제 consumer 통과/거절 시험을 먼저 사용한다. P12는 CP의 조회 비용 사례에서 호출 수·
bytes·지연·rate limit을 측정하고 304/다른 권한 cache/partial을 전체 fresh로 올리지 않는지
검증한다. 효과 직전 guard를 줄이는 최적화는 이 PR에 포함하지 않는다.

1. CP 상태표에서 정상/null/partial/stale/unsupported의 독립 기대값을 작성한다.
2. 현행 v2 중심 consumer에서 v3 정상 사실이 보존되지 않는 assertion을 확인한다.
   compiler/import 실패나 JSON golden 파일 존재만으로 RED/GREEN을 판정하지 않는다.
3. Python pure encoder와 Rust/TS strict decoder를 하나의 reviewable candidate로 연결한다.
4. 실제 serializer 출력을 consumer에 전달하는 wire 시험과 source별 reducer 사건열을 만든다.
5. bounded cache·clock resume·binding 변경·원본 오류·악성 text를 연결하고 read effect oracle를 확인한다.
6. v2 회귀와 실제 세 계층 검사를 통과한 뒤 P16 화면 통합에 넘긴다.

| 정본 TC | 사건 | 독립 oracle / 금지 효과 |
| --- | --- | --- |
| CP-D01/17, VF-D04 | 실제 Python 정상/null/unknown 필드→Rust→TS | 값/의미 동일 수용·거절. null→0·partial→empty·unsupported→success 변환 0 |
| CP-D02/07/18 | seq2 뒤 seq1, opaque revision 역전, binding/재시작 | 최신 source 유지, 옛 generation 배제, 캐시 역쓰기·과거 Fact 재활용 0 |
| CP-D03/04 | GitHub 정상+native unsupported+history 실패, TTL/clock resume | 정상 source 유지, 해당 source만 stale/unknown. 실제 running/ended 추론 0 |
| CP-D05/06 | record/cache/output 상한, closed work+cleanup pending | 완전 record prefix+partial·재조회, active=0/cleanup complete/unsafe Quit 0 |
| CP-D15/16, VF-D03/12/22 | 질문 같은 문장·raw canary·악성 링크·read 반복 | 권한/질문 생성 0, 공개 누출 0, 원격 write·LLM/wake·ticket release·자동 URL fetch 0 |
| CP-D14/18 | merged+cleanup pending, decision applied+execution 미관측 | 결과/전달/정리/실행 축 독립. read 장애로 기존 명령 unknown feedback 소거 0 |
| CP-D01/08/15/17 | 후속 후보/PR/정리 receipt와 native-only reply, 잘못된 pin·누락된 nullable key | 실제 source pin·단계 의미 보존, unsupported reply strict 거절. native payload renderer 유출·가짜 receipt·표시 pin 자동 교체 0 |

## 5. 검증·리뷰·완료 증거

루트 기준 명령이다. 새 selector는 실제 파일/case가 있어야 하며 수집 0개는 성공이 아니다.
현행 frontend test runner는 새 `*.test.ts`를 포함하므로 별도 시험 framework를 만들지 않는다.

```sh
# 기존 회귀와 새 파일을 포함할 suite
python3 -m unittest discover -s tests -p 'test_control*.py' -v
python3 -m unittest discover -s tests -p 'test_runtime_identity.py' -v
npm --prefix apps/mac test
npm --prefix apps/mac run build
cargo test --locked --manifest-path apps/mac/src-tauri/Cargo.toml
# 예정 wire 사례의 명시 수집
python3 -m unittest discover -s tests -p 'test_control_wire_contract.py' -v
```

D는 실제 serializer/decoder/reducer 연결과 부작용 카운터가 필수다. L은 N/A: 새로운 의미
해석·판단 prompt를 추가하지 않는다. live O는 source qualification/P16이 소유한다. 이 PR의
synthetic fixture와 빌드는 standalone 앱의 native 원본 접근 성공을 증명하지 않는다.

독립 리뷰는 source 의미 손실, Fact 종속성, v2 fallback 범위, source/bridge identity,
bounded 메모리와 private 필드 누출을 확인한다. 완료 증거는 exact head의 RED/GREEN,
실제 Python→Rust→TS 전달 자료·수집 case·CI/리뷰다. 원본 미지원은 출력과 결과 기록에 남긴다.

## 6. 호환·회복·인계

새 DB/migration 없이 기존 admission/progress 정본을 유지한다. 캐시 소실·원본 삭제/권한 철회는
CP availability/coverage 의미로 재조회하고 외부에 상태를 복원 쓰기하지 않는다.
DecisionView source mapping이 미정인 부분은 그 capability만 unsupported로 남기며 generic JSON으로 메우지 않는다.
P16에는 strict v3 타입·fixture·read-only v2 동작·지원 source별 범위를 인계한다.
