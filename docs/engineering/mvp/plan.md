# Hydra v1.0.0 구현 계획

Revision: 13 · 상태: 설계 후보 · 2026-10-19

[상세 설계](spec.md)의 R01–R16을 실제 동작까지 만드는 계획이다. 아래 파일명과 TC는
구현할 대상이며 현재 존재하거나 통과했다는 뜻이 아니다. 작업 기록은 GitHub에 두고
이 문서에 Issue 상태·CI 결과·진행률을 복제하지 않는다.

## 0. 자료조사에서 설계 개정과 실행 인계까지

이 절은 전체 설계 개선의 수행 순서다. 조사 자료 자체와 제품 채택을 구분하고, 기존 조사의
주장을 `확인된 충돌 / 지원 확인 필요 / 선택 개선 / 이미 충족`으로 재판정한다. 조사 질문마다
공식 출처·확인일·적용 version/surface·관측 범위·반대 근거·영향 요구·결정·TC를 연결한다.
자료 링크 개수나 설계 분량으로 완료하지 않는다. 공급자 사실은 아래 소유 계약에서 확인한다.

| 조사 질문 | 조사·설계 소유 | 이번 개정의 결정과 후속 증거 |
| --- | --- | --- |
| 누가 기존 native 작업을 읽고 이어가나? | NC·CS, P01/04/07/08 | surface별 지원 표와 최소 실증. 앱 tool·설치 CLI·최신 문서를 상호 대체하지 않음. live 연결은 미확인 |
| proactive는 언제 어떤 결과를 만드나? | 제품 §3, P08/10 | 발견·위임 진행·복구 구분; 동일 제안 억제·거절 후 재검토·비용/끝조건. 별도 scheduler 없음 |
| 목표 분해 뒤 관계를 누가 만드는가? | WR·GI, P10/11 | P10의 native 등록 주체가 명시된 관계 준비를 담당, P11은 읽기/gate. 생성 성공·관계 실패 복구를 통합 시험 |
| 전달 증거가 연속 병합에도 남나? | GI·EX, P14 | PR latest-only와 main SHA별 CI 보존을 분리. 실제 workflow 수정·실행은 P14의 후속 구현 |
| 최소 데이터로 복원 가능한가? | NC·CP·WR | 현재 외부 정본 우선 유지. 원본 연결 불가를 숨은 map으로 메우지 않음. 새 저장 필요가 입증되면 목적·보존·권한을 별도 결정 |
| 정상 진행·판단 품질을 어떻게 측정하나? | 검증 정의·구현 규율, P13/16 | 기존 D/L/O·상태열 TC 재사용, 독립 결과 oracle·평가 보정·사용자 개입 지표를 구체화 |
| 여러 프로젝트 조회 비용과 안전성은? | CP·P12/16 | 화면 조회와 효과 직전 검증을 구분, 조회 범위/호출 수/지연 측정. freshness를 권한으로 사용하지 않음 |

현재 설계에 이미 있는 유연한 접수, first-flow 실증, 정상 대조군, 상태열 시험, held-out L 평가,
native 직접/매개 구분을 새 기능처럼 다시 만들지 않는다. 정확한 main SHA 증거 보존과 관계 준비
주체는 구체적인 수정 대상이다. 원문 변경 시 binding 보류를 완화하는 안은 선택 개선으로 남긴다.
현재 guard를 바꾸지 않고, 반복 제안/과잉 질문·일상 수정 비용을 측정한 뒤 별도 판본에서 결정한다.

### 0.1. 개정과 인계의 순서

1. 실제 candidate·accepted 계약·설치 표면·기존 작업을 대사한다. 기능군별 정상/실패/재시작/
   동시 변경/다중 창구/공개 범위를 대조하되 효과가 같아지는 조합을 무한 열거하지 않는다.
2. 공식 문서·현재 소스·설정으로 사실을 확인하고, 결정에 필요한 최소 실증을 정의한다.
   read 성공을 write·human identity·restart 복원으로 올리지 않는다. source가 미확인이면
   그 기능의 활성화만 보류하며 독립 fixture·guard·문서 작업은 진행한다.
3. 제품→구조→소유 계약→PR→검증의 순서로 기존 문서를 개정한다. 새 대장이나 계약 사본을
   만들지 않는다. 실제 제품/권한 선택만 분리하고 가역적 내부 구현 선택은 구현자에게 남긴다.
4. 독립 검토에서 의미·지원 가능성·책임 공백·공개 경계를 검사하고 최종 문서의 링크·요구/TC
   연결을 확인한다. 문서 검사가 D/L/O 실행이나 새 계약의 운영 수용을 뜻하지 않는다.

### 0.2. 결과로 묶는 구현 순서

| 단계 | 기존 PR 능력의 조합 | 통과 증거 |
| --- | --- | --- |
| G1 실행 연결 | P01–07 중 첫 흐름에 필요한 능력 | 아래 §1.2의 같은 task 질문·Pause·원격 답변·재시작·Resume·실제 진전 |
| G2 한 작업 전달 | P09–14 및 필요한 P15 | 기존 설계 재사용→필요 관계 준비→구현/검증→보호 병합→해당 merge SHA 확인→정리 |
| G3 자율 복구 | P07/08/15/17/18과 기존 실행 guard | 응답 유실·중복·offline·scope 변경 후 같은 책임 복구, 불필요 예약 종료 |
| G4 선제적 다중 프로젝트 | P08/10/12/16과 각 원본 능력 | 유용한 제안·채택·진행, 다른 프로젝트 격리, 중복 제안/과잉 질문/비용 측정 |

G1–G4는 새 tracker 상태나 추가 PR이 아니라 통합 증거의 묶음이다. 번호순 전체 PR 병합을
강제하지 않는다. P12/P16의 읽기·제어 화면은 각 단계에서 실제 지원된 능력부터 검증한다.
첫 흐름에 전체 프로젝트 연결·관계 전환·UI 완성을 선행시키지 않는다. 필수 O가 남은 기능은
설계 후보/구현 후보로만 인계하며, 모든 native 기능을 만들 수 있다는 보장으로 포장하지 않는다.

### 0.3. Codex 중심 운영 개정의 구현 순서

원격 Codex만으로 필수 사용자 조작을 수행하는 것이 기준이다. 앱은 보조 화면이며 native
Plan/Goal/질문과 MCP를 중복 구현하지 않는다. 다음은 기존 PR의 능력을 연결한 순서다.

| 결과 | 기존 변경 단위 | 해당 결과의 증거 |
| --- | --- | --- |
| 사용 가능한 native 기능·설치 표면 특정 | P01, NC·CS | 문서/노출/fixture/설치/원격 실제 증거 구분; P01 caller unverified를 권한으로 사용하지 않음 |
| 질문에서 수용 설계·TC로 연결 | P04/P10, EX·CS·스킬 | 객관식+추가 설명, 주관식, 수정·부분 응답·충돌; 준비 질문에 가짜 checkpoint 없음 |
| 같은 core의 제한된 MCP 효과 | P02/P03/P05/P06 | CAS·scope·expected·현재 위임·정확한 source, legacy broad 경로 우회 없음 |
| 세션·Goal 지속과 대기 복구 | P07/P08 | 실제 owner 재사용, Goal 예산 보존, native continuation과 외부 대기 예약 분리 |
| 검증·전달·원본 복구 | P13/P14/P15 | exact CI·리뷰·원본 효과 확인·보존/정리, 미확정 재시도 0 |
| 원격 Codex 종단 수용 | O01–06 및 P16 | 로컬 앱 조작 없이 질문·답변·조회·Pause/Resume·중단 결과·전달 확인 |

이 표는 새 PR 번호나 tracker 상태를 만들지 않는다. P01의 읽기와 P02의 CAS core는 독립
구현할 수 있다. P04의 원본/신뢰 경로가 미확인인 동안 모델 JSON을 답변 증거로 받는 P06을
열지 않는다. 해당 live 경로의 미확인과 실행 가능한 fixture·정상 대조군을 구분해 진행한다.
Plan은 모든 변경의 의무 절차가 아니며, 이 문서 구현 요청 자체로 native Goal·예약을 생성하지 않는다.

## 1. 시작 조건과 작업 단위

W0는 새 제품 기능이나 의식적인 승인 단계가 아니라 현재 상태 대사다. 실제 repository,
base/head, dirty 변경, 기존 Issue/PR, 설치 runtime, 작업 소유권을 확인한다. 기존 후보를
보존하고 구현할 경로 하나를 정한다. 현재 설계 revision과 독립 검토 결과를 기존 작업에
연결한다. 이미 결정한 목적·권한·정책을 다시 묻지 않는다. 새로운 경계만 구체적으로 해결한다.

W0에서 아래의 전체 조작 계약과 [플랫폼 책임 경계안의 정합성 목록](../../architecture/platform-boundaries.md#7-기존-후보와의-정합성변경-기록)을
먼저 대조한다. 기능마다 누가 무엇을 어떤 범위에서 변경하는지 정한 뒤 W1에서 필요한 호출
주체·owner·지원 경로를 확인하고, W2에서 native 관계와 legacy 원본 선택을 구체화한다.
기존 packet 이름과 예정 schema를 그대로 구현하는 것이 이 단계의 목적은 아니다.
의존하지 않는 조사·검증 설계는 계속 진행할 수 있다.

W1a의 첫 단계는 [native 계약의 사전 조사](contracts/native-capability.md#3-w1-사전-조사와-실제-qualification)다.
직접 외부 호출과 native 매개를 같은 관측·제어·복구 기준으로 비교한다. 정적 명세 조사만으로
W1a packet이나 실제 capability를 완료 처리하지 않는다. W1b는 경로·대상·권한을 정한 최소
조회부터 시작하고, 필요한 최소 구현 뒤 해당 기능의 실제 시험을 수행한다. 실행·질문·중단·
복원·정리를 모두 검증한 W1b 전체 완료를 W3/W4/W6 구현의 선행 조건으로 두지 않는다.

이 설계 작성 시 Hydra checkout에는 프로젝트 등록용 `.hydra.toml`이 없었다. 구현 시작 때
다시 확인한다. Hydra 자신의 등록/실행 능력을 구현의 선행 조건으로 만들지 않는다.
기존 저장소의 Codex 개발 절차로 구현하고, 실제 Hydra self-use는 별도의 등록과 capability
증거가 확보된 뒤에만 수행한다. 가상의 등록이나 fixture를 실제 연결로 표시하지 않는다.

W1–W7과 아래 13개 packet은 제품 책임 묶음이다. 실행 진입점은
[변경 명세 P01–P18](changes/README.md)의 구현 단계이며, 이 문서 §1.6이 단계 간 순서를 연결한다.
W는 책임 참조, P는 유지·개정할 명세, G는 통합 수용 묶음이다. 별도의 세 작업 queue로 관리하지 않는다.
packet 하나나 명세 하나가 PR 하나를 뜻하지 않는다.
한 packet의 목적은 한 결과이며 한 함수·한 파일·한 TC마다 Issue를 만들지 않는다.
기존 작업과 결과가 같으면 재사용한다. 실제 변경이 커서 독립 전달/복구가 필요할 때만
분할하고, 너무 작으면 같은 결과의 packet을 합친다. 아래 번호/제목은 강제 Issue 문법이 아니다.

모든 packet에 공통인 여섯 항목은 다음과 같다.

| 항목 | 고정할 내용 |
| --- | --- |
| 목적 | 아래 결과와 R/S 요구 참조; 구현 편의가 목적을 대체하지 않음 |
| 책임 | 아래 source owner는 변경 후보 경로; 현재 코드를 읽고 영향 경계를 확인 |
| 동작 | 입력·출력·불변식과 source revision; 상세 schema는 소유 계약 한 곳에서 참조 |
| 실패·복구 | 금지 효과, 원본 보존, 대사와 재시도/질문 조건 |
| 완료 | 해당 TC/eval/운영 증거 + 필수 회귀·CI·독립 리뷰; NOT RUN은 완료 아님 |
| 범위 | 해당 결과에 필요한 최소 변경; 다른 제품 규칙/새 DB/실행기/스케줄러 제외 |

각 packet에서 먼저 요구 기반 기대값과 의미 있는 실패를 만들고, 구현하고, 관련 회귀와
독립 검토를 마친다. CI 변경이 필요하면 그 packet에 포함한다. 마지막에 TC/CI를 붙이지 않는다.
설계와 구현이 충돌하면 그 원인을 수정하며 통과를 위해 요구나 oracle을 낮추지 않는다.

### 1.1. 지금 먼저 닫을 설계와 구현 시작 조건

다음 산출물은 기존 문서의 개정으로 만든다. 새 tracker나 문서 묶음을 추가하지 않는다.
전체 기능의 책임·권한·정본을 먼저 맞추고, 상세 schema와 구현은 작은 결과 단위로 확정한다.
모든 기능의 세부 구현 설계가 끝나야 첫 구현을 시작하는 방식은 아니다.

전체 조작표의 첫 후보는 [제품 설계의 F01–F12](../../product/mvp-design.md#42-전체-기능-조작표)에
작성했다. 조작 의미·끝조건·충돌 기본값은 제품 문서가 소유한다. 첫 흐름은 아래 §1.2와
EX §7/CP §8/NC §2.1/검증 정의에 상세화했다. native 원본의 실제 지원 확인과 해당 구현은
남아 있다. 이 좁은 정합화가 WR의 전체 관계 전환이나 제품 전체 계약의 완료는 아니다.

| 순서 | 할 일과 소유 문서 | 끝의 조건 |
| --- | --- | --- |
| 1. 전체 조작표 | 제품 설계에 기능별 사람의 목적, 입력 주체/창구, 대상, 권한, 변경 효과와 적용 시점, 정본, 실패/복구, 완료 근거를 연결 | 아래 12개 기능군을 누락 없이 대조. command·원본 변경·제안·답변·wake가 각각 어떤 의미인지 구분하고 미결정 항목을 표시 |
| 2. 공통 의미와 원본 검증 | architecture와 WR/CP/EX/NC에 상태 축, pause/stop/resume, 답변 수용/적용, 충돌 우선순위, 각 효과의 복원 방법을 정렬 | 필요한 사실마다 실제 저장 주체·지원 조회·identity·revision/보존 범위를 특정. 원본이 보장하지 않는 원자성·중복 방지를 가정하지 않음 |
| 3. 첫 흐름의 상세 계약 | 아래 범위에 필요한 기존 계약과 D/L/O 기대값을 고정하고 독립 검토. W1a 사전 조사와 W1b 최소 조회로 호출 주체·대상·권한 확인 | 범위 안의 목적·책임·동작·실패/복구·완료·제약에 구현자가 새 제품 결정을 해야 하는 공백이 없음. 미지원 경로는 대안/제한을 명시 |
| 4. 작은 구현과 실제 증명 | 필요한 W3/W4 부분을 구현하며 해당 TC/CI와 native 시험을 함께 수행 | 아래 첫 흐름을 실제 원본 증거로 확인. 그 뒤 다음 결과 단위로 확대하고 최종 W1b/O 수용은 끝에서 판정 |

전체 조작표가 대조할 기능군은 연결/해제·설정, 위임/범위 변경/철회, 접수/채택, 설계/계획/
우선순위/의존, 세션/할당/실행, 질문/답변/결정, pause/stop/resume/cancel, 검증/리뷰/수정,
발행/전달/배포/후속 관측, 지속 관측/예약/재진입, 실패/응답 유실/재시작/인계,
완료/보관/정리다. [대화·제어 시나리오](../../product/interaction-scenarios.md)는 이 중 창구
전환 사례이며 전체 기능 계약의 대체물이 아니다. 기본 동작은 설계자가 제안하고, 실제로
미정인 목적·taste·권한·정책만 구체적 선택으로 사람에게 묻는다.

위임 책임·작업·결정·실행 시도·예약·전달·자원 상태를 한 상태값으로 합치지 않는다.
Hydra 명령 경로의 guard와 Codex/GitHub에서 직접 바뀐 사실의 관측·대사를 구분한다.
효과별로 조건부 변경/직렬화가 가능한지, 요청 접수와 실제 적용이 어디서 갈리는지,
응답 유실 후 무엇을 조회하는지 정의한다. 조회 목록에 없다는 이유만으로 미실행을 단정해
재시도하지 않는다. 복원 가능한 원본이 없으면 해당 자동 동작의 지원 공백으로 남기고,
숨은 로컬 사본이나 무조건적인 exactly-once 주장으로 메우지 않는다.

### 1.2. 첫 통합 증명의 범위

기존에 유효한 프로젝트·작업·설계·위임이 있으면 재사용해 한 owner에서 아래 흐름을 증명한다.
새 intake/binding 전환·전체 UI·두 프로젝트 운영의 완성을 먼저 요구하지 않는다.
상위 admission이 running인 상태에서 한 프로젝트의 pause와 같은 범위의 resume을 사용한다.
host 전체 pause를 프로젝트 resume으로 해제하는 시험과 섞지 않는다.

> 위임된 한 작업 → needs_decision checkpoint → 같은 task의 질문 → project pause → 원격 답변 →
> pause 유지와 답변 상태 관측 → 명시적 scoped resume → 유효한 다음 행동과 원본 결과 확인

- 필수 사람 조작은 지원되는 원격 Codex에서 수행한다. Pause/Resume도 MCP 경로로 보내고
  조회와 실제 적용 결과를 같은 원격 창구에서 확인한다. 로컬 앱 버튼은 이 수용의 대체 경로가 아니다.
- 답변 수신·수용·결정 적용·실행 재개를 분리한다. pause 중에는 원본 읽기/projection과 기존의
  좁은 stopped 보존만 허용한다. GitHub 결정 pair 게시와 **다음 attempt/assignment 배정**은
  보류한다. needs_decision 뒤 이미 retire된 옛 step의 commit 거절을 Pause의 증거로 세지 않는다.
- Resume 뒤 현재 답변·기준을 재확인해 결정 적용, fresh attempt의 원 phase 진행과 checkpoint를
  확인한다. 첫 시험의 효과 한도는 이 결과까지이며 이후 전달은 별도다. narrow checkpoint
  지원 없이 legacy broad continuation을 호출하지 않는다.
- 원래 질문의 task/turn과 제공되는 question identity, 응답자·답변 원본, 적용 대상 revision,
  재진입 대상을 연결한다. 다른 chat의 메시지 도착만으로 질문에 답했다고 판정하지 않는다.
- 답변에 따른 native turn wake와 Hydra admission은 별개로 관측한다. 이 시험은 모든 native
  동작을 차단한다는 증거가 아니다. pause 이전에 나간 효과와 실제 중단 여부도 별도로 표시한다.
- resume은 최신 위임·설계·질문/답변·owner·admission을 재확인한다. UI 표시나 모델의 성공
  문구가 아니라 같은 책임에서 허용된 다음 행동이 수행된 증거로 통과를 판단한다.
- 중복 답변·오래된 resume·응답 유실·재시작의 TC를 해당 구현에 붙인다. 실제 재현 가능한
  유실/재시작 시험은 같은 흐름에 추가하고, 모의 시험과 실제 시험의 결과를 분리한다.

W1b 최소 조회는 연결 근거일 뿐 이 흐름의 PASS가 아니다. 실제 원격 창구·질문·답변 연결을
확인하지 못하면 NOT RUN 또는 확인된 지원 제한으로 남긴다. 최소 adapter가 필요하면 scoped
계약 검토 뒤 구현하고 검증한다. 현재 설계 문서 작성은 외부 작업의 실행·정지 권한을 추가하지 않는다.

이 단위의 상세 정본은 [EX §7](contracts/execution.md#7-질문결정다음-wake),
[CP 프로젝트 제어](contracts/control-plane.md#첫-흐름의-project-pauseresume),
[NC 원본 연결](contracts/native-capability.md#21-질문과-재개를-위한-원본-연결),
[통합 검증](verification.md#첫-통합-흐름--질문-대기와-project-pauseresume)이다.
작업 범위는 기존 operations의 CAS·동일 mode 무쓰기, native 질문/답변 reader와 decision
적용 guard, 명시 답 수정의 적용 시점별 복구, 원본 재발견, checkpoint의 효과 상한과 관련
source/consumer 검증이다. CP의 DecisionView는 수신·수용·적용을 분리하며 실제 재개는
기존 assignment/execution으로 확인한다.
구형 runner가 새 결정 기록을 우회해 소비하지 않도록 **WR의 보호된 project-v2 최소 loader와
`work_source=legacy_issue`**를 먼저 적용한 검증 환경을 사용한다. 기존 intake/의존 의미를
재사용하며 전체 WorkBinding/native 관계 전환은 선행하지 않는다. 이 정책 전환은 실제
수용·진행 중 효과 대사 뒤 수행하며 설계 작성으로 자동 적용되지 않는다. 책임 단위 pause·
cleanup-only·다중 host는 이 첫 통합 단위에 함께 넣지 않는다.

최소 읽기의 출력은 [CP의 task metadata/history 계약](contracts/control-plane.md#최소-native-읽기-관측과-결정-근거-분리)으로
고정한다. 이 읽기만으로 질문·응답 권한·결정 적용의 EvidenceRef를 만들지 않는다. 다음 source
설계는 NC §2.1의 원본 연결, 특히 native 선택 근거와 GitHub exact intent의 연결 재발견을 확정하는 것이다.
필요한 원본이 없으면 해당 capability를 보류하고 경로를 수정한다. 새 DB로 메우지 않는다.

### 1.3. 다음 좁은 구현 단위: 기존 MCP 연결의 호출 문맥 검증

기존 W1a/W3의 첫 reviewable outcome은 **설치된 Hydra와 실제 native caller가 제공하는
문맥·capability를 정직하게 구분하는 것**이다. 기본 경로는 Codex task→기존 Hydra MCP다.
역방향 native 목록/중단/wake나 자동 질문 복원을 이 연결에 포함시켜 가정하지 않는다.
상세 정본은 [NC §2.3–2.4](contracts/native-capability.md#23-선택한-기본-경로와-별도-capability)다.

| 항목 | 구현자가 따라갈 계약과 검증 |
| --- | --- |
| 입력과 source owner | SDK가 모델 입력 스키마와 별도로 주입하는 request context, actual negotiated protocol·transport·client 선언, 기존 runtime identity. 일반 tool args나 임의 `_meta` 이름을 인증된 task/사람 identity로 바꾸지 않는다. |
| 변경 책임 | 기존 `mcp.py` wrapper와 runtime identity 경계, `tests/test_mcp.py`의 독립 fake context/SDK fixture. 코드 판본·distribution metadata·module version이 다른 경우 탐지하고 consumer에 확인 수준을 보존한다. 일반 업무 begin/checkpoint 의미는 바꾸지 않는다. |
| 반환 한도 | protocol/back-channel/input 경로의 알려짐·미지원·미확인, 허용 필드의 존재/형식, 현재 runtime 연결 사실만 표시. raw metadata·headers·env·본문·credential 출력 0. 현재 task binding을 검증할 수 없으면 unknown이 정상 결과다. |
| D 검증 | NC-D01/03/06/09/10, CP-D15/16, VF-D03/16. 위조 task 인자, client 선언만 있음, source/runtime 불일치, 새 protocol, back-channel 없음, input-required 지원 여부, 자동 accept를 각각 구분한다. 기존 read로 write/wake/ticket 해제 0. |
| 실제 관측 | 검토한 reader와 정확히 대응되는 설치 경로의 status 한 번으로 caller context/지원 조건을 관측한다. 기존 설치본 응답은 그 설치본의 읽기 증거로만 쓴다. source 변경을 설치·실행한 것으로 세지 않는다. |
| 완료 | 합성 TC/관련 CI·독립 리뷰 + 실제 설치 경계에서의 최소 read 증거. 질문·재개·전체 projection 수용은 별도로 남긴다. 설치 변경이 필요하면 기존 설치/인계 절차에서 활성 책임을 먼저 대사한다. |

순서는 (1) source/설치/SDK 정적 대조 → (2) 독립 기대값과 경계 TC → (3) 최소 reader →
(4) exact installed read 확인이다. 기존 mutable 작업을 보존하고 이 단위를 검토·수용한 뒤
코드를 변경한다. 새 server·task·질문을 만드는 시험을 read 안에 숨기지 않는다.

그 결과로 두 후속을 나눈다. 지원되는 원본 결과가 Hydra까지 들어오는 경우 CP의 최소
metadata/history projection과 실제 consumer를 연결한다. 질문은 실제 client/protocol에 맞는
입력 경로와 질문·답변·공개 적용 의도의 원본 join을 확정한 뒤 별도 작은 변경으로 구현한다.
back-channel request 실패를 다른 입력 방식의 자동 재전송으로 바꾸지 않는다. Pause 중 응답
수신 뒤 restart 복원을 통과하기 전에는 첫 흐름의 자동 결정 적용을 활성화하지 않는다.

Codex는 답변의 의미·현재 기준과의 관계·공개 가능한 결정을 제안한다. Hydra는 현재 위임·
작업 귀속·revision·ownership·admission·중복 효과를 검사한다. GitHub의 exact 공개 결과를
native 원본에 다시 저장하는 구조는 요구하지 않으며 각 정본의 참조를 대조한다. reader와
무관한 project Pause/Resume CAS·effect guard의 독립 설계/TC는 병렬로 진행 가능하다.

### 1.4. 첫 흐름까지의 구체적인 구현 인계

아래는 기존 W1/W3/W4를 검토 가능한 결과로 나눈 실행 순서다. 새로운 Issue 계층이나 진행
대장이 아니다. 실제 구현자는 해당 행의 **소유 계약·정확한 판본, source diff, 수집된 TC,
검증 결과와 미해결 사실**을 기존 작업에 연결한다. 이 표의 작성은 구현 수용·운영 PASS가 아니다.

| 결과 단위 | 입력 → 결과와 소유 경계 | 선행·실패 경계 | 완료 증거와 다음 단위 |
| --- | --- | --- | --- |
| A. 호출 문맥을 정확히 읽기 — W1a/W3a | 실제 SDK 주입 문맥·startup runtime → NC §2.4의 `native_context`; `mcp.py`, runtime identity 경계, `test_mcp.py` | NC의 필드별 source/default/오류 계약. 기존 status 정상값 보존. caller task/사람/실제 입력 지원의 자격은 만들지 않음 | NC-D 및 실제 SDK/stdio integration, 같은 후보의 installed status read. **C의 입력 경로 선택에 참고하는 진단**이며 C를 통과시킨 증거가 아님 |
| B. project admission을 경합 없이 변경하기 — W3b | trusted target·기대 revision → project mode·revision·read-back; `operations.py`/`control.py`와 operation suite | A와 독립. CP의 CAS/동일 mode/상위 제한/dispatch 경계. remote writer와의 전역 원자성을 주장하지 않음 | CP-D09/10/13와 실제 시험 process/lock. lost ACK 재조회 및 유효 Resume 양성 사례. admission 적용과 실행 재개는 별도 |
| C. 한 질문의 원본 연결을 자격 검증하기 — W1b/W4b | 선택한 실제 입력 경로·native 원본 → EX가 요구하는 질문/선택 귀속·채택 판본·권한 출처와 GitHub intent 연결 | NC §2.1/2.3의 source 계약. A의 generic Context만으로 구현 가능 판정 금지. 실제 source write/read/수정 검출/재시작을 제공하는 경로를 확인 | 고정 source fixture의 D와 실제 원본 재발견 O. 미지원이면 **자동 결정 적용만 보류**하고 B·원본 읽기·WR/W5 작업 계속. transcript mirror로 메우지 않음 |
| D. 같은 선택을 한 번 적용하고 좁게 이어가기 — W3b/W4a/W4b | C의 유효 선택 + B의 admission + EX exact intent → 결정 read-back·fresh attempt·원 phase의 제한된 checkpoint | WR의 project-v2 최소 loader + 명시적 legacy source, EX의 version/유실/수정/소비 경계, CP의 versioned command/effect ceiling. C 미확인 중에는 합성 원본으로 순수 guard·adapter TC 구현 가능; 자동 live 적용은 불가 | EX-D11–14, VF-D05–08 및 legacy native 회귀. 모든 begin/advance/command 경로가 같은 guard 사용. `checkpoint_only`가 기존 broad continuation을 호출하면 실패 |
| E. 첫 실제 왕복 — 관련 W1b/W7 | 유효 작업 하나·같은 owner·실제 질문/원격 답변·B/D → paused 상태의 답변 복원·명시 Resume 뒤 실제 진전 | 전체 WR 전환·새 task·전체 UI 완료를 요구하지 않음. 위임된 검증 환경, exact installed 후보와 C 지원이 필요 | VF 첫 통합 흐름의 D/L/O. controller 재시작 전후 같은 질문/선택 복원 필수. 통과 뒤 interrupt/wake/정리 등 다음 native 범위 확대 |

소스 편집 전에 A/B/D는 해당 계약의 데이터·효과·실패 의미와 독립 검토를 고정한다. C에서
남는 것은 구현자에게 맡길 제품 결정이 아니라 **실제 provider 사실 확인**이다. 지원이 없으면
어떤 요구가 미충족인지와 가능한 지원 경로를 남기며, 새로운 실행 소유권·자격·비용이 필요한
대안만 사람의 결정으로 연결한다. 기존 native 도구의 사용 조건도 그대로 유지한다.

첫 인계의 기존 회귀 명령은 아래와 같다. 호스트의 지정 실행 wrapper 안에서 실행할 내부
명령이며 이 설계 작성 중 실행한 결과가 아니다. 새 사례는 해당 파일 또는 소유 계약의 예정
suite에 추가하고 실제 수집을 확인한다. 좁은 명령만으로 최종 후보의 전체 검사를 대신하지 않는다.

| 결과 | 기존 경계의 명령 |
| --- | --- |
| A | `python3 -m unittest discover -s tests -p 'test_mcp.py' -v`; `python3 -m unittest discover -s tests -p 'test_runtime_identity.py' -v` |
| B | `python3 -m unittest discover -s tests -p 'test_operations.py' -v`; `python3 -m unittest discover -s tests -p 'test_operation*.py' -v`; `python3 -m unittest discover -s tests -p 'test_control.py' -v` |
| D | `python3 -m unittest discover -s tests -p 'test_native*.py' -v`; `python3 -m unittest discover -s tests -p 'test_checkpoint_continuation.py' -v`; EX/VF의 신규 integration selector |

fixture·독립 oracle·CI skip 처리와 D/L/O 배치는
[검증 계약의 첫 구현 단위](verification.md#첫-구현-단위의-fixture와-판정-경계)가 소유한다.
한 파일을 여러 단위가 바꾸면 순차 통합한다. C의 source adapter와 D의 coordinator는 같은
normalized 입력 계약으로 만나는 작은 경계이며 새 provider framework를 만들 이유가 아니다.

### 1.5. PR 단위 설계로 실행하기

[change index](changes/README.md)의 각 `spec.md`에 목적·입출력·소스 경계·구현 순서·정상/실패 TC·
검증 명령·독립 검토·전달/복구 종점을 연결했다. 구현 시 현재 base/head와 해당 spec의 immutable
revision을 기존 Issue/PR에 연결한다. 계획 번호를 실제 Issue/PR 번호나 완료 상태로 사용하지 않는다.
같은 책임의 후속 작업은 기존 명세를 재사용·개정한다. 새 파일을 만들 기준과 PR별 최소 인계는
[변경 규약](changes/README.md#11-명세-재사용개정과-새-명세의-경계)이 소유한다.

| 첫 흐름 | PR 설계와 수용의 연결 |
| --- | --- |
| A | P01의 호출 문맥 진단; 질문·사람 authority를 증명하지 않음 |
| B | P02의 project admission; 독립 구현 가능 |
| C | P04의 실제 질문/답변/공개 제안 원본; P06 실제 게시를 선행 요구하지 않음 |
| D | P03 최소 호환 gate + P05 checkpoint 경계 + P06 결정 적용/재개 |
| E | 위 능력의 첫 통합 실증; 새로운 코드 변경이 없다면 별도 PR을 만들지 않음 |
| 후속 native 운영 | P07의 세션 수명주기와 P08의 재진입, P15의 종료/정리 |
| 독립 개발 흐름 | P09–P11 작업 연결, P12 projection, P13 검증 근거, P14 보호 전달 |
| 연결·위임 수명주기 | P17 연결·설정·해제, P18 범위 변경·철회·취소; 기존 등록/위임 fixture 작업의 전역 선행은 아님 |
| 최종 경험 | P16 화면 통합과 별도의 v1 전체 운영 수용 |

세션의 역할·생성/재사용/교체·독립 reviewer·context handoff는
[세션 계약](contracts/codex-sessions.md), GitHub 기능별 사용·컨벤션·접근 범위는
[GitHub 활용 계약](contracts/github-integration.md)을 사용한다. 실제 provider qualification이
없는 부분은 source-only 코드와 live 지원을 구분하며, v1의 필수 긍정 경로를 삭제하지 않는다.

### 1.6. 구현 단계와 선택 순서

아래는 실행 상태표가 아니라 각 명세의 결과를 연결하는 지도다. 이번 PR의 요구·범위·TC·종점은
해당 명세에 두고 실제 Issue/PR과 증거는 기존 작업에 연결한다. 번호순이나 전체 행 완료를 강제하지 않는다.

| 선택할 결과 | 명세의 구현 단계 | 필요한 능력과 후속 소비 |
| --- | --- | --- |
| 기존 후보 재사용 | P01 진단·P02 저장 경계의 기존 구현과 검증 기록 대사 | 동일 bytes/범위·환경 확인; P01 설치 관측과 P02 명령 연결은 별도 잔여 결과 |
| 독립 제어·호환 기반 | P02 공통 명령/target/runtime/receipt, P03, P05 | P02 저장 TC만으로 명령을 켜지 않음; P05는 공통 admission을 소비하고 P06이 P03/P04와 결합 |
| 독립 관측·검증·CI | P12 공통 projection/wire, P13 증거 수집·CI, P14 main CI 보존 | 현재 source/TC/workflow로 시작; native 지원을 요구하지 않는 범위는 연결 실증과 병행 |
| 실제 연결 확인 | P04/P07/P08의 사실 확인→최소 양성 실증→adapter/활성화 | NC의 source·actor·원본 복원 증거; 실증에 필요한 최소 구현은 먼저 허용하되 P 전체 완료를 선행시키지 않음 |
| 질문의 첫 완결 흐름 | P04·P02/P03/P05→P06와 §1.2의 실제 왕복 | P04는 P06의 실제 적용 성공을 선행으로 요구하지 않음; 첫 O 실패는 관련 연결만 복구 |
| 작업 접수·선행 판정 | P03→P09, P10의 MCP/core 등록, P11 관계·입력조건 gate | P10은 P02 공통 명령·P05 공통 MCP 배선·qualified draft 필요; P11은 새 실행을 gate하고 Issue 생성 자체를 막지 않음 |
| 검증·전달·정리 | P13 좁은 검증 실행→P14 보호 전달, P15 | P13/P14는 실제 후보 검증/review·보호 조건·main CI 보존을 소비. P15는 해당 자원 종료/보존을 소비하며 원격 명령은 P02/P05 기반 필요; 취소 정리에 P14 완료를 요구하지 않음 |
| 지속·변경·취소 | P07 세션→P08 재진입, P17 연결, P18 위임 변경 | 각 source의 실제 원본과 허용 효과; P17/P18의 독립 parser/guard는 앞선 전체 전달을 기다리지 않음 |
| 앱과 전체 수용 | P10 앱 소비·P16, P17/P18 화면 인계, G1–G4 | P12 기반과 개별 qualified 명령을 소비; 필수 원격 경로와 보조 앱 O를 구분하고 두 프로젝트 전체 수용 |

매 재진입에는 기존 진행 중 효과·복구 책임부터 대사한다. 그 뒤 현재 위임·계획 원본의 우선순위와
위 선행 능력을 만족하는 결과를 고른다. 같은 책임의 유효 작업을 새로 생성하지 않으며 대기 중인
작업 때문에 독립 결과를 막지 않는다. 우선순위가 정해져 있지 않은 동등한 후보는 후속 의존을
여는 작은 결과부터 선택한다. 목적·범위의 충돌만 사람에게 구체적으로 질문한다.

P04/P07/P08의 실제 연결이 미확인인 동안에는 해당 명세의 source 매핑·시험과 독립 구현을
진행할 수 있다. 필수 경로의 지원 부재가 확인되면 미충족 요구·단절 지점·해결 주체를 남기고
그 능력의 소비를 보류한다. 새 runtime/DB/credential 채택이나 v1 기준 축소는 자동 대안이 아니다.
세 연결의 필수 양성 실증과 본 문서의 의존 관계를 확인하기 전 전체 v1 완주 경로가 준비됐다고
표시하지 않는다. 설계 정합성 검토와 실행 준비 판정은 [검증 §10](verification.md#10-설계-인계-점검)을 따른다.

자체 개발의 PR→review/CI→보호 병합→main→복구/다음 작업은
[변경 규약 §5.1](changes/README.md#51-hydra-자체-개발의-진행과-복구)을 따른다.
제품 전달 기능이 미완성이라도 기존 허용 Codex/GitHub 절차로 그 기능을 개발할 수 있다.

## 2. 순서와 병렬성

~~~mermaid
flowchart LR
  W0[W0 현재 상태·설계 대사] --> D[전체 조작 계약·정본·범위별 검토]
  D --> A[A 호출 문맥 reader]
  D --> B[B project CAS·효과 guard]
  D --> I[독립 WR·projection·검증·전달 보강]
  A --> C[C 실제 질문·선택 원본 연결]
  C --> S[D 결정 적용·좁은 continuation]
  B --> S
  S --> O[E 첫 흐름의 실제 증명]
  O --> X[interrupt·wake·정리 등 native 운영 확대]
  I --> W7[W7 두 프로젝트 통합 · 전체 W1b/O 수용]
  X --> W7
~~~

화살표는 선택한 흐름에 필요한 계약·기능의 선행 조건이며 packet 전체 완료를 뜻하지 않는다.
W3의 core guard는 첫 실행/질문 흐름의 일부다. UI 전체를 만든 뒤 뒤늦게 붙이지 않는다.
첫 O 뒤 native 운영은 실행 중 stop과 wake, 실패/복구/정리 순으로 확대하고
서로 다른 두 프로젝트로 제품 수용을 확인한다. 각 단계에 필요한 W5 검증·CI·리뷰는 함께 진행한다.
WR의 정본 전환, GitHub projection, 검증/전달의 결정적 guard는 첫 O를 기다리는 전역 gate가 아니다.
독립적인 원본 조사·UI fixture·순수 guard TC는 실제 연결 대기 중에도 진행할 수 있다.
미지원/실패는 의존하는 조작의 완료를 막으며 전체 v1.0.0의 필수 범위면 최종 완료도 막는다.
같은 파일·host writer·외부 자원을 동시에 소유하지 않는다.

## 3. 결과별 설계와 구현 책임

| Packet / 목적 | 입력 → 출력·설계 | 실패·복구와 금지 효과 | Source owner / 범위 |
| --- | --- | --- | --- |
| W1a 지원 능력을 사실로 분류 | 지원 표면과 instance 관측 → 기능별 supported/unsupported/unverified, identity·coverage | tool 존재를 standalone 접근으로 추론하지 않음; unknown 유지 | native/control 경계, native-capability 계약; provider별 작은 adapter, 새 runtime 금지 |
| W1b 실제 연결 가능성 입증 | W1a의 경로로 사전 최소 조회 → 관련 최소 구현 뒤 실행·재진입·중단·복원·정리 단계별 증거 | 미지원 원인/해결 주체/대안 기록; 공식 지원 경로 없이 우회하지 않음 | 실제 qualification 환경과 기존 연결 코드; native-capability runbook |
| W2a 원문과 실행 계약 분리 | 임의 Issue/legacy intake/인증된 binding → WR의 단일 work_source·typed WorkBinding와 검증 결과 | malformed marker·conflict·source drift는 효과 보류; 원문 형식으로 거절하지 않음 | project/github parser·identity/digest와 보호된 project-v2 최소 loader부터 시작; progress v1 의미 유지 |
| W2b 유용한 제안을 안전하게 채택·등록 | 원문·기존 설계·실제 위임 → 해석 후보/부족한 정보/채택/한 Issue | 혼합 injection에서 요구 가치 보존; create 응답 유실은 create_key로 대사 | skill/coordinator/github; 작업 기록의 해석·위임·생성 계약 |
| W2c 실제 결과로 선행/목표 판정 | 현재 native 관계·고정 입력조건·선택한 계획 원본·증거 → 충족/미충족/unknown과 다음 후보 | close-only·cycle·잘린 그래프 통과 금지; 현재 parent가 기존 위임을 변경하지 않음 | project/github/runner의 관계 조회·dependency·goal aggregation; 계획·관계의 두 번째 정본 없음 |
| W3a 외부 사실을 일관되게 표시 | GitHub/Codex/resource 관측 → v3 projection와 v2 read-only 호환 | 부분 장애·늦은 응답·cache 소실·원문 공격에도 정상 source 보존 | control/progress + Rust protocol + TS decoder/reducer; schema/fixture 동시 변경 |
| W3b 명령을 정확한 대상·효과로 제한 | 사용자 command + 기대 revision + fresh 관측 → 허용 effect/read-back | stale·중복·유실·Stop 경합·unsupported 거절; 제한 lane 보존 | operations/control + Rust bridge + UI command state; 새 CP 효과 한도, legacy 다섯 도구 유지 |
| W4a 실행 소유와 복원 | 검증된 WorkBinding·admission·기존 자원 → 한 assignment와 실제 task 연결 | dispatch/checkpoint 유실·권한 철회·host 재시작에서 중복/foreign 변경 금지 | native/coordinator/workspace/runner; 기존 ticket·외부 기록 재사용 |
| W4b 질문과 유효한 다음 행동 | 원래 단계·질문/답변·외부 변화 → 같은 목표에서 재진입/대기 | 침묵·오래된 답은 승인 아님; 자체 progress wake loop·대기 후보 기아 방지 | native/skill/coordinator; 실제 native question/schedule capability만 사용 |
| W5 설계에 따라 구현·검증 | accepted 요구·기존 TC → 최소 변경·D/L evidence·독립 review | 누락 요구·잘못된 oracle·성공 과장 탐지; spec/head 변화 영향 재검토 | runner/workspace/skill + 관련 테스트·eval·CI; 프로젝트 평가 기준 내장 금지 |
| W6a 보호 전달과 다음 결과 | 현재 head/base·필수 checks/reviews → protected 전달·main 판정·다음 요구 | push/PR/merge 유실은 원본 대사; main 실패는 실패 책임, 무기한 pending 아님 | github/project/runner, 기존 전달 엔진 보강; 자동 권한 확대/새 배포 금지 |
| W6b 결과 이후 책임 종료 | 실제 종료·보존·owned 자원 → 정리/보관 또는 cleanup pending | partial cancel·disk 부재·예약 삭제 실패·닫힌 Issue의 잔여 책임 재발견 | workspace/operations/resource provider; 원래 lifecycle 사용, 삭제 추정 금지 |
| W7 한 화면에서 전체 흐름 운영 | W1–6 원본 projection → 개요/상세/결정/증거/제어·두 프로젝트 실제 흐름 | 다른 conventions·source 장애·재시작에서 유용한 진행과 불확실성 표시 | 기존 Mac 앱과 종단 검증; 새 tracker·미러 편집기 없음 |

## 4. Packet별 검증과 완료

TC의 입력·기대값·금지 효과 정본은 해당 계약이며 여기에는 실행 연결만 둔다.
정확한 현재 명령·예정 selector는 [검증 설계 §3](verification.md#3-현재-존재하는-검사와-앞으로-만들-검사)를 따른다.
실제 파일·수집된 case 목록을 확인한다. 없는 파일을 대상으로 0개 시험이 종료한 것은 PASS가 아니다.

| Packet | 계획 TC·평가 | 단위 완료에 필요한 추가 증거 |
| --- | --- | --- |
| W1a | tests/test_native_capabilities.py, NC-D01–10 | unsupported/partial/instance 불일치 및 정상 지원 경로 모두 검증 |
| W1b | native-capability의 실제 qualification, O01/O04 관련 단계 | 최소 조회와 단계별 실제 수용을 구분. 미지원/실패는 해당 capability와 의존 조작에 기록하고 미실행은 NOT RUN; 필수 단계 전부 확인 후 W1b 완료 |
| W2a | tests/test_work_records.py, WR-1 | legacy intake/progress 회귀, 새로운 binding 수정·재시작 경계 |
| W2b | tests/test_work_intake.py, tests/test_work_registration.py, WR-2/3, WR-L01 | 자유 형식의 유효 진행과 금지 효과 0회; WR-O01 실제 API 대사 |
| W2c | tests/test_work_dependencies.py, WR-4 | 닫힘과 산출물 차이·복수 요구·관계 변경·독립 작업 선택. WR-O02의 실제 관계/선택적 계획 source 확인, 목표 완료 의미는 L 평가 |
| W3a | tests/test_control_projection.py, tests/test_control_wire_contract.py, apps/mac/tests/projection.test.ts, Rust protocol TC | 실제 Python→Rust→TS producer/consumer 검사, 기존 v2 호환 |
| W3b | tests/test_control_commands.py + 기존 operation suite, CP-D command 사례 | read-back·Stop lane·effect ceiling, 실제 CP-O02는 W1b와 결합 |
| W4a | tests/test_mvp_execution_contract.py, EX-D/NC-D, 기존 ownership 회귀 | O01/O04의 실제 ownership·복원, unknown을 success로 표시하지 않음 |
| W4b | 같은 execution suite, EX-L01/02, 관련 L 평가 | 실제 질문·답변·턴 종료 후 재진입, 무변화 조건의 불필요 wake 없음 |
| W5 | 기존 영향 suite + tests/test_mvp_verification_contract.py 예정, VF-D, 관련 L 평가 | 불충분/잘못된 구현을 실제로 탈락시키는 oracle; 충분한 설계 재사용 O02 |
| W6a | tests/test_mvp_delivery_contract.py, 기존 delivery/post-merge suite | O05 실제 protected 전달, final head/main·후속 책임 대사 |
| W6b | delivery suite의 cleanup 사례 + 기존 resource suite | O04/O06 실제 보존·정리·예약 종료; pending 책임 재발견 |
| W7 | 전체 영향 suite/build, VF-D 통합, L 평가, O01–O06 | 서로 다른 일반 프로젝트 두 개, 실제 packaged/installed 화면·원본 read-back |

VF 통합 사례가 여러 파일에 걸치면 각 packet에서 실제 selector를 검증 산출물에 연결한다.
새 파일명은 구현 선택이며 동일 책임의 기존 TC에 넣어도 된다. 파일명이 아니라 기대 행동을 검증한다.
D의 의미 해석 입력은 고정 fixture이며 LLM 의미 판단의 품질은 L에서 별도로 검증한다.
항상 거절하는 구현도 불합격이다. 정상 권한·충분한 정보에서는 유용한 다음 단계가 실제 수행되어야 한다.

## 5. CI·통합·설치와 회복

작업 중에는 영향 suite를 실행하고, 후보에서는 관련 전체 검사와 계약 검사를 수행한다.
정확한 후보/통합 base를 기준으로 필요한 CI·독립 코드/보안 리뷰를 확인한다. 수정 뒤 이전
PASS를 재사용하려면 영향이 없다는 근거가 필요하며 보호 규칙의 필수 재검사를 생략하지 않는다.
live L/O에 필요한 자격을 untrusted PR CI에 주지 않는다.

설치는 검증된 merge SHA의 불변 artifact로 한다. 기존 설치 절차가 지원하는 범위에서
artifact hash·source SHA·실제 실행 경로/버전을 확인하고, 실제 앱의 runtime identity와
대조한 뒤 O를 수행한다. dev server나 패키지 생성만으로 설치/운영 완료라고 하지 않는다.
이 설계는 새 자동 updater나 자동 rollback 시스템을 추가하지 않는다.

설치/운영 실패 시 새 admission을 제한하고 진행 중 실제 효과·자원을 대사한다. 이전 검증
artifact로 되돌리는 것은 기존 설치 절차와 데이터/기록 호환이 확인된 경우에만 수행한다.
구버전이 새 binding/v3 의미를 이해하지 못하면 해당 작업을 보존·보류하며 old runner로 실행하지 않는다.
보호된 외부 효과는 기존 정책과 위임으로 판단한다. 필요한 사람의 결정에는 정확한 원본 링크를 남긴다.

## 6. 종료와 남는 일

R01–R16의 필수 D/L/O, 최종 CI/리뷰/보호 전달/main, 실제 설치와 두 프로젝트 운영·정리가
연결돼야 전체 v1.0.0 완료다. 각 결과는 외부 정본/기존 검증 산출물에 기록하고 이 문서의 상태표를
새 tracker로 사용하지 않는다. native 미지원·실제 보호 전달 미확인·실행 미관측은 명시적으로 남긴다.

목표 범위가 달성되면 새 유지보수나 상시 monitor를 자동 만들지 않는다. 종료하지 못한 책임은
원래 작업의 pending 상태와 해결 주체로 보존한다. 알려진 결함은 요구/재현/영향/다음 행동을
연결하고, 선택 개선은 v1.0.0 완료를 무기한 늘리는 조건으로 바꾸지 않는다.
