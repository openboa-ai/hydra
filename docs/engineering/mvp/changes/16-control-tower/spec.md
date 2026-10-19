# P16 — 근거와 조작이 연결되는 control tower

상태: 설계 후보 · revision 4 · 2026-10-19. P16은 계획 ID이며 실제 PR 번호가 아니다.
수용 판본·구현 head·화면·D/L/O 결과는 [공통 변경 절차](../README.md)에 연결한다. 현재 실행은 NOT RUN이다.
검토 기준은 CP revision 7와 제품 Revision 7다. 구현 시작 때 수용한 immutable 판본을 고정한다.

## 1. 목적·요구·범위

사용자가 Hydra에서 맡긴 목표·작업·현재 실행·질문·전달·정리와 다음 행동을 이해하고,
현재 권한과 실제 capability가 허용하는 조작을 할 수 있게 한다. 외부 정본을 두벌로 관리하지 않는다.
[R01/R08/R10/R12/R13/R14/R15/R16](../../spec.md#3-요구사항과-판정)의 최종 제품 경험을 연결한다.

| 항목 | 이 변경의 경계 |
| --- | --- |
| 화면 정본 | [CP §4–9](../../contracts/control-plane.md), [제품 F01–F12](../../../../product/mvp-design.md#42-전체-기능-조작표) |
| 포함 | overview/project/work detail·원본/해석/근거·source 상태·정확한 명령 feedback·실제 화면 |
| 통합 범위 | 구현된 source/command의 실제 화면 연결·원본 변화·부분 장애·재시작. 두 프로젝트의 전체 운영은 Goal의 별도 수용 milestone |
| 제외 | 새 tracker/질문함/대화 DB, 가상의 native 제어, provider 우회, UI에서 업무 정책 재정의 |
| 현재 차이 | 현재 app은 v2 host/project 운영 상태와 단순 work 목록이며 전체 v3 제어 화면/실제 종단 증거가 없음 |

필수 원격 사용자 창구는 Codex이며 업무 조회·제어는 qualified Hydra MCP 경로를 사용한다.
P17 연결·해제는 PC가 정의한 허용된 native caller→fixed CLI→같은 core 경로를 별도로 검증한다.
이 앱은 projection·최소 제어를
제공하고 별도 채팅·질문함·Plan/Goal 편집기를 만들지 않는다. 앱 버튼과 MCP가 같은 action의
공통 core를 사용함을 검증하되, 로컬 버튼 성공으로 O01–06의 원격 조작 수용을 대신하지 않는다.
worker busy·MCP 장애·Codex 연결 단절·host 단절의 관측과 unknown을 구분한다.

## 2. 선행과 변경 소유

[P12](../12-projection-contract/spec.md)의 실제 producer/consumer 계약이 화면 연결의 선행이다.
P02/P05/P06 및 P07–P15/P17/P18의 각 지원 기능은 해당 조작을 켤 때 필요하다. 모든 기능의 O 완료를
UI 개발의 전역 gate로 두지 않는다. 준비된 projection/command부터 통합하고 나머지는 정확히 표시한다.
전체 v1 종단 수용은 필요한 native lifecycle/wake·작업/검증/전달·정리 증거를 빠뜨릴 수 없다.
P07/P08/P15의 기능 구현을 이 PR로 옮기지 않으며 전체 O01–O06 때문에 이 UI PR의 독립 전달을 막지 않는다.

이 명세는 공통 화면 기반과 후속 기능 화면 PR에서 재사용한다. 첫 화면 PR이 P17/P18을 기다리지
않아도 되지만 다음 인계 범위를 계획에서 누락하지 않는다. source-only 화면/disabled 조작과 실제
설치본의 qualified 조작을 구별하며, 한 버튼의 성공으로 다른 command의 지원을 선언하지 않는다.

| 기능 제공자 | P16의 후속 화면·consumer 책임 | 활성화와 관측 |
| --- | --- | --- |
| P02/P05/P06/P13/P14/P15 | P12 기반 위에서 CP가 앱에 허용한 profile의 `protocol.rs`/`process.rs`/`model.ts` 명령별 소비와 실제 Python→Rust→TS TC를 소유. 기능 provider는 core·MCP/native 결과를 제공 | 해당 producer 판본과 공통 wire를 함께 고정. P06/P13의 native-only handoff는 거절하며 private assignment를 앱에 옮기지 않음. 허용된 public 결과와 Fact만 표시 |
| P07 세션 제어 | P07이 검증한 명령별 consumer와 실제 실행 관측을 화면 연결 | qualified owner/control 범위만 활성화; 접수와 실제 종료 구분 |
| P10 작업 등록 | P10이 제공하는 work_create typed consumer와 접수/원본 생성/현재 작업을 화면 연결 | qualified draft source와 해당 command의 정상 read-back 이후. 등록을 실행 위임으로 표시하지 않음 |
| P17 연결·해제 | PC 별도 strict connection consumer·preview·config/stopped/pending/finalized 표시. producer/fixture는 P17 소유 | P17 core와 실제 source action의 target/expected/권한 검증 이후. 0-project를 host 0-active로 표시하지 않음 |
| P18 위임 변경 | P18이 제공하는 typed consumer와 원래 지시/적용 gate/interrupt/실제 ended/cleanup을 분리 표시 | 원래 human source·명령 경로가 qualified된 범위만. P07/P15 미지원은 남은 책임으로 표시 |

P17/P18의 필수 원격 Codex 경로가 이 보조 앱 화면 PR에 종속되지 않게 한다. UI 공개 시에는 해당
consumer의 D와 설치 관측·running screen을 따로 연결한다. 화면 문구만으로 새로운 권한을 부여하지 않는다.
위 후속 단계는 한 화면 PR에 묶을 필요가 없다. producer가 준비된 명령부터 이 명세를 재사용해
연결하고, malformed/stale/unknown 결과와 정상 read-back을 같은 실제 소비 경로에서 검증한다.
소비자 미구현은 앱 기능만 비활성으로 두며 이미 검증된 MCP 경로의 전달을 막지 않는다.

| 현재 경로 | 구체 변경 |
| --- | --- |
| `apps/mac/src/main.ts`, `apps/mac/src/model.ts`, `apps/mac/src/style.css` | v3 views·source별 상태·명령 feedback·안전한 원문 표시 |
| `apps/mac/src-tauri/src/main.rs`, `apps/mac/src-tauri/src/process.rs`, `apps/mac/src-tauri/src/protocol.rs` | validated command·read-back·binding 유지·허용된 source 이동 |
| `apps/mac/tests/model.test.ts`, `apps/mac/tests/projection.test.ts` — 후자는 예정 | UI 상태/명령/late response·대상 전환·오류 보존 |
| Rust 기존 module tests | renderer 권한·typed 입력·fixed argv·bounded process·원본 열기 |
| 기존 Mac scripts·`.github/workflows/ci.yml` | 실제 영향을 받는 frontend/Rust build·theme 검사 유지 |
| 기존 수용 기록 | installed identity·지원 경로의 실제 화면/source refs, 후속 Goal O06 연결. 새 운영 대장 없음 |

## 3. 화면·명령·실행의 연결

1. overview는 프로젝트별 맡긴 목표와 현재 attention/다음 행동을, project는 작업 관계와 admission을 보여준다.
2. work detail은 원본 요청/해석/readiness, 설계→TC→PR·CI→실제 실행→결정→정리를 source ref로 잇는다.
3. 받은 답·채택·context만 기록·적용·assignment·실제 running을 CP의 별도 상태로 표시한다.
   Resume 성공을 실제 재개로 표시하지 않고 host 제한과 project override를 함께 보여준다.
4. command는 표시한 target/expected를 그대로 보낸다. 버튼 비활성화와 별개로 core가 guard를 재검사한다.
5. request receipt와 현재 source 상태를 분리한다. ACK 유실/다른 poll 성공/late reply로 unknown을 지우지 않는다.
6. native/provider 동작은 qualified exact operation만 켠다. unsupported는 원본 이동/필요 조건을 설명한다.

화면 내용은 inert text/안전하게 처리한 Markdown이다. source preview는 허용 connector 안에서
해결하고 임의 URL fetch·remote resource 자동 로드·shell 실행을 만들지 않는다.
원문·public/private 범위를 유지하며 raw native transcript나 자격 정보를 새 UI cache에 보관하지 않는다.
source partial/unknown은 “0 active”가 아니며 result/cleanup 완료와 안전한 Quit의 기준도 다르다.

## 4. 구현 순서와 의미 있는 RED

1. CP의 각 상태와 정상 사용자 경로를 실제 model 입력으로 고정하고 UI 기대 문구·가능 조작을 독립 작성한다.
2. 현행 화면의 admission→execution 혼동·누락된 source 표시 또는 stale 명령 결함을 행동 assertion으로 확인한다.
   screenshot 차이만으로 의미 충족을 판정하거나 UI가 없는 오류를 RED로 세지 않는다.
3. P12 v3 read를 연결한 뒤 overview→project→work detail의 source 이동과 해석/근거를 구현한다.
4. 지원된 typed command만 연결하고 stale/loss/target 전환·binding 변경을 실제 bridge 경계에서 검증한다.
5. source/fixture 화면을 확인한 후 packaged app을 고정 installed runtime/config에 연결한다.
6. 지원된 read와 적어도 하나의 유효한 scoped command를 설치 앱에서 원본/read-back과 대조한다.
   최종 시각적 PR 공개 전에 running-screen 증거를 공유하고 전체 두 프로젝트 O06은 Goal milestone으로 연결한다.

| 정본 TC | 사건 | 독립 oracle / 금지 효과 |
| --- | --- | --- |
| CP-D03/14, VF-D10 | alpha 사람 대기, beta 정상 실행 가능 | alpha 대기·beta 정상 정보/진전 유지. unknown writer일 때만 host 제약 반영 |
| CP-D01/02/04/07 | partial·sleep/resume·늦은 응답·binding 변경 | source/시간/coverage/reason 표시, 정상 source 보존. 누락→0 active·옛 연결 채택 0 |
| CP-D09/12/18 | stale 화면→명령, lost ACK, R+1 receipt 뒤 R+2 Pause | stale 거절·refresh, 현재 상태와 receipt 병기. expected 교체·자동 mutation retry 0 |
| CP-D15, EX-D15 | 좁은 checkpoint/decision command와 legacy capability | 실제 effect ceiling과 표시 일치. unsupported 버튼 dispatch·legacy narrow fallback 0 |
| CP-D08/14/17, EX-D31 | 지원된 verify/publish/deliver와 paused/stopped cleanup-only | exact 후보/PR/자원·단계별 receipt 표시. candidate 변경 자동 채택·전체 Resume·검증을 전달완료로 표시 0 |
| CP-D16, VF-D12/22 | 악성 원문/링크·private canary·preview | 안전한 표시·허용 원본 이동, 임의 네트워크/파일/shell·공개 누출 0 |
| CP-D06/11/18, VF-D11 | closed work cleanup pending·재시작·dirty/foreign/unknown | 원래 책임 재발견, 관련 safe recovery만 진행. 삭제·false complete·unsafe Quit 0 |
| PC-D07/11/12, P18-D04/07/09 | 연결/해제/취소 receipt, 0-project·pending·late reply·restart | config/gate/실제 종료/정리 축을 별도 표시. 미지원 기능 활성화·다른 target receipt 채택·0-active 추정 0 |

## 5. 검증·리뷰·완료 증거

아래는 루트 기준 기존 script/명령이다. P12의 예정 projection 시험이 실제 수집되는지 함께 확인한다.
실행은 허용된 격리 build 환경에서 수행하며 앱 패키징·설치·운영은 별도 단계다.

```sh
npm --prefix apps/mac test
npm --prefix apps/mac run build
npm --prefix apps/mac run verify:theme
cargo test --locked --manifest-path apps/mac/src-tauri/Cargo.toml
cargo build --locked --manifest-path apps/mac/src-tauri/Cargo.toml --features custom-protocol
# 실제 packaged UI 수용 때 별도 실행
npm --prefix apps/mac run tauri -- build --bundles app
```

D는 실제 reducer/bridge·Python wire 경로와 위 금지 효과를 확인한다. L은 UI만 바꾸면 N/A이며
기존 판단을 새로 구현하지 않는다. 원문 해석/행동 제안 prompt를 변경하면 관련 L01/L05/L07/L09를
별도 실행하고 UI 시험으로 대신하지 않는다. 독립 UX 검토는 의미·근거·가능 조작이 사람에게 분명한지 본다.

이 PR의 O는 installed runtime/config identity, 지원된 원본 조회·scoped command와 실제 read-back,
stale 조작·cache 소실·running screen이다. fixture 화면·source test·앱 시작만으로 통과시키지 않는다.
[O06](../../verification.md#o06--두-프로젝트-control-plane실제-화면정리)의 전체 두 프로젝트
운영과 CP-O01–03의 남은 native/정리 범위는 Goal milestone에서 수행한다. 이미 있는 증거는 재사용하고
새 코드가 필요하지 않으면 수용 시험만을 위해 의식적인 PR을 만들지 않는다. 미지원 부분은 NOT RUN/BLOCKED다.

독립 리뷰는 올바른 target/expected, source 상태와 실행 의미, safe rendering/원본 이동,
private 경계·Quit·정리 제한을 확인한다. exact final head의 CI/리뷰와 실제 화면 공개 checkpoint를
완료 증거로 연결한다. 전체 v1 종료는 이 화면 PR의 merge가 아니라 공통 Goal의 모든 필수 증거로 판정한다.

## 6. 호환·회복·인계

v2 설치본은 read-only 호환 view, 지원되지 않는 v3 mutation은 명시적 미지원으로 유지한다.
binding 교체·재시작 시 cache/pending 연결은 무효화하되 효과 미실행을 추정하지 않는다.
실패한 operation의 현재 원본과 남은 책임을 표시하고 사용자에게 같은 답을 다시 요구하거나 새 task를 만들지 않는다.
최종 인계에는 실제 지원/미지원·남은 O·원본 링크·정리 책임을 남긴다. 새 DB·전역 feature 완료 gate는 추가하지 않는다.
