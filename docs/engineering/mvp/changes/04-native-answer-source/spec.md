# P04 — 실제 질문·답변·선택 근거를 재발견하는 source

Revision: 4 · 상태: 내부 reader 범위 수용 · 2026-10-21 · 번호는 계획 ID이며 실제 PR 번호가 아니다.
공통 시작·리뷰·전달 기준은 [PR 규약](../README.md)을 따른다. P04 전체 source qualification: NOT RUN.
이 개정은 기존 질문의 내부 읽기 단계를 구체화하며, 구현·설치·기능 활성화를 의미하지 않는다.
이 명세를 유지·개정하며 아래 구현 단계를 여러 PR로 전달할 수 있다. PR마다 해당 단계·요구와 정확한 명세 판본을 고정한다.

## 1. 목적과 범위

한 질문의 답변을 native 원본에서 정확히 읽고, controller restart 뒤 같은 선택과 미전송 의도를
다시 찾는다. R01/R06/R08/R10/R12/R16, [NC §2.1–3](../../contracts/native-capability.md#21-질문과-재개를-위한-원본-연결),
[EX §7](../../contracts/execution.md#7-질문결정다음-wake)이 요구·identity·선택 의미의 정본이다.
대화 요약·`resolved` 알림·auto-accept를 사람의 답변이나 적용 사실로 바꾸지 않는다.

| 여섯 설계 항목 | 이 명세의 결과 |
| --- | --- |
| 목적 | 질문/답변/선택의 출처·현재 판본·귀속을 잃지 않고 후속 P06에 전달 |
| 책임 | provider가 실제 원본, adapter가 bounded normalized source, Codex가 의미 해석 제안 |
| 동작 | 같은 책임의 원본 질문/답변 읽기 → exact 선택 근거 확인 → 지원 native source에서 미전송 의도 재발견 |
| 실패·복구 | 삭제·부분 조회·수정·권한 철회·유실을 구분. 원본 재조회 없이 새 답/질문으로 덮지 않음 |
| 완료 | 정상 원격 답변과 native 의도 write/read/restart의 실제 양성 증거 + 변경/유실 D |
| 범위 | source qualification과 최소 adapter. GitHub 적용 게시·fresh assignment·전달 효과는 P06 이후 |

질문 전달은 CS §3.1에 따라 native 질문을 기본으로 하고 선택지와 추가 설명·주관식 응답을
보존한다. MCP elicitation 성공은 native Q/A의 출처 증거가 아니다. 준비 질문은 fake attempt를
만들지 않는다. 부분 응답·명시적 수정·충돌은 EX §7의 영향 범위대로 처리하고 VF L07 변형으로
평가한다. 실제 원격 UI·응답 귀속·restart는 동일한 source profile에서 검증한다.

## 2. 선행과 provider mapping

P01은 입력 경로 선택에 참고할 진단이며 P04의 지원 증명이 아니다. 기존 허용 task와 유효 work를
재사용할 수 있다. P07의 신규 task 생성이나 P09의 전체 native intake 전환을 먼저 요구하지 않는다.
질문 시험은 별도 범위의 실제 mutation이며 read 시험에 숨기지 않는다. 지원 source가 없으면
해당 capability는 BLOCKED이고 미실행 시험은 NOT RUN으로 남긴다. P06 pure guard·다른 독립 작업은 계속한다.

구현자는 아래 mapping의 빈 부분을 **사실 확인**으로 닫고 해당 source/version을 fixture에 고정한다.
API 이름을 이 표의 제품 의미에서 역으로 만들어내지 않는다.

| 의미 | 구현 전 특정할 source·접근 | 부족하면 |
| --- | --- | --- |
| work↔owning task↔원 질문 | 지원 reader, caller/host, 실제 locator·조회 coverage | 제목·마지막 메시지로 연결하지 않음 |
| answer·응답 권한·수정 관계 | 원격 입력의 실제 항목과 provider가 보장하는 출처/판본 | role=user·clientId·resolved만으로 대체하지 않음 |
| 선택된 답·안전한 의도·대상 공개 참조 | 지원 native source의 읽기/쓰기·변경 검출·재시작 보존 | private DB/blob/journal 또는 일반 `_meta`로 발명하지 않음 |
| normalized source→Hydra | 모델 재서술과 구별되는 지원 transport/caller 경계 | read 가능성만으로 trusted adapter를 켜지 않음 |

스키마는 NC/EX의 원본 의미와 [CP의 DecisionView](../../contracts/control-plane.md)를 참조한다.
P04는 GitHub의 exact intent/result를 native에 복제하지 않는다. P06이 소비할 유효 선택과
native의 미전송 의도 연결까지만 제공한다. **P06 실제 효과 게시를 P04 완료 조건으로 요구하지 않는다.**

### 구현 단계와 후속 인계

| 단계 | 시작 조건·구현 범위 | 완료 증거와 후속 소비 |
| --- | --- | --- |
| 연결 사실 확인 | 이미 허용된 기존 task와 읽기 범위에서 위 mapping을 특정한다. NC §2.2/3에 따라 caller·surface·설치/version·owner·권한·원본 coverage·transport를 대조한다. | 기존 검증 기록에 확인한 필드와 미확인 의미, 한 실제 시험 경로와 허용 효과를 남긴다. 정적 지원·도구 노출만으로 질문 기능을 활성화하지 않는다. |
| 최소 양성 실증 | 특정한 경로에서 실제 원격 응답을 받을 수 있는 범위와 대상이 위임돼 있어야 한다. 필요한 최소 reader/transport adapter만 먼저 구현할 수 있다. | 아래 절차의 원본 read-back·복원·비공개 경계 증거를 같은 profile에 연결한다. 선택 원본을 P06에 제공할 수 있는지 판정하며 P06 업무 효과는 만들지 않는다. |
| adapter와 소비자 연결 | 실증에서 확인한 의미·제약을 고정한 공개-safe fixture와 §4의 독립 oracle을 사용한다. | reader→normalized source→DecisionView와 P06 입력 연결을 검증한다. fixture 통과와 실제 연결 통과를 구별하고, 필요한 양쪽 증거가 있을 때만 해당 profile을 활성화한다. |

이 순서는 실제 활성화의 근거 순서다. 독립 fixture·guard·비활성 adapter 구현은 실증과 병행할 수
있으며, 실증에 필요한 최소 adapter도 관련 D를 통과한 판본만 사용한다.

최소 실증 입력은 **기존 work/owning task 하나, 그 범위의 실제 미결 질문 하나, 원격 응답자,
현재 권한·설계 판본, 미전송 의도를 둘 수 있는 지원 원본**이다. 시험만을 위해 제품 질문을
꾸며내지 않는다. 실제 질문이 없으면 실증은 NOT RUN으로 두거나 별도로 위임된 시험 대상에서
수행한다. 이미 있는 질문을 재사용하며 새 질문이 필요하면 그 생성·전달이 위임된 경우에만 한다.
대기 timeout·호출 한도·취소 후 읽을 원본을 실행 전에 기존 검증 기록에 고정한다.

1. 원격 응답의 정확한 질문 귀속·판본·응답 출처와 선택을 원본에서 읽고, 지원 경로로 미전송 의도를 보존·read-back한다.
2. Hydra controller를 재시작해 memory/cache 없이 같은 질문·선택·미전송 의도를 복원한다. native app/host는 이 시험에서 재시작한 것으로 간주하지 않는다.
3. §4의 수정·삭제·부분 조회·응답 유실 변형은 고정 fixture로 검증한다. 실제 원본 장애 유발은 별도 위임 없이 수행하지 않는다.
4. 실제 원본→Hydra 전달 결과와 P06 입력을 대조한다. 질문 중복 생성·GitHub 결정 게시·후속 실행은 이 실증의 허용 효과가 아니다.

원본과 전달·복원이 모두 기대대로 연결되면 해당 시험은 PASS다. 실행했지만 잘못된 귀속·선택
복원이나 금지 효과를 관측하면 FAIL이다. 접근/권한 부족은 BLOCKED, 지원 명세·실제 응답으로
확인한 미지원은 그 profile의 capability 한계로 기록하고 해당 시험을 BLOCKED로 남긴다.
미실행은 NOT RUN이며 모두를 `unsupported`로 반환하는 구현은 양성 통과가 아니다.
기록은 NC §3/VF의 기존 양식으로 정확한 소스·명세 판본, 실제 입력 범위·관측·판정·남은
책임을 연결한다. 공개 문서에는 private locator·대화·인증 값을 복제하지 않는다.

연결을 못 닫으면 P06의 실제 결정 적용과 원격 질문 통합만 보류한다. pure guard와 독립 TC는
계속한다. 새로운 저장소·credential·runtime이 필요하다는 발견은 이 범위의 불충족과 필요한
결정으로 보고하며 임의 도입하지 않는다. 같은 명세를 개정하고 실증 범위 변경을 기록한다.

## 3. source와 구체 구현 순서

| source 후보 | 책임 |
| --- | --- |
| `hydra_sdlc/native.py`의 provider 경계 | 원본 adapter의 dependency injection·scope 검증; 업무 mutation 호출 금지 |
| `hydra_sdlc/control.py` | 지원된 source의 상태·coverage만 CP projection으로 전달 |
| `hydra_sdlc/mcp.py` | 선택된 경로가 실제 MCP인 경우에만 source transport 연결; generic model JSON 승인 API 금지 |
| `plugins/hydra/skills/sdlc/SKILL.md` | 원본 질문·선택의 역할과 기존 도구 권한을 분명히 함 |
| 예정 `tests/test_native_answer_source.py` | 고정 source fixture와 read/restart/수정 oracle; 내부 adapter 모듈 분리는 구현 재량 |

1. 설치/호출 주체별 source mapping과 미확인 필드를 기록하고 NC 결정표로 실제 시험 경로를 하나 고른다.
2. 요구의 의미와 실제 필드를 대조한다. 접근 제한은 사람에게 필요한 정확한 권한만 남기며 새 계정/서명 체계를 기본으로 추가하지 않는다.
3. 정상 질문·답변·선택·미전송 의도와 변형 fixture를 공개-safe 형태로 작성한다. 원문/ID를 public fixture에 복사하지 않는다.
4. reader와 pure normalized selection을 분리하고 bounded pagination, 현재 revision, source 불일치 거절을 구현한다.
5. 같은 native source의 선택/의도 write-read-restart를 qualified 경로에서 시험한다. 전송 유실은 해당 원본부터 확인한다.
6. 정상 normalized 입력을 P06 guard fixture에 전달할 수 있음을 확인하되 GitHub decision 게시나 실제 다음 배정은 수행하지 않는다.

### 3.1. 첫 source PR: 기존 질문 항목의 내부 읽기

이 PR은 이미 식별된 기존 질문 하나를 읽고 정규화하는 내부 reader를 제공한다. 새 질문이나
답을 만들지 않고, 질문의 의미를 해석하거나 선택하지 않는다. §2의 최소 reader·비활성 adapter
단계이며, §1·§6의 P04 전체 완료 조건을 축소하지 않는다.

선택한 source profile은 지원되는 `thread/items/list`의 고정 task/turn 및 exclusive item
anchor다. 기존 질문 항목과 같은 ID·내용을 반복 조회할 수 있다는 근거는 이 읽기 동작에만
적용한다. 최종 구현의 source/version·실제 호출 범위와 판정은 검증 기록으로 고정하며, 이
문장 자체를 일반 설치의 지원 선언이나 최종 adapter의 운영 통과로 사용하지 않는다.

| 항목 | 이번 PR의 계약 |
| --- | --- |
| 목적 | 정확한 기존 질문 항목을 bounded source read로 읽고 내용 변화·부분 조회를 구별 |
| 책임 | caller가 허용된 source/connection 범위와 실제 locator를 제공; reader가 범위·형태·한도를 검증 |
| 입력 | server 내부에서 주입한 page-reader, 현재 connection/허용 task 범위, exact task/turn/item locator, 선택적인 이전 질문 내용 digest |
| 결과 | source 참조·질문 title/options·관측 범위·변화 여부를 갖는 내부 메모리 관측. 업무·권한 상태가 아님 |
| 실패 | mapping unavailable, bounded inconclusive, source unavailable, content/identity conflict를 구별. 미관측을 질문 없음으로 바꾸지 않음 |
| 전달 종점 | 양성·거절 TC를 통과한 비활성 내부 reader. 기본 transport·공개 도구·설치 설정·CP/P06 연결은 포함하지 않음 |

page-reader와 결과 타입은 Hydra 내부 구현 경계이며 새 Codex API나 플랫폼 보장 필드가 아니다.
모델이 제시한 locator/JSON만으로 trusted source·work ownership을 만들지 않는다. 주입된
scope와 locator가 다르거나 현재 connection binding을 확인할 수 없으면 source 호출 전에
거절한다. locator가 없으면 `mapping_unavailable`로 반환하며 provider·filesystem I/O는 0회다.
로그·DB·제목 검색·task 열거·새 질문으로 locator를 보충하지 않는다. 이 PR은 새로운 locator
저장소나 work↔task map을 만들지 않는다.

#### 고정된 읽기와 한도

1. 같은 허용 owner/task와 turn에서 질문 item Q를 exclusive anchor로 `desc`, `limit=20` 조회한다.
2. 첫 반환 항목을 검증해 가장 가까운 이전 항목 B로 사용한다. 다른 turn, 잘못된/중복 ID,
   Q 자체 반환 등은 거절한다. 첫 항목이 잘못됐다고 뒤 항목을 대신 고르지 않는다.
3. 같은 task/turn의 B를 exclusive anchor로 `asc`, `limit=20` 조회한다. 실제 반환 item ID가
   Q와 같고 `agentMessage`의 질문 형태가 유효한 경우만 질문 관측을 생성한다.
4. 반복 관측을 요청한 경우에만 같은 ASC(B) query를 한 번 더 수행한다. 같은 Q와 canonical
   질문 내용의 일치·변경을 구별한다. 반복 응답에서 Q가 빠지면 조회 불확실성이며 삭제로 단정하지 않는다.

이전 질문 digest가 없으면 최초의 유효 Q를 관측 결과로 반환한다. 이전 digest가 주어졌는데
현재 내용과 다르거나, 반복 조회 사이에 같은 Q의 내용이 바뀌면 `conflict`로 반환한다.
바뀐 내용을 옛 선택·승인에 붙이거나 새로운 기준으로 자동 채택하지 않는다.

각 source 호출 직전에 같은 connection·task 범위와 남은 deadline을 확인한다. 변경된 binding을
자동 채택하거나 새 기대값으로 요청을 다시 만들지 않는다. 모든 경로에서 최대 세 page·page당
20항목·총 60항목이다. 각 raw 응답은 **1 MiB**, 누적 raw 입력은 **3 MiB**, 전체 조회는
**50초**, 개별 대기는 남은 전체 시간 안에서 최대 **30초**다. transport는 응답 전체를
무제한으로 만든 뒤 길이를 재는 방식이 아니라 읽는 경계에서 byte 상한을 집행해야 한다.
현재 source가 이를 보장하지 못하면 해당 adapter의 실제 사용은 활성화하지 않는다.

deadline 소진·취소·잘림·한도 초과·anchor 오류 뒤에는 추가 RPC를 보내지 않는다. cursor
continuation, 전체 turn 조회, 다른 anchor/source/home, cap 증가로 우회하지 않는다. reader가
획득한 요청/stream은 성공·실패·취소 모두에서 제한된 정리 경로로 반환하며 다른 실행의
process·connection은 종료하지 않는다. 기본 transport나 새 background process는 만들지 않는다.

DESC 결과가 비면 `bounded inconclusive`다. 이는 질문이 첫 항목인 경우를 포함할 수 있으며,
질문 없음·API 전체 미지원의 증거가 아니다. Q가 한 ASC page에 없을 때도 같은 제한을 유지한다.
이 경우의 추가 lookup 방식은 이 PR에 숨겨 넣지 않는다.

#### 정규화와 소비 경계

- Q의 실제 item ID, turn과 source connection을 함께 묶는다. 서로 다른 task에 같은 ID가
  있어도 같은 자원으로 취급하지 않는다. `questions`는 하나 이상의 title과 선택적인 string
  options 배열로 검증한다. 추가 설명·title/options를 임의 요약하거나 선택 결과로 변환하지 않는다.
- 질문 원문과 private locator는 허용된 내부 메모리 경계에만 둔다. raw page, reasoning,
  tool arguments/results, 예외 원문, 소비하지 않는 추가 필드는 저장·log·공개 DTO에 넣지 않는다.
  upstream의 무관한 추가 필드는 버릴 수 있으나 필수 envelope·귀속·소비 필드의 손상은 거절한다.
- source revision이 제공·검증되지 않으면 null이다. canonical 질문 digest는 내용 변화 비교에만
  사용하며 provider revision·불변성·권한을 뜻하지 않는다. 같은 ID·내용의 반복 조회는 두
  관측 사이의 일치이며 controller restart나 영속 intent 복구의 근거가 아니다.
  digest 입력은 허용된 title/options만 추출한 질문 배열이다. 배열 순서·문자열·선택 필드의
  없음/null을 보존하고 object key를 정렬한 공백 없는 UTF-8 JSON에 SHA-256을 적용한다.
- 결과는 내부 question-read 관측이다. 기존 `NativeHistoryPageValue`에 필요한 turn
  `reported_status`를 발명하거나 ASC anchored page를 `newest_first`로 바꾸지 않는다.
  새 SourceValue kind, 화면 상태, `WorkView.task_refs` 관계를 이 PR에서 추가하지 않는다.
- source-attempt/work 귀속이 미확인인 상태에서 DecisionView의 question Fact를 채우지 않는다.
  질문 읽기만으로 answer awaiting/received, acceptance accepted, application applied 또는
  Pause/Resume·native 실행 상태를 도출하지 않는다. CP의 기존 미확인 의미를 유지한다.

변경은 내부 reader 모듈, 예정된 `tests/test_native_answer_source.py`, 이 명세와 검증 기록으로
한정한다. `native.py`의 begin/checkpoint/advance 업무 경로를 읽기 우회로로 사용하지 않으며
기존 `control.py`/`mcp.py`의 설정·snapshot·공개 도구에 자동 연결하지 않는다. 내부 모듈 분리는
구현 재량이다. 다음 연결 PR은 지원 locator producer, 실제 transport/caller와 CP/P06 consumer를
각자의 원본·계약으로 검증한다.

### 3.2. 첫 source PR의 결정적 수용 사례

fixture는 공개-safe 합성 값으로 만들고 실제 대화·locator·private 검증 기록을 복사하지 않는다.
source fake는 직렬화된 응답과 실제 요청/byte 경계를 제공한다. 정규화 함수의 성공 값을 mock해
양성 검증을 대체하지 않는다. 아래 사례는 독립 oracle이며 reader의 분기 자체를 정답으로 삼지 않는다.

| ID | 자극 | 독립 oracle |
| --- | --- | --- |
| QREAD-D01 | 유효한 Q, DESC(Q)→ASC(B), 같은 내용의 선택적 반복 | 고정 순서·task/turn·anchor·한도를 지키며 실제 Q title/options와 refs가 반환됨. 반복은 같은 Q/내용으로 판정 |
| QREAD-D02 | locator 없음, 다른 task/provider, connection binding 변경 | mapping unavailable 또는 scope 거절; 누락·초기 불일치는 provider/filesystem I/O 0. 중간 변경 뒤 추가 호출 0 |
| QREAD-D03 | exclusive anchor, 잘못된 첫 predecessor, 중복 ID | anchor 자신을 읽은 것으로 착각하지 않음. 첫 항목을 건너뛰거나 다른 B로 재시도하지 않음 |
| QREAD-D04 | 빈 DESC, Q 없는 ASC, 반복에서 Q 누락 | bounded inconclusive. 질문 없음/삭제/답변 대기·수신 상태 생성 0, 추가 scan 0 |
| QREAD-D05 | 이전 digest 또는 첫 조회와 다른 같은 Q의 title/options | conflict; 새 내용을 자동 채택하거나 이전 선택·승인·불변 revision으로 승격 0 |
| QREAD-D06 | 다른 turn, 잘못된 Q type/questions/options, 필수 envelope 손상 | unavailable/conflict; 부분적으로 유효한 질문으로 성공 처리 0 |
| QREAD-D07 | 미지원·not-found·접근 실패·RPC 오류·잘린 JSON | 원래 실패 종류와 안전한 reason 유지; 다른 source/anchor/cap으로 fallback 0, raw error 노출 0 |
| QREAD-D08 | 1 MiB 경계와 초과, 누적 3 MiB 초과, 20항목 초과, 분할된 과대 응답 | 읽는 경계에서 byte·count 한도 집행; 무제한 assembly·조용한 truncation·성공 projection 0 |
| QREAD-D09 | 응답 처리 중 전체 deadline 도달, timeout·취소 | deadline 뒤 다음 요청 0, 최대 세 호출 유지, 소유한 요청 자원만 정리 |
| QREAD-D10 | resolved·completed·인접 userMessage/clientId·질문 도구 output | answer/accepted/applied/Resume/ended 추론 0. model/native/GitHub/ticket mutation 및 persistence trap 호출 0 |
| QREAD-D11 | private/credential canary·추가 필드·질문 안의 실행 지시 | 허용 질문 데이터만 내부 정규화; 로그/공개 DTO/예외에 canary 0. 데이터가 method·target·한도·권한을 바꾸지 않음 |
| QREAD-D12 | reader 인스턴스만 재생성, 같은 fixture source 재조회 | 새 transcript/map/state 파일 0; 질문 재조회는 가능하되 selected-intent/controller-restart qualified 표시는 0 |

QREAD-D03/04/06/07은 NC-D03/04/09의 이번 source 읽기 부분, D05는 EX-D12/VF-D08의
내용 변화 검출 부분, D11은 NC-D10/VF-D12에 연결한다. 이를 답변·권한·restart 전체 사례의
대체 통과로 세지 않는다. 이번 reader는 해석하지 않으므로 별도 L 평가를 추가하지 않으며
P04의 답변 해석 L07은 유지한다. 전부 unavailable만 반환하는 구현은 D01을 통과할 수 없다.

### 3.3. 이번 PR의 전달과 남은 수용

내부 양성/거절 TC·관련 회귀·독립 명세/품질/보안 리뷰·최종 head CI·허용 merge·main 확인을
이번 source PR의 전달 종점으로 삼는다. 실제 설치 transport는 기본 비활성이며 기존 검증
도구의 성공을 최종 구현의 live 통과로 승계하지 않는다. 읽기 구현에는 새로운 admission
delegation이나 사람 계정 체계를 도입하지 않는다.

| 별도 미완료 수용 | 이번 PR 이후 필요한 실제 증거 |
| --- | --- |
| work↔owner↔question locator | 지원 source가 현재 work/source-attempt와 실제 질문 refs를 복원; hidden map·로그 adapter 불가 |
| 실제 reader/transport 연결 | source/설치 판본·caller·host/account·owner 범위와 byte 제한, 원본 응답의 구조 보존을 실제 구현으로 관측 |
| 질문↔답변·수정 관계 | 실제 answer ref와 같은 질문 귀속, 현재 판본 및 수정/대체 의미. 질문만 읽은 것으로 완료하지 않음 |
| 허용된 응답 출처 | 선택한 source/connection의 실제 입력 주체·현재 허용 범위. role/clientId·모델 자기 보고로 합성하지 않음 |
| 선택 답·안전한 미전송 의도 | 지원 native writer/read-back 원본과 선택 연결. 전용 DB·journal로 대체하지 않음 |
| controller restart | memory/cache 없이 같은 선택·미전송 의도를 재발견. 같은 process의 반복 read와 분리 |
| CP/P06 소비 및 원격 흐름 | source-attempt/work binding·원본 전달·현재 guard를 연결하고 별도 위임된 원격 응답/재개를 관측 |

위 미실행 양성 수용은 NOT RUN으로 유지한다. 구체 source가 미지원임을 확인한 경우만 그
capability 범위에 한정해 BLOCKED로 기록한다. 이번 source PR의 전달은 P04 전체·원격 결정
흐름·v1 완료가 아니며, 다른 독립 guard·구현 작업의 선행 완료 조건도 아니다.

## 4. 결정적 사례와 판단 평가

| 연결 ID | 정상/장애 자극 | 독립 oracle |
| --- | --- | --- |
| NC-D03/06, EX-D12 | 같은 질문의 실제 답변/선택 source | exact source refs·채택 판본·허용 출처가 normalized 결과에 연결; 정상 답을 영구 unknown으로 두면 실패 |
| NC-D03, VF-D05 | turn 종료·중단·자동 해결로 resolved만 발생 | received/accepted/applied 생성 0; native 원본과 수명 알림 분리 |
| NC-D04/09 | partial page·삭제·403·timeout·새 schema | source별 unknown/conflict; 원문 부재를 답변 없음/완료로 바꾸지 않음 |
| EX-D12, VF-D06 | 의도 쓰기 전/후 ACK 유실·controller restart | 같은 source에서 선택/미전송 의도 복원; 중복 질문·새 선택·public write 0 |
| EX-D12, VF-D08 | 답변 수정·선택 교체·work/spec/head/권한 변경 | EX의 수정 시점 계약으로 유효 선택 또는 재평가, 옛 선택의 자동 적용 0 |
| NC-D10, VF-D12 | private 원문·식별자·credential canary | 공개 DTO/log/fixture에는 0; 허용된 의미와 연결은 유지 |

L은 필요한 평가다. Codex가 실제 질문의 답을 현재 요구에 맞게 해석하고 안전한 공개 의도를
제안하는지를 VF L07의 독립 rubric으로 본다. 기술 선택과 사람 판단, 답과 새 목표, 명시적 수정과
모호함을 구분한다. D가 응답 권한을 검증하고 LLM은 권한/허용 효과를 새로 만들지 않는다.

## 5. 검증 명령·실제 시험

| 상태 | 명령/관측 |
| --- | --- |
| 기존 회귀 | `python3 -m unittest discover -s tests -p 'test_native*.py' -v` |
| 기존 회귀 | `python3 -m unittest discover -s tests -p 'test_mcp.py' -v` |
| 예정; 생성·수집 확인 후 | `python3 -m unittest discover -s tests -p 'test_native_answer_source.py' -v` |
| O 예정 | 한 허용 task의 실제 질문→원격 답변→선택/미전송 의도 source read→controller restart→같은 source 재발견 |

명령은 공통 규약의 지정 runner에서 실행한다. 이번 설계에서는 실행하지 않았다. O는 provider
원본과 actual response를 관측하며 모델 요약이나 mocked remote 화면으로 대체하지 않는다.
답변 이후 native turn이 시작됐는지는 따로 기록하고 Hydra 효과의 승인을 뜻하지 않는다.
native app/host restart는 controller restart와 별도 관측으로 남긴다. 지원되지 않으면 그 범위만 명시한다.

## 6. 리뷰·호환·회복·끝조건

reviewer는 source mapping·권한·부분 조회·수정 순서·유실 재조회·private 공개 경계를 검토한다.
기존 legacy progress/decision 의미를 조용히 바꾸지 않는다. 새로운 결정 적용 guard는 P06의
보호된 project version 경로로 전달한다. 지원 부족에서 legacy marker 소비로 fallback하지 않는다.
source-only PR은 mock/adapter 검증 상태로 전달할 수 있지만 실제 Q/A·의도 복원이 없으면
P04 capability는 완료가 아니다. fail-closed만 구현한 것을 정상 질문 흐름의 구현으로 세지 않는다.
실제 양성 source qualification 뒤 P06이 normalized 입력을 사용해 효과 처리하고, 전체 Pause→Resume
왕복은 후속 통합에서 시험한다. 이 순서로 P04↔P06의 완료 의존 순환을 만들지 않는다.
