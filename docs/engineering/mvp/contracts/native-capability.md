# Native 연결: 실행 가능한 경계와 qualification

Revision: 9; design contract, 2026-10-22. Native operating qualification remains separate.
상위: [v1.0.0 spec](../spec.md), [실행 계약](execution.md), [통합 설계](../../../architecture/sdlc.md)

## 목적·책임·범위

NC-R1. Codex가 소유하는 실행·세션·질문·예약을 재사용하면서 Hydra에서 사실에 근거해
관측·조종한다. model worker, scheduler, private transcript 저장소를 새로 만들지 않는다.
현재 native-first 실행 경로를 기본으로 유지한다. CLI는 기존 호환 경로이며 native 실행
실패를 숨기기 위해 조용히 대신 실행하지 않는다.

Codex는 실제 native task와 도구/권한을 제공한다. Hydra는 배정 identity와 관측 계약,
admission과 결과 검증을 담당한다. 이 계약은 공개되지 않은 desktop RPC, 내부 DB 직접 읽기,
로그 scraping을 연결 방법으로 채택하지 않는다.

## 1. 확인된 표면과 입증되지 않은 연결

2026-10-18의 로컬 소스 검토 범위:

- native.py의 배정 반환과 MCP 다섯 도구는 GitHub/host 소유권을 연결한다.
  반환이 native task 생성·시작을 증명하지 않는다.
- control.py는 native turn control을 unsupported, schedule coverage를 unverified로 표현한다.
- native 운영 task가 사용하는 app tool과 standalone Hydra 프로세스가 호출할 수 있는 API는
  서로 다른 표면이다. 한 표면에서의 성공을 다른 표면으로 일반화하지 않는다.
- 현재 등록 설정이 없는 프로젝트에 대해서는 별도 등록/위임을 확인한다. Hydra가 자기 저장소를
  개발한다는 사실도 자기 등록이나 새 credentials를 자동으로 만들지 않는다.

공식 App Server는 thread 및 turn 수명주기를 문서화하지만 그 사실이 기존 desktop task의
안전한 외부 제어·공유 접근을 입증하지는 않는다. 별도로 띄운 서버에 기존 task를 가져오는 방식은
이 계약의 자동 대안이 아니다. 원본 서버/세션 소유권과 지원 연결을 먼저 확인해야 한다.
공식 문서는 App Server 명령과 WebSocket의 실험적 상태·production 지원 제한도 명시한다.
문서화된 연결 후보라는 사실과 제품 운영에 채택할 수 있는지는 별도로 판정한다.
[공식 App Server 문서](https://learn.chatgpt.com/docs/app-server)

프로젝트에 예약된 local 작업은 host와 앱의 가용성을 요구한다. 이를 항상 작동하는 server로
간주하지 않는다. 실제 설치에서 재진입과 그때 사용한 권한·작업 공간을 확인한다.
[공식 Scheduled tasks 문서](https://learn.chatgpt.com/docs/automations?surface=app)

## 2. 최소 capability 계약

이 표는 Hydra 내부 provider 경계다. 현재 존재하는 새 외부 API의 이름이라고 주장하지 않는다.
반환은 지원 provider의 실제 응답과 정확한 대상에 연결한다. 에이전트가 적은 상태 문자열만으로
native 실행·종료나 전체 coverage를 인증하지 않는다.

| Capability | 입력·반환 | 합격/실패의 의미 |
| --- | --- | --- |
| inventory | 등록 project/host 범위 → 실제 task identity·상태·coverage | partial은 전체 0/정리 완료가 아님; native source 전체 조회가 없으면 partial |
| inspect | exact task + provider instance → 현재 turn/state, 관측 시점 | task 부재·권한 부족·접속 실패·미지원 구분 |
| create/reuse | 위임된 goal/work 참조·역할·create_key → task identity/receipt | 기존 task 우선, 유실 시 같은 intent 조회; 추정으로 재생성 금지 |
| continue | exact task + 확인한 turn/head/assignment → 요청 receipt | 보내짐과 실행 시작/완료를 분리; 과거 task의 기존 실행 먼저 확인 |
| interrupt | exact task/turn + 현재 위임 → 요청 receipt 및 이후 종료 관측 | 요청 성공만으로 ended/소유 해제 불가 |
| question | 기존 task·work/attempt 질문 → 전달 상태·실제 answer provenance | 질문 생성/전달/답변/소비를 구분; 새 승인 체계가 아님 |
| schedule | exact owned schedule 조회/변경 → 원본 read-back | 전체 관리 범위와 해당 schedule 변경만 확인; current turn 제어와 별개 |
| archive | 종료·미해결 책임 없음이 확인된 task → 원본 archive 상태 | descendant 부분 실패를 전체 성공으로 취급하지 않음 |

NC-R2. provider source는 target/host/connection identity와 실제 관측을 반환해야 한다.
unknown enum, malformed 응답, timeouts, 연결 identity 교체는 unknown 또는 unsupported를
반환한다. 이전 응답으로 새 연결의 task가 종료됐다고 판단하지 않는다.

NC-R3. private native ID는 외부 public GitHub payload에 넣지 않는다. provider의 원래 task
내용/metadata에서 공개-safe goal/work/attempt 참조를 다시 찾을 수 있어야 한다.
연결 복원은 source의 지원 기능으로 확인한다. 제목 부분 일치만으로 task를 채택하지 않는다.
native 측 정본에서 이 참조를 복원할 수 없으면 mapping_unavailable이며 숨은 로컬 map을 만들지 않는다.

NC-R4. 현재 앱 tool을 native agent가 사용할 수 있다는 것과 외부 provider를 구현할 권한/접근이
있다는 것은 다르다. 직접 호출과 지원되는 native 매개는 모두 후보이며, capability마다 실제
호출 주체·권한·owner·결과 원본을 지정한다. native 매개도 다음 조건을 충족해야 한다.

- Hydra의 요청을 정확한 대상에 전달하고, 접수와 실제 시작·종료를 원본 응답으로 구별한다.
- 실행 중인 작업이 다음 Hydra tool을 호출할 때까지 기다리는 것만으로 중단을 보장하지 않는다.
- 턴 종료 뒤에도 위임된 wake가 가능하고, 매번 사람이 메시지를 옮겨야 하는 흐름에 의존하지 않는다.
- 연결·응답 유실 뒤 지원되는 원본으로 같은 요청·작업을 다시 찾는다. 모델의 자기 보고는
  native 실행·종료 증거를 대신하지 않는다.

native-only 기능은 해당 주체에서 수행하고 control plane에는 실제 관측 근거 또는 unavailable을
보여준다. 지원 경로가 없는 조작은 정확한 native 화면으로 연결할 수 있지만, 이 한계 표시는
전 범위 control plane의 수용 증거가 아니다. 직접 호출 불가만으로 매개 경로까지 배제하지 않는다.

### 2.1. 질문과 재개를 위한 원본 연결

첫 흐름은 [EX §7](execution.md#7-질문결정다음-wake)의 기존 task·질문·project Pause/Resume만
사용한다. 아래 항목은 provider가 제공해야 할 **증거의 의미**이며 실제 API 이름이나 현재 지원
선언이 아니다. 구현 전 caller·지원 API/tool·version·owner·원본 ref와 보존/조회 범위를 실제
선택 경로에 매핑한다. 직접/매개 어느 경로라도 동일 기준을 적용한다.

| 필요한 source 증거 | 연결·보존 조건 | 부족할 때 막는 동작 |
| --- | --- | --- |
| 기존 작업과 owning task | ticket 해제 뒤에도 work/source-attempt/원 phase와 exact task를 지원 원본에서 재발견 | 새 task 자동 생성이나 제목 매칭으로 복원하지 않음 |
| 실제 질문 항목 | 정확한 question/item ref, 채택 판본 구별·변경 탐지, 생성 turn과 작업 귀속, 전달 관측 | 대화 요약만으로 전달 성공·원래 질문 해결을 인증하지 않음 |
| 원격 답변 | 같은 질문의 실제 answer ref/판본·권한 있는 응답 출처·수정/대체 관계 | 메시지 전송 성공·비슷한 텍스트·에이전트 요약을 답변 출처로 대체하지 않음 |
| 결정 적용 의도와 결과 | native의 답변·선택 근거·공개 ref와 GitHub의 exact public intent/context/resolved·후속 attempt를 원본별로 읽어 연결; 미전송 의도도 재발견 가능 | memory만 있을 때 자동 게시/재시작 복구 미지원. public에 native ID/답변 hash를 넣지 않음 |
| 재진입과 후속 실행 | 같은 work의 fresh attempt/step과 실제 task/turn 귀속, 실제 시작/결과 | 메시지 queue·assignment 발행을 실행으로 표시하지 않음 |

원본 연결은 지원되는 기존 대화/item/metadata에 둘 수 있다. 이를 쓰고 다시 읽는 경로도
실증 대상이다. 전용 DB·로그 scraping·로컬 mapping 파일을 대안으로 숨기지 않는다. 수정 가능한
항목은 revision 또는 exact contents의 변화 검출을 제공해야 하며, 삭제·접근 거부·부분 조회는
source unavailable/conflict다. provider가 보장하지 않는 불변성·순서를 adapter가 만들어내지 않는다.

질문 원본을 읽을 수 있어도 실제 원격 응답 귀속이나 결정 적용 연결의 복원이 안 되면 이
흐름 전체는 unverified 또는 해당 capability 미지원이다. 수동으로 원본 질문을 열어 확인하는
경로는 유용한 부분 기능일 수 있지만 자동 연결·복구 수용의 대체가 아니다. 미지원은 해당
provider/설치/권한 범위에 한정하며 플랫폼 전체의 불가능으로 확대하지 않는다.

native caller가 기존 task metadata와 최근 실제 메시지를 읽을 수 있어도 위 다섯 의미 연결을
모두 입증한 것은 아니다. metadata는 조회한 task의 사실, history page는 그 범위에서 반환된
내용의 근거다. 실제 메시지를 읽었다는 사실도 exact 질문·답변·응답자의 권한·적용 intent의
귀속이나 재시작 복원 증거로 확대하지 않는다. 이 연결과 재진입은 별도 qualification 전까지
unverified이며 실행하지 않은 사례는 NOT RUN으로 남긴다.

허용된 기존 대상 하나에서 source 필드와 조회 범위를 먼저 확인한 뒤, 필요한 최소 adapter
구현과 별도 위임 범위에서 원격 답변·재진입·cache 소실 복원을 관측한다. 문서 작성 자체가
새 실제 질문·세션·예약 생성을 허용하지 않는다. 최소 조회는 CP의 metadata/history observation
종류·허용 필드·EvidenceRef 매핑을 먼저 확정한다. private DecisionView의 원본 매핑은 질문·답변·
권한·적용 intent의 별도 증거를 요구하며, 읽을 수 없는 의미를 UI status나 임의 문자열로 채우지 않는다.

### 2.2. Read-only adapter의 원본과 전달 경로

최소 reader는 이미 허용된 exact task만 조회한다. caller, provider/연결 instance, target/owner,
지원 tool/API와 선언된 version, 권한 범위, 입력·응답 schema, 관측 시점과 조회 한계를 고정한다.
task를 활성화하거나 새 turn을 시작하는 호출을 read의 대용으로 사용하지 않는다. source가
제공하지 않는 identity·revision·불변성·조회 완전성을 adapter가 생성하지 않는다.

| 구분 | 계약 |
| --- | --- |
| native caller의 app tool | 해당 caller에서 받은 실제 tool result의 필드·범위만 인정한다. 외부 Hydra process의 호출 가능성을 뜻하지 않는다. |
| 설치 CLI의 protocol/schema | 선언된 설치 version과 capability의 요청·응답만 해석한다. schema 생성은 실제 owner 접근·질문 영속화·응답자 인증의 증거가 아니다. |
| 공식 최신 문서 | 연결 후보와 의미를 확인한다. 다른 version의 필드·pagination method를 현재 설치본의 기능으로 합성하지 않는다. |
| 원본 결과 → Hydra structured transport | 지원된 경로로 정확한 source 응답·대상·필드가 보존되는지를 별도 qualification한다. 모델이 source를 읽었다고 말하거나 JSON을 재작성한 것만으로 trusted observation이 되지 않는다. |

첫 경로의 CP 관측은 `native_task_metadata`와 `native_history_page`로 분리한다. 전자는 exact
task metadata 범위만, 후자는 반환된 한 history page만 설명한다. 실제 메시지·요약·잘린 output을
구분하고, 반환되지 않은 tool result나 원문을 복원한 것으로 취급하지 않는다. 최근 history가
있다는 사실이나 다음 cursor가 없다는 사실만으로 질문·전체 이력·종료 책임의 부재를 판정하지 않는다.
metadata 한 건의 coverage와 history의 부분 coverage를 합쳐 전체 inventory complete로 만들지 않는다.
구체적인 허용 필드·coverage·locator는 [CP source 계약](control-plane.md)을 따른다.

cursor는 같은 provider/target/query 범위에서 반환된 값을 해석하지 않고 그대로 전달한다.
provider가 지원하지 않는 pagination을 다른 API 이름으로 흉내 내거나 raw rollout/DB를 직접
읽어 보충하지 않는다. source ref·opaque locator는 허용된 private 관측에만 두고 raw transcript를
새 정본으로 저장하지 않는다. Codex가 위임 안에서 해석하고 다음 명령을 제안하는 것은 정상
입력이다. Hydra는 현재 source·범위·효과 guard를 검증한다. 모델의 “사람이 승인했다/실행됐다”라는
자기 보고만으로 권한·실행·결정 적용 사실을 만들지 않는다. 원본을 읽은 caller와 Hydra 사이
전달 경로가 미검증이면 원본 읽기
가능성과 structured projection의 신뢰 수준을 따로 표시한다.

App Server의 metadata read, history pagination, 항목 완전성은 version과 실제 저장 방식에
따라 확인한다. `full`이 반환돼도 해당 history에 보존되는 항목의 범위이며 모든 live 질문·응답이
영속화됐다는 보장은 아니다. [공식 App Server 문서](https://learn.chatgpt.com/docs/app-server)
exact Q/A, 응답 주체, 결정 적용 의도와 결과의 read-back은 §2.1의 별도 수용 조건을 유지한다.

### 2.3. 선택한 기본 경로와 별도 capability

첫 구현 경로는 **기존 Codex task가 Hydra MCP를 호출하는 배치**다. Codex가 판단·수행하고
Hydra가 현재 GitHub/host 근거로 배정·checkpoint·검증·전달을 제한하는 기존 구조를 사용한다.
아래의 다른 방향은 이 연결에 자동으로 포함되지 않는다.

| 방향 | 구현에 사용할 경계 | 추가로 필요한 증거 |
| --- | --- | --- |
| Codex task → Hydra MCP → GitHub/host | 기존 다섯 도구와 core guard. 명령 인자는 제안이며 서버가 원본·현재 조건을 확인 | 설치 runtime과 source 판본 일치, 실제 caller context의 보장 범위, 각 mutation의 수용·효과. status 성공만으로 쓰기 capability PASS 아님 |
| native history + GitHub → 연결 projection | supported history의 exact tool-call 참조를 실제 Issue/attempt/head와 대조 | history는 과거 요청의 근거. result/error·현재 owner·위임·step이 없으면 수용/실행/소유 추론 금지 |
| Hydra 도구의 추가 입력 → Codex 입력 창구 → Hydra | 해당 도구에 필요한 MCP elicitation 또는 input-required 응답을 **입력 후보**로 검증 | 원격 표시·사람 응답 출처·정확한 request 연결·Pause 중 응답 보존·재시작 후 원본 복원 |
| Hydra 화면 → 기존 Codex task 관측/중단/wake | 해당 native owner에 도달하는 별도 supported adapter | 직접/매개 경로의 접근·독립 제어·재진입. MCP server 연결만으로 다른 client tool이나 native 목록을 호출할 수 있다고 가정하지 않음 |

지원 history가 반환한 `mcpToolCall.arguments`의 work/attempt/head를 GitHub 원본과 대조하는
방법은 새 task mapping 저장소 없이 과거 참조를 재발견하는 후보다. 호출 status=completed와
서버 결과·business acceptance는 다르다. result/error가 없으면 결과 성공으로 보완하지 않는다.
부분 조회나 과거 참조 하나로 현재 작업의 owning task를 자동 채택하지 않는다.

신뢰는 필드 이름이 아니라 source와 실제 호출 경계에서 온다. SDK가 tool 인자와 별도로 주입한
request context는 모델이 넣은 `task_id`와 구별하지만, generic request/session ID가 Codex
thread/turn·사람의 identity를 보증하는지는 별도 확인한다. `_meta`를 지원한다는 이유로 임의
key를 인증된 플랫폼 필드로 채택하지 않는다. 별도 사람 계정 DB·서명 체계를 기본 요구로
추가하지 않으며, 플랫폼의 검증된 scoped authority 근거가 같은 보장을 제공하면 사용할 수 있다.

일반 요구사항·taste·선택 질문은 Codex native 질문이 기본이다. 객관식과 주관식, 자유 설명의
모드/원격 UI 지원을 개별 확인한다. native 질문의 Q/A 원본 연결과 MCP 입력 왕복은 서로 다른
capability이며 한쪽 성공을 다른 쪽의 증거로 사용하지 않는다. MCP elicitation은 도구 호출의
추가 입력에 사용하고 동일 결정을 양쪽에서 중복 생성하지 않는다. P01 form probe는 native
질문 도구의 지원/인간 응답/권한을 판정하지 않는다.

MCP elicitation은 모델이 답을 재작성해 tool argument로 보내는 경로와 구별할 수 있는 후보다.
`accept/content`는 해당 입력 수신이며 자동으로 project Resume·scope 확대·보호 승인이 되지
않는다. decline/cancel/timeout은 제품 결정 완료가 아니다. App Server의 request schema에
thread/turn 정보가 있어도 그것이 외부 MCP server에 그대로 전달된다고 가정하지 않는다.
server 응답을 받은 client가 자동으로 처리할 수도 있으므로 `accept` 자체를 사람 입력의
증거로 쓰지 않는다. back-channel request와 input-required 응답 후 continuation은 별도 경로다.
협상 protocol·지원 client driver·요청 귀속에 맞는 하나를 선택하고, 실패 후 다른 경로로 새
질문을 자동 발행하지 않는다. back-channel이 없다는 사실만으로 모든 입력 경로를 미지원으로
판정하지도 않는다. form request의 의미는 [공식 MCP elicitation](https://learn.chatgpt.com/docs/app-server#mcp-server-elicitation-requests)을
따른다. input-required는 해당 SDK/protocol과 실제 client 지원을 별도로 확인하는 후보다.
실제 client capability·자동 처리와 사람 입력의 구별·응답의 durable 원본이
확인되기 전에는 질문/복원 capability를 활성화하지 않는다. input-required의 `request_state`는
해당 요청에 묶인 opaque continuation 자료이며 질문 원본·영속 checkpoint가 아니다. 만료·서버
재시작·binding 변경으로 사용할 수 없으면 미해결 입력을 유지하고 새 질문/효과로 우회하지 않는다.
이를 public 기록·raw log·별도 blob/journal에 복사하지 않는다. 동일 요청 재호출도 모든 effect
직전 현재 guard를 거쳐야 한다. 새 요청을 만든 사실은 기존 대화의 답을 복원한 증거가 아니다.
일반 natural-language 질문을 전부 form으로 바꾸는 제품 결정도 아니다.

### 2.4. 다음 qualification 단위: 설치본과 호출 문맥 읽기

이 변경은 기존 `hydra_status({})`를 읽는 주체가 **지금 요청의 transport 진단**을 확인하게 한다.
task owner 인증·질문 생성·결정 적용은 후속 capability다. 문맥이 없는 호출도 기존 GitHub/host
status를 읽을 수 있어야 한다. SDK가 주입한 문맥과 모델 인자를 분리하는 목적이며 새 인증 체계가 아니다.

| 설계 항목 | 계약 |
| --- | --- |
| 목적 | 어떤 입력 경로를 실증할지 근거로 선택하고, status 도달을 native 제어 성공으로 오해하지 않음 |
| 책임 | MCP wrapper가 SDK 문맥을 추출하고 pure projection이 아래 닫힌 결과를 생성. controller는 기존 status 책임 유지 |
| 입력·동작 | 현재 요청의 SDK Context와 startup SDK profile만 읽음. network·native inventory·질문 호출·파일 재탐색 없음 |
| 실패·복구 | 읽을 수 없는 진단 필드만 null/unknown. 다음 명시적 status가 fresh 문맥으로 다시 읽음; 자동 retry·마지막 정상 문맥 재사용 없음 |
| 완료 | §5의 독립 기대값, 실제 SDK 등록/호출 fixture, 기존 status 소비 경로의 호환 검증. 설치된 client 관측은 별도 O |
| 범위 | W1a/W3의 좁은 진단 변경. CP v2/v3, EX의 판단/효과 gate, WR의 위임/기록 의미는 바꾸지 않음 |

#### 2.4.1. 출력과 source별 의미

결과는 기존 MCP status의 최상위 `native_context` 하나에 둔다. 아래 일곱 key는 모두 필수이며
추가 key는 없다. null과 enum은 JSON 값으로 직렬화한다. task/ref·request ID·시간·원문·오류
문자열은 넣지 않는다. 이는 CP Observation이나 실행 Capability가 아닌 요청별 진단이다.

```text
NativeContextProbeV1 = {
  schema_version: 1,
  protocol_version: string | null,
  request_channel: available | unavailable | unknown,
  form_elicitation: declared | not_declared | unknown,
  input_required_sdk: present | absent | unknown,
  input_required_client: unverified,
  caller_task_binding: unverified
}
```

| 필드 | 읽는 source와 정상값 | 부재·잘못된 값의 결과 |
| --- | --- | --- |
| `schema_version` | Hydra 상수 정수 `1`; boolean 불가 | consumer는 다른 판본/누락을 이 진단의 미지원으로 처리 |
| `protocol_version` | 주입 Context의 `protocol_version`. profile이 해석하는 exact string만 반환; 최대 64자 | null. 입력 문자열을 자르거나 날짜 대소로 지원 판정하지 않음 |
| `request_channel` | 같은 Context의 `session.can_send_request`가 정확한 bool이면 true→available, false→unavailable | unknown. `0`, `1`, 문자열, missing/예외를 bool로 coercion하지 않음 |
| `form_elicitation` | 같은 Context의 typed `client_capabilities.elicitation.form`에 유효한 form 선언이 있으면 declared | 아래 선언 판정 규칙 적용; client 구현/사람 응답 성공으로 승격 금지 |
| `input_required_sdk` | startup에 확인한 고정 SDK profile의 정적 지원. 해당 API/type이 확인되면 present | 미확인 profile·불일치·손상은 unknown. absent는 검토한 profile이 기능 부재를 명시한 경우만 가능 |
| `input_required_client` | 항상 unverified | 선언·protocol·SDK 존재·기존 tool 성공으로 바꾸지 않음 |
| `caller_task_binding` | 항상 unverified | `_meta`, tool args, request/session ID, clientInfo로 바꾸지 않음 |

첫 SDK profile은 저장소가 고정한 `mcp==2.3.0`의 `mcp.server.mcpserver.Context`,
`mcp_types.ClientCapabilities`/elicitation types 및 `InputRequiredResult`에 대한 정적 계약이다.
해석하는 protocol 집합은 `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`,
`2026-07-28`이다. 목록에 없는 값은 null이고 그 요청의 channel/form 해석도 unknown이다.
새 SDK/protocol은 profile·독립 fixture를 검토한 뒤 추가한다. 설정이나 모델 인자로 profile을 고르지 않는다.

form은 `2025-06-18`, `2025-11-25`, `2026-07-28`의 typed 선언만 해석한다. capabilities 전체가
없거나 malformed이면 unknown이다. 유효한 capabilities에 elicitation이 없으면 not_declared다.
유효한 form 객체가 있으면 declared이며, 빈 form 객체도 참/거짓 평가 없이 존재로 판정한다.
후자의 두 protocol에서 유효한 URL-only 선언은 not_declared다. elicitation 객체는 있으나
form/url이 모두 없는 legacy/모호한 선언은 unknown으로 둔다. 이를 form 지원 또는 부재로
추정하지 않는다. 더 오래된 두 protocol의 form 해석은 unknown이다. 다른 capability의 내용은 읽지 않는다.

#### 2.4.2. 주입·추출·projection 알고리즘

1. server 생성 시 기존 runtime snapshot과 고정 SDK profile을 한 번 준비한다. optional MCP
   import는 기존 MCP 실행 경계 안에 유지하여 CLI의 SDK 없는 사용을 깨지 않는다. 등록할 Context
   annotation은 SDK가 실제 타입으로 해석할 수 있어야 하며 모델 입력 schema에 드러나면 실패다.
2. `hydra_status({})`는 SDK가 주입한 Context만 사용한다. controller/model args에서 Context를
   복원하거나 임의 dict를 Context로 감싸지 않는다. 같은 함수의 내부 직접 호출에 문맥이 없으면
   정상 fallback이며 protocol=null, channel/form=unknown이다. SDK 정적 지원은 독립 판정한다.
3. 해당 SDK profile의 실제 Context/필드 형태를 확인하고 protocol을 먼저 읽는다. 알려진 값이면
   channel과 form을 각각 최대 한 번 추출한다. 해석용 입력은 고정 개수의 scalar/enum뿐이며
   raw Context·params·`_meta`·headers·clientInfo·input_responses·request_state를 복제하지 않는다.
4. 추출기는 필드별 유효/부재/실패만 pure projection에 전달한다. projection은 위 표의 literal
   결과를 만들고 caller/client 두 unverified를 고정한다. 한 필드 실패가 독립적으로 확인한 다른
   필드를 지우지 않는다. 다만 Context/profile 또는 protocol 자체가 부적합하면 해당 문맥 해석
   전체를 닫는다. `2026-07-28`에서 channel=true가 보이면 profile 불일치이므로 channel=unknown이며
   back-channel 경로를 선택하지 않는다. capability 선언은 별도로 유지한다.
5. 기존 status 결과에 진단만 더한다. 기존 controller 오류를 `projects=[]` 성공으로 삼키지 않고,
   기존 `controls` 오류 처리와 runtime을 변경하지 않는다. 진단 추출 실패는 기존 읽기 성공을
   실패로 바꾸지 않는다. 취소·프로세스 종료는 삼키지 않고 기존 수명주기로 전달한다.
6. 호출마다 새 projection을 만들고 요청 Context를 보관하지 않는다. 같은 입력은 같은 진단을
   낸다. 다음 요청이 client/capability를 달리하면 그 요청만 반영하며 이전 값·응답·session을 섞지 않는다.

SDK 속성 접근의 AttributeError/TypeError/ValueError/RuntimeError는 해당 필드 부재로 변환한다.
그 밖의 일반 Exception은 **진단 추출 구간에 한해** protocol/channel/form을 기본값으로 만들고
독립적으로 확인한 SDK 정적 지원만 보존한다. CancelledError/KeyboardInterrupt/SystemExit는
삼키지 않는다. 직렬화한 예외·`repr(context)`·traceback에 source 값을 담지 않는다. 프로그래밍
결함은 독립 TC에서 실패로 탐지하며, 운영 diagnostic에는 고정된 비식별 error category만
허용한다. 새 reason 필드나 원문 log는 만들지 않는다. 전체 status/controller 예외를 이
fallback으로 감싸거나 취소를 unknown 성공으로 바꾸는 구현은 계약 위반이다.

#### 2.4.3. Runtime identity와 호환

같은 tool 이름이나 package version만으로 검토한 소스가 실행 중이라고 보지 않는다. 현재 source,
설치 metadata, module/code observation, status runtime을 구분한다. 기존 `RuntimeIdentityV1`의
startup snapshot을 그대로 반환하며 status마다 source/설정/SDK를 다시 탐색하지 않는다. 이
identity는 package source의 관측이며 loaded byte attestation이나 dependency hash가 아니다.

SDK profile은 같은 server 생성에서 선택한 실제 SDK 배포 version과 import된 API 형태에 묶는다.
동일 version 문자열만 있고 필요한 타입/필드가 없으면 unknown이다. 버전 확인 실패도 absent가
아니다. 정상 profile은 Context 부재에도 SDK 정적 지원만 표시할 수 있다. 현재 profile에서
absent를 발생시키는 판정은 없다. runtime identity가 후보 baseline과 다르거나 불완전하면 소비자는
진단을 그 후보의 qualification PASS로 사용하지 않는다. 이를 고치려고 runtime 값을 덮어쓰지 않는다.

| 기존 경계 | 호환 계약 |
| --- | --- |
| A reader의 MCP 다섯 도구 | 이름·모델 입력 schema·mutation semantics 유지. status의 모델 인자는 여전히 빈 object |
| MCP status | 기존 projects/runtime/선택적 controls를 동일하게 보존하고 native_context만 추가. direct caller도 새 키를 빼면 기존 결과와 같음 |
| 이전 설치본 | native_context가 없으면 probe unavailable. 새 default를 합성해 probe 실행/SDK 지원으로 표시하지 않음 |
| probe consumer | 일곱 key/타입/enum을 엄격히 확인. 알 수 없는 판본·key·손상은 이 진단만 사용 불가; 유효한 기존 status를 보존 |
| CLI·CP/Rust/TS | 기존 strict v2/v3 wire에 native_context를 넣지 않음. 이 변경만으로 CP native capability나 제어 버튼을 활성화하지 않음 |

SDK profile·runtime 불일치를 확인하는 것은 업데이트·재설치·서비스 재시작의 자동 권한이 아니다.
별도 버전 DB나 identity journal을 만들지 않는다. 일반 native task inventory/control bridge로
확장하거나 기존 `project_threads` 설정을 인증된 현재 caller로 채택하지 않는다.
다섯 도구 불변은 이 A reader packet의 범위다. 후속 좁은 continuation packet의 versioned
command 추가·gate는 [CP 명령 계약](control-plane.md)과 [EX 실행 계약](execution.md)이 소유한다.
A의 tool-count TC를 그 추가를 금지하는 전역 규칙으로 쓰거나, A가 해당 명령 지원을 광고하지 않는다.

#### 2.4.4. 비밀·metadata 비간섭과 소비 경계

projection이 읽는 것은 정해진 typed 속성뿐이다. raw metadata의 key 목록·크기·해시도 결과에
넣지 않는다. protocol은 허용된 literal만 반환하고 임의 문자열·예외는 echo하지 않는다. 알려지지
않은 key의 값은 깊이 순회·JSON dump·문자열 변환하지 않는다. 거대한 무관 metadata를 받은
경우에도 Hydra 추출 비용은 고정된 접근 수에 머물러야 한다. SDK transport가 payload를 파싱한
비용/한도와 Hydra projection의 비간섭은 서로 다른 검사다.

동일한 허용 필드에 secret canary·위조 task ID·`human_approved`·중첩 대형 blob을 **무관 필드에만**
추가/교체하면 진단은 byte-equivalent여야 한다. stdout에는 SDK protocol 응답만 있어야 하고
stderr/진단에도 canary가 없어야 한다. 본문·ID·cursor·request_state·credential을 저장하거나
해시로 바꾸어 밖으로 내보내지 않는다. 사람이 입력해 보이는 text도 caller 권한을 바꾸지 않는다.

최초 consumer는 MCP tool 결과를 읽는 native caller와 qualification 판정이다. source reader→
pure projection→실제 SDK status serialization→consumer의 key/enum 확인을 같은 D 통합에서
잇는다. `structuredContent`와 text JSON 중 현재 SDK가 제공한 경로를 읽되 양쪽이 있으면 같은
object인지 검사한다. 응답을 모델이 요약한 문장은 이 진단의 재생성 원본이 아니다. Mac 화면의
metadata/history observation으로 연결하는 것은 CP가 소유하는 별도 변경이다.

#### 2.4.5. 질문 시험으로 넘어가는 결정표

| 관측 | 다음 조치 | 아직 허용되지 않는 추론/효과 |
| --- | --- | --- |
| runtime/profile 불일치 또는 probe 없음 | 실제 판본·경계부터 확인; 읽기 결과와 한계 보존 | 후보 PASS, 자동 설치/재시작 |
| Context/protocol 미확인 | 해당 client의 지원 문맥을 읽는 경로 확인; 기존 status 사용 유지 | 모델 task ID로 대체, 질문 경로 임의 선택 |
| 해석한 legacy protocol + channel available + form declared | 해당 version의 back-channel form 시험안을 구체화 | client가 사람에게 보여줌·원격 답변·재시작 성공 |
| channel unavailable + SDK input-required present | 해당 client의 input-required driver 지원을 별도로 확인 | 질문 기능 전체 unsupported, ctx.elicit 자동 fallback |
| modern protocol + SDK present + driver 지원 근거 | 같은 요청의 input-required/retry 시험안 구체화 | continuation state를 영속 질문 원본으로 채택 |
| form not_declared/unknown 또는 driver 미확인 | 해당 경로만 보류; 지원 native 질문 경로 등 다른 후보의 근거 조사 | 실패 직후 다른 방식으로 질문 중복 생성 |

시험안에는 exact 대상·호출 주체·scope, 질문/응답을 관측할 지원 source, timeout·취소·응답 유실
후 대사 방법을 정한다. 원격 표시·응답 출처·Pause 보존·restart 복원은 **실제 시험의 판정 대상**이며
probe 성공의 자동 후속 실행이 아니다. 영속 복원이 아직 증명되지 않았다는 이유로 안전한 범위의
시험 설계까지 막지 않되, §2.1/EX의 원본 연결이 통과하기 전 업무의 자동 결정 bridge를 열지 않는다.

#### 2.4.6. 미확정 사항의 책임

| 남은 항목 | 종류·해결 방식 | 독립적으로 진행할 범위 |
| --- | --- | --- |
| 실제 client protocol/capabilities와 caller 필드 보장 | 사실 확인: 검토한 reader의 한 번의 무변경 status 관측. unverified는 정상 결과 | pure projection·SDK boundary·호환 TC |
| legacy의 모호한 선언, input-required driver·원격 UI·Q/A 원본·restart | 사실 확인: version별 지원 근거와 별도 좁은 O; 다른 사례의 성공을 전이하지 않음 | 기존 상태 읽기, Pause/Resume guard·EX 결정 계약 |
| 내부 모듈/class/function·테스트 fake 구성 | 구현 재량: 고정된 source/알고리즘/오라클을 만족. 새 framework/DB/daemon 불필요 | 같은 리뷰 가능한 변경 안에서 선택 |
| 기존 위임 밖의 자격·비용·대상·public/production 효과 | 사람 결정: 정확한 추가 범위와 영향만 별도 판단 | 현 위임 안의 설계·TC·무변경 읽기 |

전체 v1.0.0 control tower 수용 기준은 그대로다. probe 하나의 unverified 결과 때문에 독립 작업을
멈추지 않고, 반대로 probe 성공을 native 질문/중단/wake의 성공으로 바꾸지 않는다.

## 3. W1 사전 조사와 실제 qualification

### 기능별 지원 판정의 최소 기록

각 capability는 기존 검증 기록에서 caller, 제품 surface, 설치 version, provider/schema,
실제 owner/host 접근 범위, 위임, 원본 coverage, 증거 수준, 빠진 증거, 다음 bounded 시험을
연결한다. 새 capability DB나 public private-ID 목록을 만들지 않는다. 증거 수준은 문서상
지원·로컬 노출·fixture 검증·실제 연결 검증·해당 범위 미지원·미확인으로 구분한다. 알려진
미지원과 아직 시험하지 않은 것을 섞지 않는다. 사설 locator는 원래 허용된 증거 위치에만 둔다.

| 표면 | 확인해야 할 기능 | 활성화 전 필요한 증거 |
| --- | --- | --- |
| 현재 native app caller | 기존 task/history, 질문·메시지·제어의 개별 도구 조건 | 실제 원본→Hydra 전달, 인간 답변 귀속, 책임 참조의 재시작 복원 |
| 설치 App Server/SDK | 해당 설치 schema의 read/turn/Goal/control | 기존 owner에 대한 지원된 접근. 새 서버/new thread 성공은 대체 증거가 아님 |
| 같은 대화 예약 | 같은 책임으로 turn 뒤 재진입 | 실제 wake·중복 수렴·종료 read-back. tool 노출만으로 available 금지 |
| GitHub 사건 예약 | 지원 surface·계정/조직 조건 | 현재 공식 문서는 web/mobile만 지원. Desktop/CLI/IDE 이벤트 wake를 지원으로 합성하지 않음 |
| 원격 창구 | 동일 작업·권한·질문 응답 | 연결 host와 실행 위치 확인. Work Cloud local access는 같은 local owner의 증거가 아님 |
| 발견 제안 | 원래 native 기록의 제안·근거·전달 결과·거절/재검토 조건 | 최초 미전송/전송 확인/unknown 구분, 실제 전달 read-back와 restart 중복 억제. 일반 wake 성공과 별도 |

2026-10-19 [App Server](https://learn.chatgpt.com/docs/app-server),
[예약](https://learn.chatgpt.com/docs/automations),
[원격 연결](https://learn.chatgpt.com/docs/remote-connections)의 문서 조사 기준이다. 실제 배치의
version/schema와 다시 대조하며 문서 갱신 날짜로 설치 기능을 추정하지 않는다.

P04/P07/P08의 live 경로를 열기 전에 각각 필요한 다음 질문을 닫는다: 기존 owner 원본을 읽는
caller는 누구인가, 원래 tool/provider 결과가 어떤 지원 transport로 Hydra에 도달하는가,
work↔task/question 연결을 어디서 재발견하는가, turn 종료 뒤 누가 다시 시작하는가, 실제 owned
실행의 중단/종료를 어떻게 확인하는가. 필수 답이 없으면 해당 경로는 구현 인계에서도 미확인이다.
독립 guard/fixture·다른 source까지 보류하지 않는다. 이 조사로 새 runtime·credential·저장소를 채택하지 않는다.

adapter는 qualified operation만 허용한다. 외부 텍스트의 method 이름으로 provider RPC를
선택하는 passthrough를 두지 않는다. 관측을 resume/exec로, archive를 영구 delete로 대체하지
않는다. App Server의 sandbox 밖 shell/process 기능은 이 lifecycle 경로에 포함하지 않는다.
hook은 관측 보조로만 평가하며 actual effect guard를 대신하지 않는다. 지원 surface·실패 의미가
다르고 callback 오류가 tool 실행을 막지 않을 수 있으므로 hook 부재/timeout은 권한을 만들지 않는다.
실제 실패 의미는 [공식 hook 경계](https://learn.chatgpt.com/docs/enterprise/agent-security#hooks-in-local-computer-access-with-work-cloud)와
해당 설치 surface에서 대조한다. 다른 계정/표면에 같은 동작을 추정하지 않는다.

### W1a 사전 조사: 호출 경로를 좁히기

실행 전에 지원 명세·설치 버전·현재 도구 노출을 비교한다. 연결 없이 생성한 schema는
요청/응답 형태의 근거다. 실제 task 접근, desktop 버전, 권한 또는 실행 성공을 증명하지 않는다.

| 후보 경로 | 확인할 연결 | 아직 증명하지 못한 것 |
| --- | --- | --- |
| native task → Hydra 도구 | 배정·guard·결과 제출의 주체와 경계 | Hydra에서 native task로 보내는 반대 방향 요청 |
| Hydra → 지원되는 native 매개 → 실제 owner | 요청 수신·도구 호출·원본 결과 회수 | 매개 주체의 가용성, 실행 중 중단, 턴 종료 후 wake와 복원 |
| Hydra → 지원 API → 실제 owner | 버전별 protocol과 접근·권한·owner 연결 | 기존 desktop task에 대한 실제 접근·공동 사용 범위 |

정적 조사 결과는 후보·확인한 명세·단절 지점·다음 최소 실증으로 끝낸다. API가 명세에
없다는 관측을 플랫폼 전체의 미지원으로 확대하지 않는다. 이 조사만으로 W1a의 adapter/TC
완료나 W1b의 capability PASS를 기록하지 않는다.

다음 실증은 선택한 경로에서 한 개의 위임된 대상에 대한 최소 조회부터 시작한다. provider,
호출 주체, 권한, target/owner, 조회 결과의 원본과 판정 조건을 먼저 특정한다. 조회로 연결을
입증한 뒤 아래 실행 단계로 넓힌다. 새 서버에서 새 task가 성공해도 기존 owner 연결의 증거로
사용하지 않는다.

### W1b: 실제 연결을 단계별로 관측

각 사례는 해당 환경·대상·위임 범위의 실제 증거로 판정하며 한 단계의 성공을 전체 완료로
확대하지 않는다. 원래 작업·예약·자원을 보존하고 미실행 사례는 NOT RUN으로 남긴다.

**최소 read protocol**은 허용된 기존 task 하나에서 시작한다. §2.2의 caller·지원 경로·version·
target/owner·권한을 먼저 고정하고 metadata 및 제한된 최근 history를 조회한다. 같은 대상과
입력으로 한 번 더 읽어 총 두 관측의 identity·조회 범위·변화/잘림을 대조한다. 내용이 변했다면
변경 사실을 보존하며 이를 다른 task 또는 immutable snapshot으로 임의 해석하지 않는다.
반환된 opaque cursor가 있으면 같은 조회 경로로 과거 한 page만 추가한다. cursor가 없거나
지원되지 않으면 pagination 사례는 미관측/미지원 범위로 남기고 cursor를 만들지 않는다.
이 단계의 native mutation은 0회다. task/turn 생성·resume·메시지 전송·질문 생성·interrupt·
Pause/Resume·예약 변경·archive를 함께 시험하지 않는다. 원본 읽기와 Hydra까지의 structured
transport 각각의 결과·한계를 기록한다.

두 번의 조회와 한 page의 성공은 허용된 task의 제한된 read 증거다. negative lookup, 권한
실패, 전체 coverage, 질문/답변 연결, 재진입, restart 복원은 아래 별도 사례로 검증한다.

1. **표면 확인:** 설치 revision, 실제 provider/연결, 가능한 read/write capability, 권한,
   task/project/schedule 범위를 기록한다. 값만 켜서 supported로 만들지 않는다.
2. **조회:** 알려진 test task와 존재하지 않는 ID를 각각 조회한다. native source에서
   host/project와 task identity가 맞는지 확인한다. 페이지 누락/권한 실패도 관측한다.
3. **작은 실행:** scope가 정해진 test work를 begin하고 원래 task에서 한 개 assignment를
   수행한다. 발행 receipt와 실제 시작·결과를 각각 기록한다.
4. **재진입:** 한 결과 뒤 턴을 끝내고 지원되는 위임된 재진입으로 같은 목표의 다음 결과를
   진행한다. 계속 같은 턴에 있었던 실행을 재진입 성공으로 세지 않는다.
5. **중단:** test task를 실행 중 중단하고 실제 종료·자식 process·owned edits를 확인한다.
   지원되지 않으면 정확히 unsupported로 기록하며 임의 다른 실행기로 전환하지 않는다.
6. **재시작:** Hydra를 재시작해 GitHub와 native/provider에서 task/assignment를 복원한다.
   host/app 재시작은 별도 단계로 기록하며 서비스 재시작과 혼동하지 않는다.
7. **유실/중복:** 통제된 test 경계에서 응답 유실 후 lookup을 검증한다. 정상 대상에 반복
   create/interrupt를 보내는 시험으로 production 자원을 건드리지 않는다.
8. **정리:** 정해진 종료 조건 뒤 해당 test task/schedule/workspace만 정리하고 read-back한다.
   모르는 기존 schedule이나 active task는 보존한다.

공개 receipt에는 환경 alias·source revision·capability·scope·시나리오·결과·한계·증거 종류만
담는다. raw transcript·host path·task ID·credentials는 기존 허용된 private 증거 위치에 남긴다.
private 증거의 위치도 public 문서에 복사하지 않는다.

## 4. 결과에 따른 진행

| 결과 | 후속 작업 |
| --- | --- |
| 요구 capability가 정확한 범위에서 관측됨 | 같은 provider/권한/버전을 고정하고 실행·projection 연결 구현 |
| 직접 호출은 불가, native task에서는 가능 | 지원되는 native 매개가 NC-R4를 충족하는지 평가; 미입증/미충족 capability만 표시 |
| 명세만 확인하거나 실제 연결을 관측하지 못함 | unverified 유지; 가능한 최소 실증을 특정. 전체 플랫폼 unsupported 또는 PASS로 바꾸지 않음 |
| 시작/종료·재진입·복원이 불가 | 독립적인 Issue/TC/projection 작업은 계속; 전체 운영 수용은 BLOCKED |
| 다른 공식 연결이 실제 가능 | 기존 ownership/보안/데이터/설치 계약 안인지 검토; 경계 변경이면 구체적 대안과 영향 제시 |
| 자격·새 비용·외부 접근 필요 | 기존 자격을 몰래 재사용/복사하지 않음; 정확한 필요만 사용자 판단 대상으로 올림 |

기능을 확인하지 못했다는 이유만으로 mock 성공을 통과시키거나 요구사항을 축소하지 않는다.
동시에 하나의 미지원 조작 때문에 읽기·안전한 차단·독립 작업까지 모두 사용할 수 없게 만들지 않는다.

## 5. 결정적 검증

계획 파일: `tests/test_native_capabilities.py`. 현재 `tests/test_mcp.py`의 SDK 등록/직렬화·
stdio fixture와 `tests/test_runtime_identity.py`의 startup identity 검증을 필요한 범위에서 확장한다.
실제 native와 관계없는 D이며 아래 추가 사례·fixture는 모두 구현/실행 전이다.

| ID | 입력/사건 | 기대 결과 |
| --- | --- | --- |
| NC-D01 | endpoint는 존재하지만 일부 capability 없음 | 개별 unsupported, 다른 읽기 기능 보존 |
| NC-D02 | 이전 provider instance의 늦은 ended 응답 | 새 연결 상태·ticket 변경 없음 |
| NC-D03 | 발행 receipt·model self-report·resolved 알림 또는 자동 해결만 존재 | started/ended·사람의 답변/승인·결정 적용 모두 미입증; native source tool result와 모델 재서술의 신뢰 수준을 합치지 않음 |
| NC-D04 | metadata 1건 성공, history partial/summary/truncated/hasMore 또는 lookup 403/timeout | metadata 범위와 history coverage를 분리; cursor 부재도 empty inventory·질문 none·전체 complete로 변환하지 않음 |
| NC-D05 | create 응답 유실 | create_key lookup, unknown이면 재생성 없음 |
| NC-D06 | 제목 동일하나 project/work/attempt 다름, 또는 exact task metadata·실제 최근 메시지만 확인 | 다른 task 채택 거절; 올바른 task 조회도 exact 질문/답변·응답자 권한·적용 intent 복원으로 승격하지 않음 |
| NC-D07 | interrupt 요청 접수, 종료 이벤트 없음 | cleanup/ownership release 없음 |
| NC-D08 | archive 성공, descendant 미확인 | partial 유지, 전체 정리 완료 아님 |
| NC-D09 | 새 native enum/버전, 설치/source/runtime 불일치, 최신 문서에만 있는 field/method, 다른 target/query의 cursor | 선언된 경로/version만 해석; unknown/unsupported를 known으로 coercion하거나 API를 합성하지 않음. 유효한 opaque cursor만 같은 scope로 전달 |
| NC-D10 | private source result에서 structured observation·public receipt 생성 | CP allowlist로 metadata/history 분리; private ID/path/transcript/credential/cursor의 public 출력 없음. 모델 재작성만으로 trusted observation·revision 생성 없음 |

NC-D03/06에는 다음 세 입력을 구분하는 oracle을 추가한다. (a) Codex의 위임 내 typed 명령은
정상 guard 뒤 처리 가능, (b) 같은 명령 안에 위조한 `human_approved`/`task_id`는 authority
근거가 아님, (c) supported client의 실제 question response도 request/source/scope를 확인한
뒤에만 수신으로 인정한다. 모델 입력 전면 거절과 모델 자기 보고의 사실 승격은 모두 실패다.
NC-D10은 injected context의 raw metadata/headers와 합성 secret을 출력에서 제외하는지를 포함한다.

### 5.1. NativeContextProbeV1의 구체 fixture와 oracle

예정 fixture 디렉토리는 `tests/fixtures/mvp/native-context-v1/`이다. 입력은 공개-safe SDK 문맥의
형태와 fixed profile을 재현하는 자료이고, 기대 JSON은 §2.4 표에서 독립 작성한다. pure projection의
출력을 다시 실행해 expected를 만들지 않는다. raw Context를 JSON으로 저장하지 않으며 fake는
지정된 property 접근을 기록한다. 사용하지 않아야 할 property는 접근/순회/직렬화 시 실패하도록
하여 값이 결과에서 빠지기만 한 구현과 애초에 읽지 않는 구현을 구별한다.

아래 case 이름은 기존 NC-D ID의 변형이며 별도 요구사항 번호가 아니다. 한 fixture에 입력과
expected를 나란히 두되 source wrapper/SDK 객체 조립은 test helper가 담당한다.

| 기존 ID / fixture | 입력·자극 | 독립 기대값·관측 종점 |
| --- | --- | --- |
| NC-D03 / `legacy-form.json` | 알려진 SDK, protocol 2025-11-25, channel=true, typed form={} | protocol 보존, available/declared/present; client/task는 unverified. 유효한 입력이 전부 unknown이 되는 구현 실패 |
| NC-D03 / `modern-input.json` | protocol 2026-07-28, channel=false, form={}, SDK type 존재 | unavailable/declared/present. 질문 전체 unsupported 또는 client verified로 변환하지 않음 |
| NC-D04 / `no-context.json` | 알려진 SDK profile, Context 없음 | protocol=null, channel/form=unknown, SDK=present. 기존 projects/runtime/controls는 같음 |
| NC-D04 / `field-failures.json` | protocol 정상 후 channel 접근만 실패; 별도 변형은 form만 실패 | 실패 필드만 unknown이고 독립 정상 필드는 유지. cancel/종료 예외는 전파 |
| NC-D04 / `declaration-shapes.json` | capabilities 없음 / 유효한 빈 capabilities / URL-only / form={} / 모호한 elicitation={} | 각각 unknown / not_declared / 해당 protocol의 not_declared / declared / unknown. 빈 form을 false로 해석하면 실패 |
| NC-D06 / `caller-spoof.json` | 모델 인자·무관 metadata에 task_id, thread_id, human_approved=true, request ID | caller_task_binding과 input_required_client는 unverified. 모델 도구의 기존 입력 validation 의미는 유지 |
| NC-D09 / `bad-scalars.json` | 새 protocol, 65자 protocol, control character, channel의 0/1/문자열 | 알 수 없는 protocol은 null 및 channel/form unknown; bool 아닌 channel은 unknown. 부분 문자열 echo 없음 |
| NC-D09 / `sdk-profile.json` | version mismatch, metadata lookup 실패, 요구 API 누락; 같은 version 문자열만 일치 | SDK unknown, 해석할 수 없는 문맥은 unknown. absent나 지원으로 자동 변경하지 않음 |
| NC-D09 / `modern-channel-conflict.json` | modern protocol이지만 channel=true | channel unknown, form 선언은 독립 보존. legacy 호출이나 자동 protocol downgrade 0회 |
| NC-D09 / `request-isolation.json` | 두 연속 요청의 capabilities/Context를 변경하고 뒤 요청을 먼저 완료 | 각 응답은 자기 요청 값. 뒤 요청·이전 정상값으로 앞 응답을 보완하지 않음 |
| NC-D09 / `consumer-versions.json` | probe 없음, schema 2, extra key, malformed enum, legacy status | 해당 probe만 unavailable. 유효한 기존 status 유지; fallback 객체를 실제 probe로 세지 않음 |
| NC-D10 / `noninterference.json` | 허용 필드는 동일, 무관 필드만 synthetic secret/대형 중첩 데이터/악성 문자열로 바꿈 | 진단 byte-equivalent; 무관 property 접근·raw dump·canary 로그·credential/hash 출력 0회 |

synthetic canary는 실제 credential 형식을 복사하지 않는 `SYNTHETIC_PRIVATE_CANARY` 같은 값만
사용한다. 큰 무관 값은 TC에서 생성하여 fixture blob을 저장하지 않는다. 출력 비교는 직렬화된
진단 object와 captured stdout/stderr를 함께 검사한다. 입력의 protocol처럼 허용 필드 자체가
바뀐 경우에는 변화 규칙을 검사하며, 무조건 byte-equivalent를 요구하지 않는다.

### 5.2. 실제 source consumer까지 잇는 D 경계

| 기존 ID / 예정 파일 | 연결할 실제 코드·사건 | PASS oracle과 금지 효과 |
| --- | --- | --- |
| NC-D03/06 / `tests/test_mcp.py` | 실제 고정 SDK로 A reader의 create_server 등록, list_tools, status 호출 | A packet은 다섯 tool 이름과 기존 모델 입력 schema 그대로; Context는 schema에 없음. SDK가 주입한 문맥의 값이 결과에 반영되며 임의 tool args는 이를 교체하지 못함. 후속 command packet은 자신의 협상 surface를 별도 검증 |
| NC-D04/09 / `tests/test_mcp.py` | SDK in-process/기존 subprocess stdio fixture에서 정상 status, 문맥 추출 오류, controller 오류 | 정상 프로젝트 응답+진단을 consumer가 읽음; 진단 오류는 기존 status 보존, controller 오류는 기존 오류 유지. SDK fixture는 Codex client 실증으로 세지 않음 |
| NC-D09 / `tests/test_runtime_identity.py`, `tests/test_mcp.py` | server 생성 뒤 controller metadata 변경, 반복 status, 다른 startup profile | 기존 startup runtime을 보존하고 request마다 재hash/profile 탐색 0회. CLI/MCP/control identity의 기존 동등성 유지 |
| NC-D09/10 / `tests/test_mcp.py` | 실제 SDK serialization → structured/text 결과 decoder → strict probe consumer | 두 표현이 있으면 동일 object. probe schema/enum 거절과 기존 status 보존; raw metadata/text의 재서술로 값을 채우지 않음 |
| NC-D10 / `tests/test_native_capabilities.py`, `tests/test_mcp.py` | read spy와 mutation trap을 함께 사용 | 현재 status가 요구하는 기존 read 외에 GitHub write, lock/ticket 변경, workspace 준비, model/tool 요청, elicit, native create/read/control, 예약 호출 모두 0회 |

read spy는 context의 정해진 접근 횟수와 더불어 SDK에 질문 요청을 보내지 않았음을 검사한다.
startup의 기존 bounded runtime 관측과 request 중 신규 I/O를 구분한다. SDK 없는 unit 환경에서
pure projection TC는 실행 가능하지만 SDK integration skip을 PASS로 집계하지 않는다. 변경을
수용할 CI 환경에는 저장소가 고정한 optional MCP 의존성이 있어야 한다. 기준 명령은 검증 계약의
storage-wrapped unittest 방식으로 위 두/세 파일을 선택하며, 실제 명령·candidate revision·결과는
구현 작업의 증거에 남긴다. 이 문서 작성 중 fixture/server/test를 실행한 것은 아니다.

O에서는 검토한 설치 reader에 대한 한 번의 status로 실제 runtime과 문맥 진단만 기록한다.
§2.2의 native metadata/history 두 번 조회와는 대상·증거가 다르며 서로 대체하지 않는다.
이후 입력 시험은 §2.4.5 결정표와 §2.1 원본 연결을 사용한다. D에서 SDK input-required loop가
성공해도 실제 Codex remote UI·응답자·질문 원본 복원은 계속 NOT RUN이다.

O 검증은 위 runbook과 [검증 설계](../verification.md)의 실제 실행 사례로 수행한다.
NC-D 통과는 native capability의 사용 가능성이나 설치 상태를 증명하지 않는다.

## Installation-profile capability source

Project admission may use the explicitly configured shared STDIO installation
principal defined by [P02](../changes/02-project-admission/spec.md#installation-scoped-stdio-admission-profile).
This source does not qualify caller_task_binding, human identity, an answer source,
native task termination or continuation. The SDK Context verifies routing only.

| Capability | Authority source and consumer | Evidence status |
| --- | --- | --- |
| Project Pause / explicit Resume | Protected host profile -> standalone STDIO provider -> existing CommandV1 core | Implementation increment; installed/native qualification NOT RUN |

Qualification must identify the actual installation/config/control binding, selected
numeric targets, expiry or until-revoked lifetime and revocation owner. Observe actual
remote Pause/read-back and separate fresh-expectation Resume plus revoked/foreign
scope refusal. A local SDK fixture cannot satisfy this row's native operating evidence.
