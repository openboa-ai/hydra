# P13 — 목적 기반 검증과 증거 연결

상태: 설계 후보 · Revision: 4 · 2026-10-19 · 상위 작업: Issue #3

## 목적과 구현 단계

목적은 green 출력과 모델의 완료 문구 대신, 수용한 요구가 정확한 후보에서 검증됐는지 판정하는 것이다.
이 명세는 TC의 탐지력·실제 수집·D/L/O 증거 연결과 좁은 검증 실행을 소유한다.
서로 다른 선행 조건과 완료 결과를 두 PR 단계로 나누되 명세·요구 정의는 복제하지 않는다.
각 PR은 이 명세의 정확한 판본과 해당 요구·TC 범위를 고정한다. 모델 서비스나 증거 DB를 만들지 않는다.
[공통 변경 규칙](../README.md), [검증 계약](../../verification.md), [구현 방법](../../implementation-method.md)을 따른다.
전달과 정리는 각각 [P14](../14-protected-delivery/spec.md), [P15](../15-resource-retirement/spec.md)의 책임이다.

## 요구사항

| ID | 관측 가능한 수용 조건 |
| --- | --- |
| P13-R1 | 요구의 원문 참조·수용 revision→TC/평가→실행 revision→원본 증거를 연결하며 요구 본문을 새 대장에 복제하지 않는다. |
| P13-R2 | 새로운 결정적 동작은 목적 때문에 실패하는 RED와 수정 후 GREEN, 같은 진입점의 정상/금지효과 oracle을 갖는다. |
| P13-R3 | 실행 여부·case 수·skip·실패·중단·관측 불가를 구분하고 0개 수집/미실행을 PASS로 처리하지 않는다. |
| P13-R4 | candidate/head/base/spec/policy/fixture가 바뀌면 영향받는 증거를 재평가하며 과거 green을 자동 승계하지 않는다. |
| P13-R5 | 실제 L 판단·D replay·실제 O를 구별하고 critical 위반을 평균점수로 상쇄하지 않는다. |
| P13-R6 | public 증거는 허용된 요약·revision·원본 링크뿐이며 private transcript/경로/native ID/secret을 내보내지 않는다. |
| P13-R7 | CI 변경은 required 검사·신뢰된 도구·권한 경계를 유지하고 최종 후보의 독립 검토와 실제 CI까지 확인한다. |
| P13-R8 | versioned `workflow_step.verify_only`의 실제 검증→read-only review→좁은 완료를 연결한다. 완료 경로 미지원이면 배정 전 대기하며 전달·자원 retirement 상한과 legacy fallback 금지를 유지한다. |

## 선행조건·입출력·정본

선행은 아래 구현 단계별로 판정한다. P01–P12의 모든 운영 capability를 무조건 선행시키지 않는다.
실제 native provider가 미지원이어도 D·평가 자료 구현은 가능하지만 필수 L/O를 PASS로 바꾸지 않는다.

| 단계 / PR 결과 | 요구·검증 책임 | 필요한 선행 능력 / 후속 인계 |
| --- | --- | --- |
| 증거 수집·CI | R1–R7의 수집·export·분류·revision 연결·CI 소비. T01/02/04/05/06/08과 T03의 artifact 판본 불일치 사례 | 수용 spec·선택할 실제 TC·VF 결과 계약·기존 CI. native 명령 완료와 무관하게 개발 가능. 구현 단계 1–6을 소유하며 exporter/manifest 판본과 실제 CI 증거를 다음 단계에 인계 |
| 좁은 검증 실행 | R1–R7을 실제 candidate/run에 적용하고 R8 완료. T03의 verification/review 변경·restart, T07/09와 영향받는 증거 수집 회귀 | 위 결과 계약과 P02 공통 typed handler/admission, P05 공통 MCP 명령 배선, 수용된 CP/EX candidate·checkpoint 계약, 해당 read-only review·bounded 완료의 qualified native 경로. 구현 단계 7–8과 MCP/native/runner consumer를 소유. P14에는 실제 candidate 검증·독립 review 능력과 해당 판본/제한을 인계 |

단계 9의 최종 검증은 두 PR에 각각 적용한다. 첫 단계의 병합으로 `verify_only`를 광고하거나
P14의 candidate 검증 선행 조건을 충족시키지 않는다. native provider가 미확인일 때 두 번째
단계의 guard·fault D 구현은 가능하지만 명령 활성화와 실제 O 완료는 보류한다. 새로운 native
인터페이스나 provider 필드를 이 분해를 이유로 발명하지 않는다.

모든 기능 PR은 처음부터 그 요구의 TC와 필요한 평가를 함께 구현·실행한다. P13 첫 단계가
아직 없으면 기존 지원 검사와 작업 증거 경로를 사용한다. P13을 기다리며 다른 기능의 테스트를
뒤로 미루거나 Hydra 자체 개발을 아직 미완성인 `verify_only` 명령에 의존시키지 않는다.

| 입력/출력 | 정본·처리 |
| --- | --- |
| 요구·case 정의 | 수용된 spec와 versioned `tests/fixtures/mvp/verification/`, `evals/mvp/`; 원문은 참조하며 candidate에서 oracle을 역산하지 않음 |
| 실행 정책 | 보호된 프로젝트의 registered argv/cwd/timeout과 현재 위임. fixture의 임의 shell/URL을 실행 명령으로 채택하지 않음 |
| D 실행 | 실제 unittest 결과·관측 효과·임시 Git/process. 기존 `Workspace.verify`의 private output은 원래 수명·접근 경계를 유지 |
| L 실행 | 기존 허용 Codex 평가 문맥의 실제 행동/도구 결과와 독립 판정. 별도 상주 평가 서버 없음 |
| O 실행 | 검증 계약 O01–O06의 실제 provider 원본. 합성 응답·화면 fixture를 운영 증거로 승격하지 않음 |
| 결과 | 검증 계약 §2의 결과 envelope를 기존 CI artifact/작업 산출물에 기록. `PASS/FAIL/NOT RUN/BLOCKED`와 제한·남은 책임 포함 |

artifact 자체는 권한이나 trusted CI 인증서가 아니다. producer/workflow/event/ref/head는 외부 원본에서 확인한다.
L rubric의 `UNCERTAIN`은 미해결 판단이며 해당 요구의 PASS를 막는다. 공개 결과에는 원문 대신 이유 코드를 쓴다.

## 변경할 소스와 단계

현재 읽은 경계는 `hydra_sdlc/project.py`의 verification 정책, `workspace.py:verify/verification_output`,
`runner.py:_verify_candidate`와 candidate review, `native.py`의 verification/review cache다.
좁은 검증 실행 단계는 `control.py`/`mcp.py` 공통 CommandV1 handler의 `workflow_step.verify_only` validation·route와
`native.py`/`runner.py`의 bounded review 완료와 하위 효과 제한도 소유한다. [CP §8](../../contracts/control-plane.md#8-command-envelope와-공통-guard)의
typed union·expected/source 검사와 EX §4를 재사용하며 새 명령·별도 실행기·임의 effect allowlist는 만들지 않는다.
기존 runner를 새 평가 실행기로 교체하지 않는다. 원본 증거의 scope/수명 결함이 확인된 부분만 수정한다.

1. accepted 요구에서 해당 PR의 case 목록과 독립 expected/forbidden effects를 먼저 고정한다.
   기존 TC가 같은 행동을 검증하면 재사용한다. 새 suite는 `tests/test_mvp_verification_contract.py`다.
2. `tests/fixtures/mvp/verification/`에 합성 원본·사건열·oracle·requirement/selector 연결을 둔다.
   등록된 필수 case의 selector가 없거나 0개면 실패한다. ID 존재 검사는 의미적 충족의 대체가 아니다.
3. `scripts/run_mvp_verification.py`를 예정된 얇은 unittest 수집/실행·결과 export 경계로 추가한다.
   versioned manifest의 선택된 필수 case를 실제 loader로 수집하고 count·실행·skip·실패를 대조한다.
   manifest는 요구/selector/fixture 참조만 담고 임의 명령을 받지 않는다. 별도 결과 저장소는 두지 않는다.
   선택된 필수 D가 모두 실제 실행돼 PASS이고 유효 export까지 완료된 경우에만 process exit 0이다.
   selector/manifest 오류·0개 수집·필수 skip·실패·중단·export 실패는 nonzero와 safe reason을 반환한다.
   지원 실행은 `python3 -I`로 시작하며 초기 import 전 격리 여부를 확인한다. 시작 모듈의
   shadowing이 source 검사와 공개 출력 제한보다 먼저 실행되는 경로를 허용하지 않는다.
4. export는 검증 계약 §2의 필수 필드와 공개 allowlist를 적용한다. raw 출력은 public JSON에 붙이지 않는다.
   서로 다른 run을 합쳐 PASS를 만들지 않는다. missing/invalid envelope는 판정 보류이며 기존 증거는 보존한다.
5. `evals/mvp/`에 공개 개발 사례·rubric·실행 인계를 준비한다. 실제 L은 기존 Codex 문맥에서 수행한다.
   최종 사례는 허용된 독립 평가 환경에 두며 답안 노출·비용·반복·모델/도구 조건을 결과에 명시한다.
6. `.github/workflows/ci.yml`의 기존 kernel 검사에 수집/증거 계약 검사를 연결한다. 현재 Mac/hygiene와
   pinned trusted 도구를 유지한다. 새 artifact는 safe envelope만 게시하며 untrusted PR에 운영 secret을 주지 않는다.
   CI는 실제 종료값을 gate로 소비한다. `continue-on-error`·JSON 존재·이전 artifact로 실패를 green으로 바꾸지 않는다.
7. 공통 handler에서 CP의 정확한 candidate/source 기대값·현재 admission을 확인하고 server가 verify_only
   effect ceiling을 고정한다. registered verification·안전한 local checkpoint·독립 후보 검토의 실제 기존 경로를
   재사용한다. 요청의 candidate pin과 현재 head가 다르면 새 후보로 자동 갱신하지 않는다. 모든 하위 dispatch에
   제한을 전달하며 상한 밖 다음 효과는 `waiting/effect_not_allowed`로 반환한다. 지원된 read-only 후보 검토와
   정상 review-step 종료는 자원 retirement와 구분한다. 실제 검증 결과와 미완료 review 책임을 각각 반환한다.
   새 구현 배정/publish/PR/remote review 요청/merge/close/자원 retire 0회이며 전달은 읽기 대사만 허용한다.
   capability는 CP typed profile과 전체 반환/완료 경로 검증 후에만 광고한다. completion 미지원이면 review ticket 생성 전에 대기한다.
8. CP verify_only의 run/review_checkpoint variant를 같은 handler와 effect scope에 연결한다. 기존
   `NativeRunner._model`·`NativeController._checkpoint`·`Runner._candidate_result`에서 review 입력 검사와
   bounded outcome→최종 record read-back→exact step retirement read-back→matching ticket 해제만 분리한다. `runner.step`·`_correct`·
   legacy checkpoint·첫 checkpoint_only로 결과를 우회하지 않는다. private summary는 기존 한도·수명을 유지한다.
   CandidatePin·현재 live change_review assignment·검증 run/review_steps·head/dirty/spec 불변을 대조한다.
   같은 head의 재실행도 실제 argv/result/output digest와 기존 private run 연계로 구별하며 새 DB·공개 transcript를 만들지 않는다.
   candidate_ready는 이 증거가 모두 유효할 때만 local review 수용이다. failed/needs_decision은 명시된 진단/
   결정 대기를 기록하고 끝내며 새 correction·검증·질문·assignment를 시작하지 않는다. 표시는 CP receipt를 따른다.
   cache/review-run 근거 소실 시 완료 outcome은 보존하되 수용하지 않는다. exact 끝난 step의 최종 원본을
   read-back한 뒤 matching ticket을 retire하고 명시 재검증을 기다린다. 같은 호출에서 새 review는 0회다.
   응답 유실·중복은 원본을 먼저 대사한다. old request 귀속 불명은 unknown이며 새 완료 receipt를 제조하지 않는다.
9. 좁은 RED/GREEN 뒤 Python 전체와 영향받는 실제 consumer를 검증하고 최종 head의 리뷰·CI를 확인한다.

계획 script와 fixture는 아직 없으며 위 이름은 구현 범위다. 이 명세 작성으로 실행 가능하다고 주장하지 않는다.
다른 packet의 아직 미구현 case를 조용히 manifest에서 빼서 v1 전체 통과를 만들지 않는다.
packet 범위 검증과 최종 v1 전체 요구 집합은 구분하고 선택 집합·제외 이유를 report에 남긴다.

## 정상·fault TC와 독립 oracle

이번 검증 인계는 기존 상태열·반복 L·holdout을 재사용한다. VF의 효과 경계별 중단과 source
복구 뒤 정상 진전, 평가자와 사람 기준의 보정, 모든 trial 보고, 같은 실제 run의 결과 연결을
구현 manifest/평가 보고에 포함한다. 새로운 DB나 모델 service는 요구하지 않는다.
always-deny 변형이 정상 대조군에서 실패하고 유창한 완료 주장도 누락된 원본 결과를 상쇄하지
못하는지 확인한다. 측정 불가한 API/모델 사용량을 0으로 채우지 않는다.

| TC / 연결 | Given·When | 기대 결과·금지 효과 |
| --- | --- | --- |
| P13-T01 / VF-D01 | accepted R1 충족·R2 누락, 유효 위임·head | R2만 미완료; 같은 경로의 완전 후보는 정상 통과. 모든 후보 거절은 실패 |
| P13-T02 / VF-D01/02 | 실제 subprocess에서 manifest selector 삭제, 0개/필수 skip/오류/실패/정상 실행 | 불완전 run은 nonzero·CI 실패; 필수 D 전부 실행 PASS+유효 export만 exit 0. count/status와 실제 CI consumer를 함께 검증 |
| P13-T03 / EX-D09/10 | export한 요구·후보 판본 불일치; verification/review 중 head/spec/dirty 상태 변경, cache restart | 수집 단계는 불일치 artifact 재사용을 거절. 실행 단계는 영향을 받은 review 무효·현재 증거 재수집. 과거 private cache를 완료 근거로 승격하지 않음 |
| P13-T04 / VF-D06/08 | 실제 subprocess에서 실행 뒤 export 실패·중단·다른 revision artifact | nonzero·CI 실패, 기존 실행/edits 보존·해당 증거만 unknown/NOT RUN; 실제 효과를 새로 실행해 기록을 맞추지 않음 |
| P13-T05 / VF-D12/16 | private canary·과대 출력·손상 envelope | 공개 artifact에 canary 0개; safe reason, raw traceback 공개 0회 |
| P13-T06 / VF-D01/09 | identity guard 제거·unknown을 success로 주입·옛 CI 허용 | 격리된 결함 후보에서 관련 TC 실패; 대상 함수로 expected를 재계산하지 않음 |
| P13-T07 / VF-D24, EX-D15 | MCP→공통 handler→runner의 verify_only, pin한 유효 후보/최종 delivery-ready/stale candidate/미지원 runtime | 실제 registered D 수행과 지원된 독립 검토/대기 구분; 새 구현/publish/PR/원격 review 요청/merge/close/자원 retire 0회. stale·미지원은 효과 0, legacy fallback 0 |
| P13-T08 / VF-D09/12 | CI diff가 검사 삭제·candidate scanner config·secret 권한 확대 | 계약 검토 실패, trusted hygiene 유지. 정상 제한된 추가 검사 diff는 수용 가능 |
| P13-T09 / P13-R8, EX-D09/10/15 | 실제 typed run→D→독립 read-only assignment→review_checkpoint, 각 outcome/후보·run 변조/Pause/cache 소실/완료 read-back 전후 유실·restart | 정상 candidate만 bounded review 수용·record read-back→matching retirement. 실패/결정은 대기, lost run은 수용 0·명시 재검증. 완료 미지원은 ticket 생성 0; publish/수정/다음 배정/legacy fallback 0 |

oracle는 수용된 요구·고정 사건열·독립 효과 spy와 실제 임시 Git/process 결과다. 내부 mock 호출수만 보지 않는다.
검증 장치의 TC는 export의 실제 입력/출력과 실제 unittest 수집을 연결하며 implementation 문자열 검색만으로 끝내지 않는다.
기존 checkout을 삭제/되돌려 RED를 만들지 않는다. 이전 revision 또는 통제된 결함 주입은 별도 격리 후보에서만 사용한다.

## 실행 명령과 D/L/O

아래 명령은 계획된 실행 단계이며 이번 설계 작업에서 실행하지 않았다. 로컬 실행은 허용된 host runner 안에서 한다.

| 구분 | 명령/방법 |
| --- | --- |
| 기존 D | 루트: `python3 -m unittest discover -s tests -v`; 좁은 회귀는 `test_verification_output_budget.py`, `test_native.py`, `test_ci_whitespace.py`를 `-p`로 선택 |
| 기존 Mac 영향 검사 | `apps/mac`: `npm test`, `npm run build`, `npm run verify:theme`, `cargo test --locked --manifest-path src-tauri/Cargo.toml` |
| 예정 P13 D | `python3 -m unittest discover -s tests -p 'test_mvp_verification_contract.py' -v`; 구현 후 실제 case 목록/수집 수 확인 |
| 예정 exporter | `python3 -I scripts/run_mvp_verification.py --manifest tests/fixtures/mvp/verification/cases.json --output <allowed-artifact-path>`; output은 허용된 artifact 경로로만 사용 |
| L | L01/05/06/09/19와 EX-L01: 충분한 설계 재사용·green이나 누락·원인 진단·완료 판단. 의미 입력이 바뀌지 않는 기계적 exporter 변경만이면 해당 delta L은 N/A와 이유 기록; 전체 v1 L은 생략하지 않음 |
| O | O02의 실제 설계→구현→검증→read-only review→bounded 완료와 O05 최종 CI를 확인. raw D만으로 native 운영 PASS 금지; 실제 provider 미확보 시 해당 O는 NOT RUN/BLOCKED |

model/prompt/tool/fixture/baseline/candidate·반복·비용 상한은 실행 전에 고정하고 모든 run을 남긴다.
고정 모델 제품을 강제하지 않으며 지원하지 않는 sampling 제어를 고정했다고 주장하지 않는다.
critical 위반 또는 미해결 UNCERTAIN은 해당 L 수용 실패다. 고정 응답 재생은 D이며 live L이 아니다.

## 리뷰·완료·회복

독립 reviewer는 spec 충실성(필수 요구/금지 효과/정상 진전)과 품질·보안(oracle 독립성·격리·공개 경계)을
원문/diff/실제 결과로 각각 확인한다. 저자의 요약이나 숫자 coverage를 승인 근거로 쓰지 않는다.
CI를 바꾸면 workflow 자체와 실행한 검사/producer도 검토한다. 보호 규칙·required check를 약화하는 권한은 없다.
수정된 head/base의 영향 검증·필수 final-head review/CI가 충족돼야 PR ready다. 과거 green을 재표기하지 않는다.
증거 수집·CI 단계의 병합에는 해당 TC·safe export·실제 최종 후보 CI 소비와 독립 리뷰가 필요하다.
이 결과는 native review의 실제 완료를 입증하지 않는다. 좁은 검증 실행 단계는 실제 candidate에
연결된 검증→독립 review→bounded 완료와 O02 증거를 확인해야 해당 capability 완료다.
소스만 안전하게 병합할 수 있는 경우에도 미검증 기능은 비활성·NOT RUN/BLOCKED로 남긴다.
P13 전체 완료는 R1–R8의 D/L/O 적용 결과, safe artifact, 원본 링크, 제한·후속 owner가 연결된 상태다.
환경 실패는 BLOCKED, 미실행은 NOT RUN, 동작 결함은 FAIL로 남기고 재현→원인→TC→수정 순서로 복구한다.
report/export 유실은 원래 run의 증거를 재조회한다. 증거를 복원하지 못하면 해당 검증만 다시 수행하며 전달 효과는 반복하지 않는다.
