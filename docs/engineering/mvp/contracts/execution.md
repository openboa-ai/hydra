# 실행·검증·전달·복구 계약

Revision: 8; design contract, 2026-10-22. Installation authority increment.

상위 계약은 [SDLC 통합 설계](../../../architecture/sdlc.md)다. 이 문서는 구현할 동작과
검증 기준을 정의한다. 현재 코드가 모두 충족한다는 선언이 아니며 코드·설치·예약 실행을 재개하지 않는다.
현재 실행 정본인 [GitHub workflow](../../github-workflow/spec.md),
[native 계약](../../native-codex/spec.md), [재진입](../../proactive-continuation/spec.md),
[운영 관측](../../operating-continuity/spec.md), [admission 제어](../../mac-control/spec.md)를
유지한다. 아래에서 **추가**라고 표시한 계약은 해당 구현 단위에서 revision과 호환 전환을 확정한다.

## 1. 여섯 가지 설계 기준

| 항목 | 실행 요소의 계약 |
| --- | --- |
| 목적 | 위임된 요구를 기존 프로젝트 설계에 따라 구현하고, 실제 증거가 있는 결과와 남은 책임까지 이어간다. |
| 책임 | Codex는 해석·세부 설계·구현·독립 판단을 수행한다. Hydra는 identity·권한·전이·효과·증거를 확인한다. GitHub는 작업·설계·전달 사실, Codex는 native 실행·질문, 기존 자원 provider는 자원 사실을 소유한다. |
| 동작 | 원본 재조회 → 미확인 효과 대사 → 유효한 한 단계 배정 → 결과 checkpoint → 검증·리뷰 → 전달·관측 → 다음 요구 또는 종료·정리로 진행한다. |
| 실패·복구 | 의도·소유·기존 결과를 보존한다. 늦은 결과, 응답 유실, 중단, 재시작을 새 실행으로 덮지 않는다. 불확실성의 범위에 따라 해당 작업 또는 host admission을 막는다. |
| 완료 | 요구 충족·정확한 revision의 검증·필수 리뷰·실제 전달·필요한 관측이 연결돼야 작업 결과가 완료다. 목표 완료, 실행 종료, 자원 정리는 별도로 확인한다. |
| 범위 | 기존 다섯 MCP·CLI·runner·GitHub progress·host ticket을 재사용한다. 모델 서버, workflow DB, 세션 journal, 대체 스케줄러를 만들지 않는다. native 연결은 실제 capability qualification을 먼저 통과해야 한다. |

## 2. 식별과 저장: 기존 schema를 재사용한다

작업의 식별은 `repository_id + issue_number`, 실행 시도는 `attempt_id`, native 한 단계는
`native_step` UUID다. 대화나 세션 하나가 작업 하나라는 가정은 하지 않는다. `hydra-work:v2`는
목표/작업 관계를 설명하는 별도 등록 계약이며 `hydra-progress:v1`을 대체하지 않는다.
실행 입력은 [작업 연결 계약](work-records.md)의 공통 내부 `WorkBinding`이다. project v2의
`work_source=legacy_issue`는 현행 parser를 유지하고, `github_native`는 원문을 고치지 않은 채
인증된 binding과 adoption guard로 같은 내부 계약에 연결한다. 현재 parent/blocked-by는 native
원본에서 읽는다. 선택한 source의 범위·설계·실제 위임을 검증하며 다른 경로로 자동 fallback하거나
동시에 서로 다른 실행 의미를 채택하지 않는다.
본문이나 모델의 해석 성공, JSON 파싱 성공은 실행 권한이 아니다.

| 사실 | 정본·기존 필드 | 읽는 의미 |
| --- | --- | --- |
| 작업 원문 | Issue 원문, `intake_digest`; 새 binding의 `source_digest` | exact title/body의 같은 digest 함수. 기존 progress 필드의 의미를 binding digest로 바꾸지 않는다. labels/comments는 별도 재조회한다. |
| 수용한 실행 연결 | legacy parser 또는 인증된 `hydra-work:v2` → `WorkBinding`, `binding_digest` | 원문·요구/spec·delegated_goal·input_contract·위임의 연결. 현재 parent/blocked-by는 GitHub native 관계 정본에서 별도 조회한다. 새 binding digest는 작업 연결 계약에서 계산하며 progress v1에 삽입하지 않는다. |
| attempt의 binding anchor | 작업 연결 계약의 인증된 `hydra-attempt-binding:v1` comment | 기존 attempt와 정확한 binding comment·내용 digest·source·contract의 최소 관계만 고정한다. binding 내용이나 실행 상태를 복제하지 않는다. |
| 정책 | 보호된 계약 revision, `contract_revision` | 현재 정책과 pinned 정책의 내용·허용 효과를 대조한다. |
| 설계 | versioned spec, `spec_revision` | 수용된 내용 anchor. 작업 head와 같을 필요는 없지만 원문을 실제로 읽을 수 있어야 한다. |
| 코드·전달 | `head`, `expected_head`, `expected_base`, `published_head`, PR·Git 사실 | local candidate, 기대 remote, 통합 base, 확인된 publish를 구분한다. |
| 배정 | `execution_mode=native`, `native_step`, `native_phase`, `native_head`, `native_spec_digest` | 배정 당시 identity. native 실행 시작 증거가 아니다. |
| 재개 | `native_origin_phase`, `native_resume_phase`, `native_correction`, `resume_phase` | 진행 중이던 실제 의무를 보존한다. base 통합·중단으로 구현 의무가 사라지지 않는다. |
| 결과 후보 | `native_outcome` | `candidate_ready`, `failed`, `needs_decision`, `stopped`만 허용. 완료 인증이 아니다. |
| 미확인 효과 | `pending_action`, 각 action/head/base/attempt 필드 | 기존 요청의 실제 결과를 확인하기 전 다른 효과로 교체하지 않는다. |
| host admission | 기존 OS lock + bounded native ticket | 한 trusted host에서 native/CLI 공통 배제. ticket은 작업 DB가 아니다. |
| 실제 task·질문·예약 | Codex 원본 | 허용된 private 연결로 조회. public progress에는 native task ID·질문 원문을 넣지 않는다. |

현재 GitHub parser는 알 수 없는 progress JSON 필드를 거절한다. 새 요구를 임의의 필드로
덧붙이지 않는다. 새로운 dispatch/checkpoint/recovery/delivery guard는 현재 원문 digest와
해당 attempt가 수용한 binding digest·refs·위임을 함께 확인한다. 새 binding 경로는 작업 연결
계약의 `hydra-attempt-binding:v1` 원본을 조회하고 거기에 고정된 binding comment ID와 digest를
검증한다. 변경 없는 정상 재시작은 같은 anchor와 binding을 읽어 기존 책임을 복원한다.
최신 comment를 이전 attempt의 수용 근거로 자동 채택하지 않는다. anchor의 작성자·편집/삭제·중복,
binding 내용 변경·삭제·조회 범위 부족은 실행을 hold하고 기존 효과/edits를 보존한다.
source 변경의 동등성 검토와 fresh attempt 연결은 작업 연결 계약을 따른다. 이전 pending effect는
원래 anchor로 먼저 대사하며 새 binding에 옮기지 않는다.
legacy exact-digest 복구는 유지하며 새 source-equivalence 경로를 legacy에 소급 적용하지 않는다.
새 binding capability가 없는 runtime은 그 작업을 실행하지 않는다. 새 native 관측은 provider에서
읽어 projection하며 public progress v1의 타입·allowlist를 유지한다. 기존 `native_task_active` reason은 호환 입력으로 읽되
`native_assignment_pending`과 같이 **실행 미확인**으로 해석한다.

host ticket의 현재 scope digest는 repository 문자열의 case-fold 값, Issue number,
attempt, 초기 head, contract revision으로 계산한다. 실행 전 별도로 GitHub numeric repository
identity를 확인한다. 이름 변경으로 digest가 달라지면 자동 소유권 이전하지 않고 대사한다.
서버 restart는 GitHub progress와 ticket을 읽어 책임을 찾을 뿐 기존 실행의 종료를 증명하지 않는다.

## 3. 상태 전이와 불변조건

아래 명칭은 projection의 의미다. 새 영속 상태 머신을 만들거나 기존 `phase` 값을 전부 바꾸지 않는다.

| 상태·진입 조건 | 허용되는 다음 행동 | 남겨야 할 사실·금지 효과 |
| --- | --- | --- |
| 준비: 목표는 있으나 executable intake 미완성 | 기존 설계 읽기, 부족한 계약·TC 준비, 필요한 결정 | 가짜 attempt·worktree·ready 권한을 만들지 않는다. 악성 지시를 제외한 유효 요구는 안전한 요약으로 보존한다. |
| 실행 가능: 위임·의존성·설계/정책·scope·host 확인 | 기존 구현·증거부터 대조하여 필요한 단계만 시작 | 충분한 설계를 다시 작성하거나 완료된 요구를 재구현하지 않는다. |
| 배정 발행: ticket·public record 확인 | qualified native 경로로 한 배정 수행 또는 기존 task 대사 | 배정 반환만으로 running 표시·두 번째 dispatch 금지. |
| 실행 관측: provider의 정확한 task/turn 연결 | 해당 단계 수행, checkpoint 또는 실제 질문 | stage의 소유·입력 revision을 유지한다. task 종료와 요구 완료를 분리한다. |
| checkpoint: owned edits와 origin phase 보존 | 결과 검사, 필요한 검증·리뷰 또는 대기 | 공개 recording 확인 전 ticket을 해제하지 않는다. |
| 사람/외부 대기 | 실제 답변·CI·review 등 정해진 조건을 재관측 | 같은 질문·모델 호출·알림을 반복하지 않는다. unknown 실행이 없다면 다른 유효 작업은 진행 가능하다. |
| 검증·리뷰 | 실패 원인에 맞는 bounded correction 또는 전달 | 검증·리뷰를 같은 구현자의 선언으로 대체하지 않는다. |
| 전달 중 | 원래 publish/PR/merge 의도 read-back | 미확인 전달을 남긴 채 코드 수정·새 PR·새 merge 금지. |
| 병합 후 관측 | exact merge SHA의 필수 관측, 성공 시 close | merge 사실은 보존하고 실패·unknown을 pending으로 숨기지 않는다. |
| 결과 완료·정리 남음 | 해당 자원의 보존·retirement 및 목표 재평가 | 닫힌 Issue도 미완료 책임을 재발견할 수 있어야 한다. |

항상 유지할 보장:

1. 같은 host에서 동시에 writer는 하나다. review도 현재 native assignment/ticket 계약 안에서
   운영한다. read-only 분석의 병렬성은 별도 권한이며 공유 작업 공간의 writer 제한을 바꾸지 않는다.
2. stale attempt/step/head/policy/intake의 결과는 현재 작업·ticket·전달을 변경하지 않는다.
3. `candidate_ready`는 실제 파일·scope·검증·리뷰·CI·merge의 대체 증거가 아니다.
4. 현재 정책·설계·intake 변경은 영향 재평가를 요구한다. 오래된 증거를 최신 요구에 붙이지 않는다.
   scope 변경은 기존 intake를 조용히 교체하지 않고 현행 변경/새 작업 계약으로 처리한다.
5. 부정확한 관측은 unknown을 남긴다. 시간 경과·프로세스 이름·잠금 해제·Issue closed는 native 종료 증거가 아니다.
6. 관측 함수는 read-only다. 원본 조회가 비어 있거나 실패해도 실행·정리·ticket 해제를 유발하지 않는다.

## 4. 다섯 MCP와 효과 경계

기존 입력 signature는 유지한다. `head`는 checkpoint에서는 배정의 `native_head`이며,
verify/deliver에서는 마지막 확인된 current candidate head다. agent가 임의의 새 SHA를 만들어
호출하지 않고 마지막 원본/응답에서 정확한 값을 읽는다.

| 도구·입력 | 선행조건 | 허용 효과·반환 |
| --- | --- | --- |
| `hydra_status()` | 등록된 읽기 경계 | 원본·runtime·control projection만 반환. 미관측 capability·부분 coverage를 표시한다. |
| `hydra_begin(issue_url)` | 등록·위임·현재 intake/policy·의존·remote ownership·admission·잔존 실행 확인 | 기존 책임을 대사하고 한 guarded workflow continuation을 진행. assignment·delivery 대사·다음 대기를 반환할 수 있다. task 자체를 생성하는 도구가 아니다. |
| `hydra_checkpoint(issue_url, attempt_id, step_id, head, contract_revision, outcome, summary="")` | exact identity, 허용 outcome, summary 최대 24,000자, 현재 scope | owned edits의 checkpoint와 결과 후보를 기록하고 원 단계의 후처리. raw summary는 private/process-local. `stopped`는 실제 종료 확인이 선행한다. |
| `hydra_verify(issue_url, attempt_id, head, contract_revision)` | exact current work, 미해결 assignment 없음, 현재 정책·scope와 단계별 gate | 기존 공통 workflow를 계속한다. 검증·assignment·delivery 대사/효과 모두 가능하며 이름은 검증 전용 권한 경계가 아니다. |
| `hydra_deliver(issue_url, attempt_id, head, contract_revision)` | verify와 같은 identity·정책·단계별 gate | 동일한 guarded continuation이다. 필요한 이전 검증·assignment로 돌아갈 수 있고 gate가 충족된 delivery를 수행/대사한다. |

**추가: 새 control-plane 명령의 효과 상한.** 현재 `mcp.py`에서 verify와 deliver는 같은
`advance`를 호출하며 checkpoint/begin도 공통 runner로 다음 효과를 진행할 수 있다.
[기존 native 사용 계약](../../../native-codex.md)의 이 동작과 다섯 signature를 유지한다.
기존 호출에 몰래 검증 전용 의미를 부여하거나 caller가 이름만 보고 그렇게 추정하지 않는다.

새 UI에 검증 전용 조작을 제공한다면 [control-plane 계약](control-plane.md)의 versioned
`CommandV1.workflow_step`의 `operation=verify_only` capability를 명시하고, 동일 runner의 모든 효과에 허용 집합을
적용한다. 이 명령에서는 registered verification·local candidate checkpoint·independent
candidate review만 가능하며 publish·PR·remote review 요청·merge·close·retire를 호출하지 않는다.
다음 효과가 상한 밖이면 `waiting`과 필요한 다음 동작을 반환한다. 과거 delivery의 read-only
대사는 가능하지만 재요청은 금지한다. 별도 실행기를 만들지 않는다.

구버전 runtime이 이 capability를 제공하지 않으면 UI에서 검증 전용 조작을 실행하지 않는다.
기존 MCP continuation을 검증 전용 조작의 fallback으로 호출하지 않는다. 기존 자동 진행 위임을
받은 skill/CLI는 기존 공통 continuation을 계속 사용할 수 있다. capability 판별·새 명령의
effect guard·legacy 경로 회귀를 함께 전달한다. 어느 경로에서도 project contract나 보호 승인보다
넓은 효과를 허용하지 않는다. 원래 범위보다 좁은 UI 명령은 추가 제약일 뿐 새 권한이 아니다.

## 5. 배정과 checkpoint의 정확한 순서

배정은 다음 순서로 수행한다. 각 단계 사이의 crash/응답 유실이 TC 경계다.

1. 현재 GitHub work·contract·WorkBinding의 source/binding digest·spec·branch/PR와 local ownership을
   재조회한다. legacy와 새 binding의 채택·호환 경계는 작업 연결 계약을 따른다. 새 binding 경로에서는
   기존 초기 progress의 durable attempt에 작업 연결 계약의 `pending_action=bind_work` 의도를
   기록한 뒤 정확한 `hydra-attempt-binding:v1`을 연결하고 read-back한다.
   응답 유실은 같은 attempt의 원본을 재조회하며, 미확인 anchor에서는 ticket 확보·dispatch를 하지 않는다.
2. 현재 host/control barrier 안에서 한 step UUID와 기존 ticket을 확보한다.
3. `native_*`, origin phase, 초기 head·spec digest를 기존 progress에 기록하고 read-back한다.
4. 확인된 record와 동일한 private assignment를 반환한다. 포함 필드는 `repository`, `issue`,
   `attempt_id`, `step_id`, `phase`, `head`, `contract_revision`, `spec_revision`, `cwd`, `mode`, `prompt`다.
   `cwd/prompt`는 공개 DTO·로그·Issue에 복사하지 않는다.
5. native coordinator는 기존 연결을 대사한 뒤 qualified 경로로 수행한다. dispatch 확인이
   없으면 ticket을 유지하며 `native_assignment_pending`으로 남긴다. 같은 요청을 자동 재전송하지 않는다.

Codex는 배정의 spec 원문과 요구사항·TC를 읽고 scope 안에서 파일을 수정한다. Hydra 소유 branch의
commit/push/PR/merge는 Hydra 경로가 수행한다. read-only reviewer는 수정하지 않으며 review 전후의
head·dirty state·spec bytes가 동일해야 판단을 수용한다. 원 spec과 모순이 생기면 원문·영향·대안을
제시하고, 구현의 편의를 위해 기준을 수정하지 않는다.

일반 candidate checkpoint는 exact attempt-binding anchor 재검증 → outcome 기록 → 실제 owned workspace 검사 → 필요하면 local commit → origin phase를
포함한 재개 가능한 record의 read-back → exact step retirement → ticket release 순서다.
중간 실패는 남은 ticket과 기존 checkpoint를 대사한다. 새 assignment를 먼저 만들지 않는다.
이미 반영된 같은 결과는 재조회하여 기존 결과를 반환하거나 current continuation을 안내한다.
다른 outcome의 재제출은 `native_result_already_recorded`; 다른 identity는 stale 거절이다.

현재 binding이 변경돼도 기존 exact assignment의 종료가 확인된 경우에는 기존 계약의 좁은
`stopped` 보존 예외를 유지한다. 원래 authenticated progress의 scope 안에서 owned edits를
보존·기록하고 matching ticket만 해제한다. 새 binding 수용·신규 실행·publish를 허용하지 않는다.

write phase의 `needs_decision`도 edits를 보존한다. `candidate_ready` 뒤에 설계가 변했으면
이전 accepted anchor를 보존하고 새 spec review·실제 구현 의무를 남긴다. 서버가 private verification
output을 잃었으면 관련 검증과 independent review를 다시 수행한다. raw transcript 저장으로 해결하지 않는다.

## 6. Native provider에 요구하는 최소 계약과 미지원 경로

다음은 필요한 provider 동작의 이름이며 실제 Codex API 이름이 아니다. 세부 capability와 W1은
[native 연결 계약](native-capability.md)을 따른다. 구현 전에 현재 지원 표면과 영수증을 연결한다.
desktop persisted chat과 임의 app-server thread가 같은
실행이라는 가정을 하지 않는다. 직접 DB 수정·비공개 RPC·숨은 SDK worker는 사용하지 않는다.

| 필요한 동작 | 정확한 결과·증거 | 미지원/불확실할 때 |
| --- | --- | --- |
| `find_work_binding` | repository/work/attempt/step와 연결된 실제 task, lookup scope·coverage, 중복 여부 | 기존 task를 임의로 채택하지 않는다. `unsupported`/`unknown`과 연결 필요를 표시한다. |
| `create_or_continue` | 지원되는 idempotent request identity 또는 원본에서 재발견 가능한 요청, task/turn receipt | 응답 유실 후 찾을 수 없으면 재전송하지 않는다. 해당 assignment를 pending으로 보존한다. |
| `observe_execution` | 정확한 task/turn/step의 running/ended 사실, observation time, provider revision이 있으면 해당 값 | task status만으로 모든 하위 실행 종료를 단정하지 않는다. coverage 부족은 unknown이다. |
| `ask_and_read_answer` | 같은 task의 question reference, 실제 전달·답변 reference, 응답 주체와 질문 귀속 | checkpoint만으로 질문이 전달됐다고 표시하지 않는다. 침묵은 답이 아니다. |
| `request_stop` | exact owned turn에 요청한 receipt + 별도의 실제 종료 관측 | admission만 차단하고 실행 종료 미확인으로 남긴다. `stopped` checkpoint를 자동 제출하지 않는다. |
| `retire_owned_resource` | task 또는 해당 책임의 schedule 식별, 소유, inactive, 보존·미해결 책임 검사, 원본 재조회 | native 보관 기능이 있어도 stop으로 해석하지 않는다. 미지원이면 cleanup pending으로 남긴다. |

provider 결과는 최소한 `operation`, `target`, `request identity`, `observed_at`,
`availability`, `coverage`, `effect=requested|observed|unknown`, 원본 receipt reference를 갖는
private in-memory record로 정규화한다. 사실을 제공하지 않는 필드는 null/unknown이며 추정해 채우지 않는다.
이 record를 Hydra journal에 저장하지 않는다. 재시작 시 재발견할 연결은 **Codex 원본의 지원되는
durable metadata/reference 또는 기존 자원 provider**에 있어야 한다. public progress에는 연결용
native ID를 넣지 않는다. 이 연결을 지원하는 실제 경로가 없다면 자동 복구 capability는 미충족이다.

W1 qualification receipt는 사용한 실제 API/도구, provider/version, 지원하는 대상 범위,
identity binding, 응답 유실 후 lookup, restart, stop와 ended 구분, private disclosure 검사를
명시한다. public 문서에는 안전한 capability와 결론만 남기고 private task reference는 원 소유 시스템에 둔다.
모든 기능을 `supported=true` 같은 설정 하나로 활성화하지 않는다. 시작·조회·정지·정리 각각을 확인한다.

지원되는 기존 task에서 사람이 실행을 이어갈 수 있어도 이는 부분 운영 경로다. 목표한 자동 재진입·
중단·회복을 충족하지 못하면 해당 v1.0.0 acceptance를 `NOT RUN` 또는 `BLOCKED`로 남긴다.
화면이나 mock의 성공으로 범위를 축소해 전체 v1.0.0 통과를 선언하지 않는다.

## 7. 질문·결정·다음 wake

사람에게 묻는 것은 요구사항 발견·사용자만 아는 사실·선호·제품 의미·taste·선택의 충돌과 수정,
권한·정책 또는 위임 밖 효과다. 함수 구조·테스트 세부 등 설계 안의 구현 선택은 agent가 해결한다.
기존 설계에 답이 있으면 원문을 적용하고 재질문하지 않는다. 일반 요구사항 질문은 Codex native
질문이 기본이며 선택지와 자유 설명, 주관식 모두 지원 표면에 맞게 사용한다. MCP elicitation은
특정 도구 호출에 필요한 입력에 한정한다. 폼 제한을 피하려고 지원되지 않는 mode 전환을 하지 않는다.

준비 질문은 attempt를 만들지 않는다. 기존 assignment가 결정을 기다려야 할 때만 아래
needs_decision 보존 절차를 따른다. 독립 질문/작업은 영향 범위만 보류하고 전체 진행을 막지 않는다.
같은 결정에 여러 소질문을 묶을 수 있지만 첫 흐름의 source attempt당 미해결 결정 하나를 여러
독립 결정의 원자적 적용으로 확대하지 않는다. 부분 답변은 충분한 독립 범위만 확정하고, 추가 설명·
명시적 수정은 선택한 label보다 의미상 우선 반영하되 충돌이 모호하면 해당 부분만 확인한다.
답변 뒤 설계/TC에 반영할 차이를 설명한다. 확인 설명 자체를 또 하나의 의무 승인으로 만들지 않는다.

Codex는 현재 위임 안에서 질문 필요성·답변의 의미·현재 질문과의 관계를 판단하고 공개 가능한
결정을 제안한다. 그 구조화된 명령과 제안은 정상 입력이다. Hydra는 source/work 귀속, 현재
권한·admission·효과 상한·기준 판본·ownership을 결정적으로 검증한다. 별도 사람 인증 DB나
대화 의미 판단 엔진을 만들지 않는다. 모델의 제안만으로 사람의 승인, 실제 실행·종료 또는
외부 효과의 성공을 생성하지 않으며, 이 사실은 각각 권한 있는 원본과 실제 관측으로 확인한다.

### 7.1. 첫 흐름의 범위와 식별

첫 구현 단위는 이미 유효한 프로젝트·위임·legacy intake·수용 spec을 가진 작업 하나다.
host는 running, 제어 대상은 동일 project의 pause/resume이다. source attempt당 미해결 결정은
하나이며 현재 spec이 허용하는 선택을 질문한다. 새 실행 의미의 호환 전제는 WR의 보호된
project `version=2, work_source="legacy_issue"` 채택과 구버전 writer 종료다. 이미 미확정인 v1
효과를 그대로 둔 채 version을 올리지 않는다. 여러 질문의 병렬 해소, 새 intake/binding 전환,
책임 단위 admission, 새 task 생성, host 인계, cleanup-only는 이 단위의 선행 조건이 아니다.
제품 전체에서 제외하는 뜻도 아니다. 제품 의미는 [F06/F07](../../../product/mvp-design.md#42-전체-기능-조작표)를 따른다.

gate가 허용하는 동안 exact `needs_decision` checkpoint로 owned edits·origin phase와
재시작 가능한 record의 read-back, exact step retirement·matching ticket release를 확인한다.
이는 기존 쓰기 단계의 종료이며 질문을 받을 task의 보관·삭제나 모든 native turn의 실제 종료를
뜻하지 않는다. 같은 native task에 질문을 전달한다. 아직 남은 쓰기 실행/자식 process가
미확인이면 소유권을 해제하지 않는다. 대화가 계속돼도 끝난 assignment의 쓰기 권한은 재사용하지 않는다.

질문의 논리 연결은 아래와 같다. 새 Hydra DB/schema를 저장하라는 뜻이 아니며 adapter가
원본에서 읽어 만드는 private 메모리 값이다. 원본에서 복원 가능한 연결이 있어야 동작을
활성화한다. 제공 경로는 [NC의 첫 흐름 계약](native-capability.md#21-질문과-재개를-위한-원본-연결)에서 검증한다.

| 연결 | 읽어야 하는 근거 |
| --- | --- |
| 작업·원래 단계 | repository numeric ID, Issue, source attempt, checkpoint head, resume/origin phase, spec/contract/intake 근거. 새 binding이면 기존 attempt-binding anchor도 확인 |
| 질문 | provider instance, owning task, 원본이 제공하는 생성 turn, 정확한 질문 locator와 채택 판본·변경 검출 근거. 위 작업 근거를 지원 원본에서 재발견 가능 |
| 선택한 답변 | 원래 질문과 실제 응답 locator, 채택 판본·변경 검출 근거, 응답 출처와 해당 판단 권한, 명시적 수정/대체 관계 |
| 적용할 결정 | Codex 원본의 답변 선택 근거와 공개 참조, GitHub 정본의 exact public effect intent/context/resolved, 적용 대상 기준과 내용·순서 |
| 후속 실행 | source attempt의 결정 근거와 연결된 fresh attempt/step, 실제 task/turn 및 결과 |

최소 조건은 정확한 질문·답변의 재발견, 채택한 판본의 구별, 변경·대체의 탐지다. immutable
item ref는 이를 충족하는 수단 중 하나다. 지원되는 안정된 locator와 revision 또는 정확한
원본 내용의 변화 검출이 동등한 보장을 제공할 수도 있다. 반복된 ID만으로 불변성을 가정하거나
원본에 없는 revision을 만들지 않는다. 제목, 본문 유사도, 마지막 메시지, 시간만으로 연결을
대체하지 않는다. 같은 task의 메시지도 그 자체로 질문의 답변 증거는 아니다. 다른 대화의 답은
명시적 전달 지시와 지원되는 원본 귀속 증거가 있을 때만 연결한다. 침묵·인용문·에이전트가
대신 작성한 승인은 답이 아니다.

App Server의 `serverRequest/resolved`는 답변 수신 때뿐 아니라 다음 turn 시작·turn 완료·중단으로
pending 요청이 정리될 때도 발생한다. 이 알림이나 질문 UI가 사라졌다는 사실만으로 질문을
`none`, 답변을 `received`, 결정을 `applied`로 판정하지 않는다. 원래 미해결 책임을 보존하고
실제 질문·답변 원본을 다시 확인한다. `autoResolutionMs`에 따른 자동 해결도 사람의 답변이나
승인이 아니다. [공식 App Server 문서](https://learn.chatgpt.com/docs/app-server#toolrequestuserinput)

history의 `userMessage` role 또는 `clientId`만으로 응답자가 위임된 사람이고 그 결정 권한이
있다고 판정하지 않는다. 실제 응답의 출처·질문 귀속과 현재 위임의 권한 근거가 필요하다.
이 근거는 지원 플랫폼이 보증하는 입력 출처와 위임 관계를 재사용할 수 있으며, Hydra에 별도
사람 계정 식별자를 복제하라는 요구가 아니다. 연결된 계정이나 native caller라는 사실만으로
사람의 결정을 대신하지 않는다. 지원 경로의 보장 범위가 미확인이면 해당 결정 적용은 보류한다.
metadata·최근 메시지 조회와 이 의미 연결의 검증은 [NC read-only 계약](native-capability.md#22-read-only-adapter의-원본과-전달-경로)에서 구분한다.

### 7.2. 답변 수신·수용·적용·재개

첫 흐름은 다음 순서로 수행한다. 각 행의 성공은 다음 행의 성공을 뜻하지 않는다.

| 단계 | 전제·수행 | 결과·금지 효과 |
| --- | --- | --- |
| 질문 대기 | §7.1의 checkpoint와 원래 질문 전달 확인 | 같은 책임의 미해결 질문. 새 질문/task를 반복 생성하지 않음 |
| project pause | [CP 프로젝트 제어](control-plane.md#첫-흐름의-project-pauseresume)로 current expected revision 검사와 적용/read-back | 신규 Hydra 업무 효과 차단. 실제 native 실행 상태는 별도 관측 |
| 답변 수신 | 지원되는 native 원본에서 질문·답변 locator와 응답 출처·귀속을 확인 | 답변 수신·프로젝트 일시정지로 적용 대기. 답변 원문은 native에 보존 |
| paused 상태 | read-only 조회·귀속/충돌 판정·projection만 수행 | context/resolved·fresh attempt/ticket·일반 checkpoint·업무 commit·전달의 신규 dispatch 없음. Pause 전 요청의 늦은 결과는 읽어 대사하며 현재 first-flow fixture에는 그런 pending 요청이 없음. 기존 exact stopped 보존 예외는 별도 |
| 명시 project resume | 현재 local binding/control revision·위임된 제어 범위·상위 admission 확인 | 해당 project gate만 해제. 질문 해결·native 시작·보호 승인은 아직 아님 |
| 답변 수용 | 원래 질문, 선택한 답변/응답자, 현재 spec/policy/intake/head, 남은 효과·ownership 재확인 | 유효 답변은 같은 책임에서 사용. 충돌/새 scope/기준 변경은 영향받는 적용만 보류 |
| 결정 적용 | 아래 public-safe context와 resolved를 순서대로 게시·read-back, 각 쓰기 직전 다시 guard | 재조회 가능한 적용 근거. private ID·답변 원문·자격·경로 공개 금지 |
| 다음 단계 | continuation이 전체 guard와 결정 연결을 대조한 뒤 fresh attempt/step으로 원 phase 배정 | assignment 반환과 실제 실행 구분. 정상 조건이면 다음 행동과 checkpoint까지 진행 |

pause가 `needs_decision` checkpoint보다 먼저 적용됐으면 일반 checkpoint를 예외로 강행하지
않는다. 기존 수정·질문/답변을 보존하고 기록 미확정을 표시한다. 실제 종료가 확인되면 현행
좁은 stopped 보존을 사용할 수 있지만 이를 decision checkpoint 완료로 바꾸지 않는다.
순서가 어긋났다고 이미 받은 답변을 지우거나 같은 답을 다시 요구하지 않는다.

답변 수용은 Codex의 의미 판단과 Hydra의 source/authority 검증을 연결한다. 같은 locator의
채택 판본과 변경 없음이 확인된 재관측은 같은 답이다. 상충하는 답은 도착 시각으로 선택하지
않는다. 명시적인 대체 지시가 있으면 Codex가 변경 의미와 영향을 판단하고 Hydra가 현재 기준·
이미 수행된 효과·남은 권한을 대조한다. 선택지가 spec 범위를 바꾸면 새 기준의 수용·영향 검증
경로로 돌아가며 이 좁은 흐름에서 자동 승인하지 않는다.

### 7.3. 공개 결정과 유실·재시작 복원

**추가: native 결정 v1.** 현행 `runner`는 authorized login의 exact resolved 문구와 앞선
nonempty context를 찾아 재개한다. `GitHub.record`는 progress 전체 body를 조건 없는 PATCH로
교체한다. exact pair·채택 판본·write read-back·아래 protocol은 아직 없다. 현재 marker parser나
`pending_action` 문자열 검증만으로 이 새 동작이 구현됐다고 표시하지 않는다.

#### 정본·형식·호환

Codex의 지원되는 private 원본은 질문/답변, 채택 판본·대체 근거, 작업 귀속, exact 공개 제안과
그 공개 참조를 소유한다. GitHub는 공개 intent, 실제 context/resolved, 현재 후속 attempt와 전달
사실을 소유한다. Hydra는 원본을 join하여 다음 행동을 계산한다. 질문 DB·mapping 파일·명령 journal,
새 draft slot을 만들지 않는다. 공개 결과 본문을 native에 복제하지 않으며 임의 native metadata
쓰기 API를 전제하지 않는다. 원본에서 재발견 가능한 공개 제안은 첫 dispatch 전에 필요하다.

public key는 `(repository_id, issue_number, source_attempt, round)`다. round는 1부터 시작하고
명시적 대체 때만 1 증가한다. private task/turn/question/answer ID, 원문, 응답자 자격·개인 identity,
경로·secret 또는 private 답변 hash는 공개하지 않는다. payload SHA-256은 **공개 body**에만 적용한다.
public-safe 제안을 준비할 수 없으면 private 답을 복사하지 않고 현재 wait를 유지한다.

context 자체가 append-only exact intent다. 먼저 별도 progress draft를 PATCH할 필요가 없다.
아래 타입은 닫힌 객체이며 unknown key·중복 JSON key·잘못된 숫자/UUID는 거절한다.

```text
DecisionKey = {repository_id: positive_integer, issue_number: positive_integer,
               source_attempt: UUID, round: positive_integer}
DecisionPin = {key: DecisionKey, context_sha256: sha256}
IntentBasis = {
  key: DecisionKey, resume_attempt: UUID,
  origin_phase: design | implementation | correction | spec_review | change_review,
  head: git_sha, contract_revision: git_sha, spec_revision: git_sha | null,
  intake_digest: sha256, supersedes: DecisionPin | null
}
```

```text
hydra: decision <source_attempt> context
<nonempty public-safe decision and bounded impact>
<!-- hydra-decision-intent:v1 <IntentBasis JSON> -->

hydra: decision <source_attempt> resolved
<!-- hydra-decision-receipt:v1 <DecisionPin JSON> -->
```

두 body는 별도 comment다. 준비 시 LF·UTF-8, 마지막 LF 하나, JSON key 정렬·공백 없는 직렬화·
ASCII escape를 고정한다. 이후 재정규화하지 않고 exact bytes를 비교한다. context body는 16 KiB
이하로 제한하며 초과는 새 공개 제안을 준비할 사유다. truncate하지 않는다. 현행
`_bounded_context_json`은 prompt용이며 exact intent 저장·검증에는 사용하지 않는다. receipt body는
확인한 context의 key/digest로 결정적으로 만들며 모델이 다시 쓰지 않는다. resume UUID도 첫
공개 제안에 고정하며 재시작 때 새 UUID를 생성하지 않는다.

같은 서비스 numeric user ID와 login, 같은 key, **동일 exact body**의 물리 comment 여러 개는
하나의 semantic intent로 접는다. 같은 규칙의 receipt도 하나의 semantic receipt다. 참조는
comment ID가 아닌 key/digest이고 표시 링크는 일치 집합에서 가장 작은 numeric comment ID를
선택한다. 이는 GitHub의 물리 at-most-once 보장이 아니다. service numeric ID와 login이 확인된
trusted 후보 집합 안에서만 같은 key의 다른 body를 conflict로 판정한다. outsider의 marker/key
복제는 채택되지 않은 데이터로 제외·표시하며 정상 trusted pair를 막지 않는다. 직접 pin한 trusted
ref의 actor/body 불일치는 해당 근거 invalid이고, provider actor/coverage 자체가 미확인이면
unknown이다. 설명되지 않은 trusted 원본 edit/delete도 보류한다. 모델은 최신
댓글이나 유사한 본문을 선택하지 않는다. context 하나를 확인한 뒤 receipt를 전송하며 재시작 시
그 key/digest와 실제 앞선 context를 확인한다. timestamp만으로 순서·권한을 추론하지 않는다.
원본의 body/편집 metadata를 대조하되 comment가 immutable하거나 모든 과거 편집을 탐지한다고
주장하지 않는다. 과거 관측이 필요한데 원본 참조로 복원되지 않으면 그 판정은 unknown이다.

versioned receipt는 legacy의 exact resolved 한 줄과 다르므로 legacy resolver로 소비하지 않는다.
WR의 project-v2 gate가 구버전 runtime을 실행 전에 거절한다. progress JSON v1의 field/type과
기존 `hydra-decision-context:v1`의 source/resume 연결은 유지한다. 새 reader는 native intent/receipt를
해석하고 그 exact 연결을 operator context와 공통 begin/advance guard에 전달한다. legacy human
결정 경로를 native 자동 결정의 fallback으로 사용하지 않는다. 준비 단계 질문에는 attempt를 만들지 않는다.

#### 입력·순수 coordinator·효과 상한

CP의 `workflow_step/decision_apply`는 `proposal_ref: ResourceRef`, `source_attempt: UUID`,
`round: positive_integer`를 받는다. target은 Issue, `expected.assignment=null`, effect key는
`decision:<source_attempt>:<round>`다. retired step을 active assignment처럼 요구하지 않는다.
caller 값은 제안이다. qualified reader가 private 원본의 질문·답변·채택/대체 판본, 해당 판단 권한,
work 귀속, public key와 exact 공개 제안을 다시 읽는다. `authorized=true`, 모델 요약,
`userMessage` role 또는 서비스 actor로 source 사실을 대신하지 않는다.

reader의 최소 반환 의미는 `질문/답변/채택 원본과 판본 + 권한 근거 + 작업 기준 + exact public
proposal/ref + coverage`다. 실제 source field/transport mapping은 NC qualification의 선행 조건이며
지금은 미확인이다. generic JSON을 모델에게 받아 reader가 구현됐다고 간주하지 않는다. source
reader와 dispatcher를 분리하고 고정된 해석 fixture로 pure coordinator와 guard부터 검증한다.
별도 durable ‘최초 전송’ flag를 native provider에 요구하지 않는다. 최초 호출 또는 원본 호출
근거로 decision_apply 미호출이 확인된 restart는 같은 제안으로 context를 등록할 수 있다. 늦은
동일 POST도 append만 하므로 기존 progress를 덮지 않는다. 그러나 POST 직전/직후 crash가 같은
private proposal+public 0개로 보이면 둘은 구별할 수 없다. 이 창은 unknown이며 근거 없는
‘아직 전송하지 않음’ fixture로 양성 처리하지 않는다. 원본 호출 coverage도 qualification 대상이다.

정상 첫 흐름은 read-back된 `needs_decision` progress와 retired write step이 있어야 한다. record가
없으면 새 progress를 생성하지 않고 checkpoint 복구로 돌린다. decision_apply의 ceiling은 exact
context/resolved 게시·read-back이며 fresh attempt/ticket·개발·전달·project Resume은 포함하지 않는다.
그 다음 `continue`/`hydra_begin`이 공통 guard로 pinned resume UUID를 소비한다. `resume_hint`와
command 응답은 각각 다음 행동의 제안·좁은 효과의 결과이며 실제 실행 증거가 아니다.

#### 효과별 dispatch·read-back·종점

| 효과 | 전송 전 exact 의도·조건 | read-back·종점 및 재시작 |
| --- | --- | --- |
| context POST | native 원본에서 재발견한 exact public proposal/key, 현재 source attempt와 기준·selection, 이미 존재하는 동일 key 조회 | exact authenticated context 집합을 원본에서 확인. 동일 body는 재사용·접기, 다른 body는 conflict. late 동일 POST는 semantic 결정을 추가하지 않음. receipt 전송 전 context의 exact bytes 확인 필수 |
| resolved POST | 확인한 DecisionPin에서 계산한 exact receipt, 현재 selection·위임·admission, 기존 receipt 조회 | 같은 key/digest의 authenticated receipt를 원본에서 확인. 유일한 semantic pair면 decision_apply 종료. 실제 ref만 반환하며 native 시작/재개로 표시하지 않음 |
| resume progress PATCH | 전체 guard, 현재 native selection, exact pair, 원래 source attempt. intent에 고정된 resume UUID 사용 | 같은 progress comment에서 그 UUID로 attempt 전환·원래 resume/origin phase·기존 decision-context source/resume 연결을 한 body로 보존. exact record 확인 전 새 assignment 금지. 이미 그 UUID면 재사용하며 새 UUID를 만들지 않음 |
| 후속 assignment | resume record와 기존 ticket/ownership·입력·admission·현재 결정 연결 | 기존 배정→실제 수행→checkpoint 경로. unknown 기존 ticket이면 새 claim/dispatch 금지. CP의 continue와 legacy begin 모두 같은 decision guard 사용 |
| 첫 흐름 checkpoint_only | write phase design/implementation/correction, exact assignment, outcome=candidate_ready/needs_decision 또는 기존 stopped 보존 조건 | 아래의 원 phase 완료/대기 record read-back→matching retirement까지만. 다음 assignment·검증/리뷰 실행·전달 0회. failed 및 review phase는 첫 slice에서 unsupported |

checkpoint helper는 기존 `_finish_design`/`_finish_implementation`/`_finish_correction`의 원 phase
검사·owned commit·완료 기록만 분리해 재사용한다. candidate_ready는 design_done/spec_review hint,
implementation_done/verification hint, correction의 exact completed_phase·기존 resume 의미를
기록한다. needs_decision은 owned edits·origin/resume phase와 product_decision wait를 함께 남긴다.
spec/scope 불일치는 해당 wait를 보존하며 후보 성공으로 바꾸지 않는다. 완료/대기 record와 head를
read-back한 뒤에만 matching retirement를 수행하고, `_candidate_result` 전체·`_correct`·검증·
advance로 넘어가지 않는다. retirement 뒤 step/outcome이 사라져 중복 요청의 귀속을 증명할 수
없으면 그 요청은 unknown이며 다시 commit하지 않는다. 이는 현재 확인된 phase에서 다음 명시
continue가 유효한 다음 단계를 선택하는 것을 막지 않는다. restart 후 모든 후보를 다시 실행시키는
구현이나 정상 candidate_ready를 checkpoint할 수 없는 구현은 수용하지 않는다.

context/receipt 조회는 필요한 collection coverage와 서비스 actor, key·exact body를 함께 확인하고
표시할 실제 comment를 직접 재조회한다. 0개·404·timeout·페이지 잘림은 기존 POST 미적용의 확정
증거가 아니다. 다만 append-only의 **같은 key/exact body**는 늦은 중복을 semantic하게 접을 수
있으므로 검증된 동일성·현재 guard·남은 budget이 모두 있으면 재전송할 수 있다. 다른 payload나
새 round로 유실을 우회하지 않는다. 실제 read-back되면 추가 요청 없이 정상 다음 단계로 전진한다.

재시도 상한은 최초 포함 3이다. 기존 progress `action_attempt`와 원래 요청의 재발견 가능한
실제 근거로 횟수를 확인하며 새 durable counter/journal을 만들지 않는다. 재시작 후 이전 물리
요청 횟수를 확인할 수 없으면 budget을 0으로 초기화하지 않고 read-back/진단으로 보낸다.
semantic idempotency가 무제한 POST 권한을 뜻하지 않는다. 실제 호출 근거로 이전 전송 없음이
확인된 경로와 response-loss/호출 범위 미확인 경로를 fixture에서 구분한다. 동일하게 관측되는
상태에 서로 다른 성공·실패 oracle을 붙이지 않는다.

resume PATCH는 append-only가 아니다. 같은 host의 기존 ownership/lock 안에서 최초 한 번
전송하고 exact record를 read-back한다. 응답 유실 뒤 같은 resume UUID/phase/연결이 확인되면
재사용한다. source attempt의 old body만 보이거나 결과가 partial이면 unknown이고 blind PATCH
retry는 0회다. 기존 ticket이 있으면 보존한다. late PATCH가 현재 progress를 덮을 수 있으므로
미확정인 상태에서 다음 round·다른 attempt·새 record write로 우회하지 않는다. 신규 retry는 해당
요청이 확정적으로 미적용 종료했고 원래 expected record와 모든 guard가 여전히 유효한 경우에만
기존 bounded budget 안에서 가능하다. 최초 continue 미호출이 원본 호출 근거로 확인된 restart는
정상 전진할 수 있지만 exact pair+old progress만으로 이를 추정하지 않는다. PATCH 직전/직후의
구분 불가 crash 창도 unknown이다. 원본 read-back만으로 서버 CAS가 생기지는 않는다.

#### 직렬화·Pause·원격 변경의 실제 경계

같은 host coordinator의 exclusive lock으로 효과 순서를 직렬화하고, 각 bounded mutation에는
기존 shared admission guard를 적용한다. Pause/Resume의 exclusive control lock과 coordinator
lock은 역할이 다르다. 사람 응답 대기나 긴 polling 동안 lock을 잡지 않는다. 한 qualified host
writer가 전제이며 다른 host나 직접 GitHub writer를 이 lock이 막아준다고 주장하지 않는다.

매 효과마다 progress/pair, 위임·intake/spec/policy/head, private 채택 판본을 재조회·대조하고
전송 직전 admission을 다시 검사한다. 이 read-check는 원격 GitHub 편집·답변 수정과 atomic하지
않다. `updated_at` 비교를 서버 CAS라고 부르지 않는다. 이미 보낸 요청 뒤 변경이 발견되면 원래
효과를 read-back하고 다음 영향받는 효과를 보류한다. 재조회했으므로 stale 효과가 절대 발생하지
않는다고 보장하지 않는다. append-only를 쓰는 목적도 늦은 요청이 현재 progress를 덮지 않게 하는 것이다.

Pause 적용 뒤 **새 Hydra 업무 dispatch는 0**이다. Pause 전 요청이 응답 유실 뒤 서버에서
반영될 수 있으므로 효과 commit 시각으로 위반을 판정하지 않는다. paused 중에는 원본을
read-back하되 확인용 progress PATCH나 다음 POST는 보내지 않는다. Resume 후 이미 반영된
결과부터 대사한다. 상위 host Pause/Stop, project Stop, 위임 철회는 project Resume·답변 수신으로
해제되지 않는다. native client 자체 wake는 이 보장 밖이며 Hydra 경유 신규 효과에는 같은 guard가 적용된다.

#### 수정·소비·완료 후 복원

다음 round는 native 원본의 명시적인 대체 선택과 현재 기준 검증을 요구한다. 앞선 context가 있으면
`supersedes`는 그 DecisionPin이다. 미확정 요청의 내용/예산/결과를 대사하지 않고 새 round부터
발행하지 않는다. 과거 context/receipt는 편집·삭제하지 않으며 현재 선택이 대체 관계의 정본이다.

| 수정 시점 | 보존·정상 회복 경로 |
| --- | --- |
| 공개 POST 전, 미전송 확정 | 같은 실행에서 새 선택과 exact 제안을 명시적으로 준비하여 첫 등록. restart 뒤 context 부재만으로 기존 POST가 미전송이었다고 판정하지 않음 |
| context만 존재, resolved 미전송 확정 | 원래 전송 대사 후 대체 선택·다음 round·supersedes를 고정. 새 context/receipt의 정상 등록·read-back까지 진행. 이전 context는 남기며 최신 댓글 자동 선택 금지 |
| resolved 확인, resume attempt에서 미소비 | 옛 pair 보존·옛 최초 배정 hold. 새 선택·변경 영향의 public-safe 계획을 amendment/replan으로 수용한 뒤 다음 round와 새 pinned resume UUID 사용. 기존 receipt 재사용이나 계획 없는 재개 금지 |
| resume attempt에 이미 소비 | 수행 효과·edits 보존. 현재 attempt의 영향받는 신규 효과를 hold하고 checkpoint/replan으로 수정된 기준의 다음 행동 진행. 원래 source attempt를 재실행하거나 자동 rollback하지 않음 |

scope/권한/평가 기준 변경은 이 좁은 흐름에서 자동 승인하지 않는다. 범위 내 수정은 기존 위임과
review/replan gate를 사용하며 정상 다음 행동까지 검증한다. 명시적 대체 근거 없이 시간·문장
유사도로 선택하지 않는다. 수정이 재검사 직후 도착하면 in-flight 대사가 먼저다. 수정 자체는
native 종료나 project Resume의 근거가 아니다. 무조건 conflict로 끝내는 구현도 수용하지 않는다.

native 경로는 인증된 `execution_mode=native`, product_decision source attempt와 기존
source/resume 연결로 분류한다. step retirement 뒤에도 mode를 보존한다. private provenance가
없으면 unknown이며 모든 begin/advance에서 legacy fallback을 막는다. public 서비스 actor나
resolved는 사람 위임·CODEOWNER·protected environment 승인을 만들지 않는다.

원 phase 완료 뒤 기존 decision-context marker는 제거될 수 있다. intent의 resume UUID는 예정
연결이며 단독으로 실제 소비·완료의 증거가 아니다. 완료 후 수정은 private 선택·공개 참조, 실제
GitHub 전달/완료 근거와 현재 남은 책임을 대조한다. 과거 소비 증거를 재발견할 수 없으면 그 과거
판정만 unknown이며 정상 완료 전체를 되돌리거나 원래 실행을 반복하지 않는다. 새 변경은 현재
책임에 명시적으로 연결한다. 지원 source/transport와 복원 qualification 전 자동 결정 적용은 미지원이다.

### 7.4. 다음 wake와 구현 경계

가능한 일은 같은 turn에서 이어간다. 의미 있는 상태 변화가 있을 때 기존 native re-entry 기능을
사용한다. 질문만 남으면 해당 goal의 불필요한 heartbeat를 멈추고 owning question을 유지한다.
다른 책임이 있는 shared schedule은 해당 wait를 건너뛴다. Hydra 자신의 progress/comment 갱신,
UI refresh, 변화 없는 poll은 새 작업·새 모델 호출의 이유가 아니다. 가장 높은 우선순위의 작업이
blocked여도 dependency와 host ownership이 허용하는 독립 작업을 선택한다. 검증된 완료 뒤 Issue가
다시 열렸다는 사실만으로 이전 실행을 반복하지 않는다. 실제 남은 요구·scope·위임을 먼저 대조한다.
새로운 scheduler나 보장되지 않는 event
subscription을 만들지 않으며 schedule 변경은 위임·소유·조회 범위를 확인한 대상에만 한다.
native 예약 자체가 model turn과 비용을 발생시키는 경우와 Hydra가 추가 model 호출을 선택하는
경우를 구분한다. unchanged wait에서 추가 호출 0회라는 보장은 기존 예약의 비용이 0이라는 뜻이
아니다. 놓친 tick은 최신 work/attempt/원본을 한 번 대사하며 tick 수만큼 task·attempt를 생성하지 않는다.

첫 흐름은 질문 원본·답변·결정 적용·project admission의 연결을 증명한다. native Stop,
자동 예약 wake, 두 프로젝트 전체 운영과 정리의 수용을 대신하지 않는다. 기존 owner 경로에
질문 reader/decision guard와 CP의 CAS를 연결하고 checkpoint 이후 자동 전달로 넘어가지
않는 제한도 검증한다. 필요한 좁은 `checkpoint_only` 경로가 없으면 legacy checkpoint를
같은 이름으로 사용하지 않는다. 실제 native 지원은 NC에서 확인한다.

## 8. 검증·리뷰·전달의 연결

| 단계 | 전진에 필요한 증거 | 실패·불확실성에서 하는 일 |
| --- | --- | --- |
| 설계 수용 | 기존 수용 revision 또는 실제 scoped spec에 대한 독립 review, regular/tracked/nonempty 파일·크기·scope 검사 | 구현보다 먼저 부족한 계약을 보완. accepted bytes 변경은 review와 영향받는 구현을 다시 요구한다. |
| 구현 검증 | 수용 요구의 TC, registered argv/cwd/timeout, 실제 exit·실행 범위·skip·현재 clean head | TC 실패와 환경/중단/unknown을 분리. TC 기대값을 낮추지 않고 재현→원인→수정한다. |
| 독립 change review | 정확한 spec/diff/head와 private 검증 출력, 다른 review turn, 설계 충실성·품질 판단 | 필수 요구 누락은 green TC와 무관하게 미완료. 수정 head는 기존 review를 무효화한다. |
| publish·PR | 현행 scope, 통합 base, owned branch/PR, 공개 가능 내용·필요 screen evidence | expected remote head를 사용하고 force 금지. 모호한 기존 PR은 채택하지 않는다. |
| remote review·CI | 실제 producer/workflow/event/ref/head/job identity, 필수 code/security review, 미해결 thread 없음 | running은 대기, terminal failure는 correction/진단, unknown·위조·stale은 gate 미충족. |
| merge | 최종 head/base·소유·보호 gate 재조회, 승인된 merge 효과, exact merge intent | 보호 우회 없음. 응답 유실은 같은 PR의 실제 merge를 먼저 확인한다. |
| post-merge | 실제 merge SHA와 trusted latest run의 required checks, 프로젝트가 요구하는 관측 | pending=`post_merge_checks`, terminal=`post_merge_failed`, 미확인=`post_merge_evidence_unknown`. 아래의 진단·복구 경로로 진행하며 자동 rollback·무조건적인 새 Issue 생성은 하지 않는다. |
| close·결과 완료 | 요구별 evidence, 실제 merge/post-merge 및 필요한 완료 extension의 성공 | PR body 자동 close를 사용하지 않는다. close 응답 유실은 원본 재조회. 배포를 요구하면 배포 관측은 별도다. |

외부 효과는 전부 **의도 기록 → 효과 요청 → 원본 read-back → 확인 기록**을 따른다.
응답이 유실됐을 때 publish는 exact branch/head, PR은 repository/work ownership marker,
review는 provider/kind/head, merge는 owned PR/head/merge SHA, close는 해당 Issue의 상태와
완료 근거를 재조회한다. 실제 결과가 확인되면 요청을 반복하지 않는다. 미적용이 확정되었거나
§7.3의 제한된 append-only semantic 동일성이 성립하고 현재 gate와 남은 budget이 허용할 때만
재시도한다. 조회에서 0개인 것만으로 미적용을 확정하지 않는다. 최대 세 번 요청
(최초 + 두 번 transient retry) 후 진단으로 전환한다. unknown은 없다는 증거가 아니다.

pending merge가 있을 때 새 review finding·base 변경이 생겨도 먼저 원래 merge를 대사한다.
병합된 policy 변경의 완료 대사는 기존 계약의 좁은 completion-only 경로를 사용하며 신규
구현·publish·merge를 허용하지 않는다. new policy는 이후 작업에서 별도로 채택한다.

merge route도 보호 정책의 원본 사실이다. direct merge가 허용되면 기존 경로를 사용한다. merge
queue가 필수이면 direct merge를 보내지 않고 지원 여부를 표시한다. 향후 qualified queue adapter는
exact enqueue intent/entry read-back, 실제 integration revision의 trusted checks, 최종 PR merge
사실을 구분해야 한다. PR head의 green CI나 enqueue 성공을 merge로 승격하지 않는다. 현재 구현이
queue enqueue/취소/재시작을 지원한다는 뜻이 아니며 미지원은 원본 경로의 필요한 조작으로 남긴다.

### 병합 후 실패에서 실제 복구까지

**추가: `post_merge_failed`는 진단의 진입점이며 영구적인 막다른 상태가 아니다.** 원래 PR의
merge SHA·실패한 run·요구사항을 보존한 뒤 원인을 구분한다. 원인 판정은 현재 증거를 읽는
Codex의 제한된 진단이며, 후속 효과는 동일한 권한·identity·효과 guard를 통과한다.

| 진단 결과 | 허용된 후속 행동 | 성공 또는 다음 판단의 근거 |
| --- | --- | --- |
| infrastructure/검사 실행 문제, 코드 변경 불필요 | 해당 workflow/run의 재실행이 현재 위임과 project policy에 포함되면 exact run을 한 번 요청하고 read-back. 기존 최대 세 번 요청 budget을 사용한다. | 실제 newer run의 producer·원래 merge SHA·필수 job을 검증. 실패/unknown이면 진단으로 돌아가며 재실행으로 기존 실패 근거를 지우지 않는다. |
| 실제 코드 결함, 기존 수용 요구·위임 안에서 수정 가능 | 아래의 WR 등록 경로로 하나의 repair outcome을 재사용하거나 생성하고 TC→수정→독립 review→별도 protected PR→post-merge 검증을 수행한다. | 원래 결함의 회귀 TC와 repair의 실제 revision·전달·관측 증거. 원래 PR을 재병합하거나 기존 증거를 새 SHA로 바꾸지 않는다. |
| 원인 미확인, 필요한 위임 없음, 제품/평가 기준 변경 필요 | 필요한 증거를 추가 조사하거나 정확한 결정과 권고안을 owning task에 질문한다. 독립적인 허용 작업은 계속한다. | 권한·기준이 실제로 해결됐는지 확인. timeout·agent 설명·실패 반복은 새 권한이 아니다. |

재실행 요청에도 의도와 read-back이 필요하다. provider가 안전한 run 식별·재조회 또는 허용된
재실행 기능을 제공하지 않으면 원본의 지원 경로와 필요한 조작을 표시한다. 일반 CLI/shell이나
새 credentials로 검사 서비스를 대신 실행하지 않는다. 이미 queued/running인 동일 대상은 다시 요청하지 않는다.

repair 등록은 [작업 생성·중복·위임 계약](work-records.md)의 기존 guard와 `create_key`를 사용한다.
같은 원래 repository·goal·영향받는 RequirementRefs에서 `outcome=repair-<원래 merge SHA>`를
사용해 하나의 repair 결과를 식별한다. SHA는 실제 소문자 40hex이므로 slug는 47자다.
원래 작업이 단일 goal 겸용이면 그 Issue가 repair의 owning goal이 된다. 먼저 기존 repair를
전체 필요한 범위에서 조회하고, 있으면 그 작업의 실패/진행/전달을 대사한다. 중복 후보는 conflict,
partial 조회는 unknown이며 새 Issue를 반복 생성하지 않는다. 일반 요청 생성과 동일하게 기존
goal delegation의 `create_work`/`execute_work` 범위와 현재 ready/admission을 확인한다.
이 key는 이번에 진단한 원래 전달 의무에 대한 하나의 repair outcome을 식별한다. 나중에 별개의
결함·다른 scope가 발견되면 이미 bound된 repair의 의미를 넓히지 않고 일반 새 outcome/변경 guard를
적용한다. 같은 key를 유지하려고 서로 다른 요구를 하나의 기존 작업에 밀어 넣지 않는다.

repair는 원래 실패한 Issue를 `post_merge_verified` dependency로 두어 자기 복구를 막지 않는다.
원래 결과·merge·실패·요구 참조는 repair spec/작업에서 근거로 연결하고 실제 수정에 필요한 다른
의존성만 dependency gate로 둔다. 원래 작업에서는 검증된 repair Issue 링크와 남은 책임을
표시하며 새로운 tracker 상태를 만들지 않는다. 새 repair PR·merge에는 기존 모든 보호 gate를 적용한다.

repair가 성공하면 요구 충족의 최신 증거는 **repair의 head/merge/관측**이고 원래 전달은 계속
`merged + post_merge_failed`다. v1.0.0의 완료 평가에는 이 명시적인 대체 산출물 경로를 추가한다:
정확히 연결된 유일한 repair가 해당 요구를 충족하고 필수 post-merge·운영 관측까지 완료했을 때
원래 실패의 후속 책임을 `repair로 해결됨`으로 파생 표시한다. 실패 기록을 success로 덮지 않으며
원래 PR에 merge를 반복하지 않는다. 요구가 충족된 goal은 다음 요구 또는 정리로 진행할 수 있다.
프로젝트가 원래 SHA 자체의 성공을 별도로 요구한다면 그 조건은 남는다. 이 기준을 repair 성공으로
조용히 대체하지 않고 정확한 계약 결정을 요청한다. 이 완료 확장은 별도 TC와 검토가 필요한 v1.0.0
변경이며 현재 legacy completion predicate가 이미 제공한다고 주장하지 않는다.

## 9. Pause·Stop·취소·재시작·정리

| 사건 | 실행 규칙 | 남는 책임 |
| --- | --- | --- |
| Pause/Stop 요청 | shared control barrier 이후 신규 Hydra 업무 dispatch 차단. 이전 전송의 늦은 remote commit은 별도 read-back | gate applied와 실제 native ended를 각각 관측한다. Stop의 native interrupt도 exact owned task/turn·qualified 경로가 필요하다. 별도 정리 요청은 아래 제한된 경로만 사용한다. |
| 실제 실행 종료 확인 | exact stopped checkpoint로 owned edits·origin phase 보존 후 matching ticket release | 자동 허용 예외는 이 좁은 보존뿐이다. push·PR·close·삭제 권한이 아니다. 아래 별도 명시적 정리 요청과 구분한다. |
| native stop 미지원/미확인 | gate는 막되 unknown ticket 유지, 원본의 지원되는 제어 경로 안내 | 다른 writer admission 금지. timer·프로세스 이름으로 kill/해제하지 않는다. |
| 목표/작업 취소 | 새 개발·delivery 중지, inflight 효과와 결과를 read-back하여 보존 | 취소는 종료·rollback·cleanup 완료가 아니다. unknown 결과·보존·정리 의무가 남는다. |
| 실행 중 권한 철회 | 이후 효과의 직전 gate에서 차단하고 실제 실행의 안전한 중단/보존을 요청 | 이미 전달한 결과와 inflight intent는 보존한다. 철회를 자동 rollback·scope 폐기로 해석하지 않는다. |
| host/app/server 재시작 | 현재 모드·progress·ticket·workspace·remote·native 연결 및 exact attempt-binding anchor 재대사 | 변경 없는 binding은 원본에서 복원하여 계속한다. explicit stop 자동 해제 금지. private evidence 유실 시 검증/리뷰 재수행. |
| 다른 host handover | 이전 실행의 explicit confirmed stop와 authorized handover, exact checkpoint 접근 확인 | unpushed head가 새 host에 없으면 hold. stopped라는 사실로 commit을 재생성하지 않는다. |
| 결과 완료 | Goal의 다음 요구와 남은 observation/cleanup을 계산 | one-shot goal 종료 뒤 임의 유지보수나 새 goal을 만들지 않는다. |
| 명시적 정리만 요청 | CP의 qualified cleanup profile로 특정 owned 자원의 종료·보존·공유 책임·실제 권한을 확인해 정리 | admission은 paused/stopped 그대로 유지한다. Stop/취소/일반 Goal을 이 요청으로 합성하지 않으며 새 업무 실행·전달은 0회다. |

일부 요구가 전달된 뒤 취소되어도 성공한 산출물·검증 근거와 남은 미확인 효과·정리는 보존한다.
정리는 결과 완료 또는 취소 이후의 독립된 의무다. 기존 resource provider의 owned/inactive/보존 완료
판정을 사용한다. worktree를 지우기 전 미보존 diff·untracked·unmerged 결과를 확인한다.
native task 보관은 미해결 질문/실행이 없고 원본에서 결과를 찾을 수 있을 때만 한다. schedule은
해당 책임이 끝났고 공유 책임이 없을 때만 retire한다. foreign·dirty·active·unknown은 보존한다.
취소로 더 이상 답이 필요 없는 질문은 원본의 취소/책임 근거와 함께 not-applicable로 판정할 수 있다.
답변을 받은 것으로 꾸미지 않으며 무의미한 질문이 archive를 영구적으로 막게 하지 않는다.

**추가: 책임의 재발견.** `hydra:active`는 실행 중이 아니라 Hydra의 남은 책임 표식으로 사용한다.
결과 완료+cleanup pending인 닫힌 Issue도 조회한다. 마지막 owned resource의 정리뿐 아니라 pending
effect·유효한 결정 대기·필수 관측·공유 책임이 모두 끝난 뒤 표식을 제거한다. 정리 실패는 같은 작업에서
다시 대사한다. 새 구현 attempt·복제 Issue를 만들지 않는다.
외부에서 표식이 제거되면 ticket/provider inventory와 대조해 orphan/unknown을 표시한다.
inventory scope가 partial이면 active=0·cleanup complete·안전한 Quit을 선언하지 않는다.
paused/stopped의 일반 continuation에서는 deletion/retirement도 보류하며 관측·보존만 한다.
제품의 별도 **정리만 요청**은 [CP](control-plane.md)의 typed cleanup 계약과
[P15](../changes/15-resource-retirement/spec.md)가 구현한다. 현재 실제 요청의 대상·허용 조작과
원본 권한을 확인하고 기존 lock/guard 아래서 그 자원 효과만 수행한다. admission을 잠깐 running으로
바꾸거나 broad continuation/완료 callback을 호출해 예외를 만들지 않는다. 자원 보존이 미확인인
상태에서는 삭제하지 않으며 원래 provider의 보존·release·read-back을 먼저 확인한다.
응답 유실은 동일 자원·원래 요청의 효과를 재조회하며 새 요청 identity로 다시 삭제하지 않는다.
provider가 대상/소유/보존/현재 결과를 확인할 경로가 없으면 해당 조작은 unsupported/unknown이다.
공유 자원 전체를 지우거나 GitHub 완료·close·새 배정을 수행하는 권한은 이 경로에 없다.
명시적 자원 정리는 goal 전체의 완료·취소를 요구하지 않는다. 해당 자원의 비활성·보존·다른
책임과의 분리가 충분하면 수행할 수 있으나, 성공을 goal 완료로 바꾸거나 기존 phase/wait/
next_action을 정리 상태로 덮지 않는다. 아직 유효한 질문·구현·관측 책임과 active 표식은 유지한다.
이미 완료/취소된 책임의 기존 정리 분기는 모든 잔여 의무 해소를 확인한 뒤 cleanup bookkeeping과
active 표식만 종료할 수 있다. 살아 있는 업무 상태를 바꾸는 것과 구분하며 Issue close나 새 단계는 실행하지 않는다.

## 10. 오류·대기와 복구 규칙

public 반환은 기존 `action/reason`에 의미를 유지한다. raw exception·경로·비밀값을 user-facing
reason으로 보내지 않는다. 아래 proposed reason은 새 progress JSON key를 뜻하지 않는다.

| 오류/원인 | 보존·복구 | 절대 하지 않는 효과 |
| --- | --- | --- |
| stale native continuation / head changed | 최신 identity와 원본을 반환 또는 재조회; caller의 이전 결과 거절 | 현재 step 소비·ticket 해제·commit·전달 |
| `assignment_ticket_unknown`, `assignment_record_unknown` | 기존 ticket과 public record read-back, positive stop 근거 확보 | 자동 redispatch·없는 work record 제조 |
| `intake_changed`, policy/spec mismatch | 기존 checkpoint/effect와 accepted anchor 보존, 변경 영향 검토 | digest 교체·scope 확대·old evidence 완료 |
| `product_decision`, `replan_required` | exact source attempt와 authorized resolution 확인 | generic 답변/침묵으로 재개·retry budget 임의 초기화 |
| `publish_unknown`, `pr_unknown`, `merge_unknown`, `close_unknown` | 원래 의도 식별자로 원본 대사, bounded retry | 새 identity·PR·head로 요청 교체 |
| `post_merge_failed` | 실패 근거 보존 → infra 재실행 또는 위임된 단일 repair outcome → 실제 후속 증거 확인 | polling-only 무한 대기·중복 repair 생성·old PR 재병합·자동 rollback |
| `post_merge_evidence_unknown` | 정확한 producer/SHA/coverage 확인 | missing check를 success로 처리 |
| native capability unsupported / binding unknown | 필요한 capability와 partial 운영 범위 표시, W1 미충족 유지 | 별도 worker·journal·비공개 API로 대체 |
| cleanup pending/unknown | 기존 work/provider에서 discovery 보존 | 결과 재구현·foreign 삭제·Quit 성공 |

## 11. 결정적 TC·판단 평가·실제 관측

아래 TC는 **계획**이다. 현재 실행 결과가 아니다. fake provider로 시간·UUID·실패 위치를
주입하고 원본 snapshot, 실제 Git 상태와 effect call을 관측한다. 기대값은 위 계약에서 고정하며
테스트 대상 함수로 다시 계산하지 않는다. real Git/process 의미는 격리된 통합 fixture로 검증한다.

계획 시험 파일:

- `tests/test_mvp_execution_contract.py`: EX-D01–D14, D17–D18, D22–D27, D31.
- `tests/test_mvp_delivery_contract.py`: EX-D15–D16, D19–D21, D28–D30.
- 기존 `test_native.py`, `test_native_wait_identity.py`, `test_restart_ownership.py`,
  `test_operation_boundary.py`, `test_post_merge_checks.py`, `test_active_labels.py`는 중복 구현 없이
  재사용·확장하고 전체 suite에서 회귀를 확인한다.

| ID | Given / When | Then: 기대 결과와 금지 효과 |
| --- | --- | --- |
| EX-D01 | 동일 host에서 두 begin와 CLI가 경합 | 한 step/ticket만 존재; 다른 요청은 배정·workspace mutation 0회. |
| EX-D02 | ticket 후 progress write가 timeout | read-back된 동일 record만 인정; unknown이면 같은 ticket 유지·dispatch 0회. |
| EX-D03 | 배정 반환 후 응답 유실·restart·중복 wake | 기존 step 발견, 실행 관측 unknown; 신규 step/native dispatch 0회. |
| EX-D04 | 현재 B에 A의 늦은 candidate/stopped가 도착 | B record/ticket/head 불변; commit/publish/release 0회. |
| EX-D05 | 같은 candidate checkpoint를 반복 제출 | 기존 결과 재대사; commit·후속 phase 소비 최대 1회. 다른 outcome은 거절. |
| EX-D06 | checkpoint의 commit 전/후·최종 phase record 전/후·retirement 전/후 각각 crash | owned edits와 origin phase 보존; 최종 완료/대기 record read-back 전 ticket release 0회. candidate_ready는 다음 검증을 호출하지 않고 design_done/implementation_done 또는 정확한 correction 종점까지 진행. |
| EX-D07 | active write 중 intake/policy/spec/head가 바뀜 | accepted anchor와 edits 보존; 영향받는 review/implementation 의무 유지, old evidence 전달 0회. |
| EX-D08 | spec가 없거나 symlink/untracked/oversized | candidate_ready여도 설계 미완료; dependent implementation 0회. |
| EX-D09 | read-only reviewer가 head/spec/dirty state를 변경 | review 결과 거절; verification/merge 승인 0회. |
| EX-D10 | verification output을 가진 서버가 재시작 | stale review acceptance 무효; fresh verification와 review 전 delivery 0회. |
| EX-D11 | needs_decision write 중 질문이 필요 | checkpoint read-back 뒤 실제 질문 단계; private 원문 public publication 0회. |
| EX-D12 | exact/old/foreign/empty/generic resolution, 판본·변경 탐지, provenance 소실, native 알림, 아래 정상/유실/수정 fixture | 유효한 native 원본·위임·exact semantic pair이면 정상 재개. immutable ref나 별도 first-send flag를 강제하지 않음. 알림/userMessage/clientId/모델 주장으로 권한·실행·적용 승격 0회. source 소실의 fallback·payload 재생성·중복 semantic 적용/배정 0회. 정상 수신·수정은 아래 다음 행동까지 진행. |
| EX-D13 | admitted call과 Pause 경합, 전송 직전/직후 원격 위임·답변 변경 | 적용된 barrier 이후 또는 철회를 관측한 뒤 신규 영향 효과 dispatch 0회. 이미 전송된 요청의 늦은 commit은 원래 intent로 read-back하고 다음 효과 보류. local lock이 원격 writer까지 배제한다고 가정하지 않음; stopped 보존 예외의 push/close/delete 확대 0회. |
| EX-D14 | 실제 종료 미확인/confirmed stopped/never dispatched 조합 | 정확한 positive evidence일 때만 좁은 stopped checkpoint; unknown은 ticket 유지. |
| EX-D15 | CP verify_only/decision_apply/checkpoint_only가 각 종점에 도달, legacy runtime도 연결 | 협상된 capability와 effect ceiling 집행. decision_apply는 exact pair 뒤 끝나고 fresh attempt 0회; checkpoint_only의 write candidate_ready는 원 phase 완료 뒤 다음 검증/배정/전달 0회. failed/review phase 미지원은 효과 0회. 기존 다섯 MCP의 continuation 의미는 유지. |
| EX-D16 | publish/PR/merge/close 각각 응답 후 read-back 전 장애 | matching result는 재사용, unknown은 보존, 다른 identity는 거절; 중복 효과 0회. |
| EX-D17 | 외부효과가 세 번 실패/unknown, restart 후 요청 횟수 확인/미확인 | 기존 budget 보존; count 미확인을 0으로 초기화하지 않음, 네 번째 자동 요청 0회. 동일 append-only 재시도도 bounded, unknown mutable PATCH retry 0회. authorized replan도 원래 효과 먼저 대사. |
| EX-D18 | unsupported native start/stop/lookup이 개별적으로 반환 | qualified 기능만 표시·사용; SDK fallback·local journal·가짜 success 0회. |
| EX-D19 | stale/forged/duplicate required job·provider review | 정확한 producer/SHA/latest semantics만 인정; green 이름만으로 merge 0회. |
| EX-D20 | exact merge 후 pending/failed/unknown/success 및 newer rerun | 네 상태 구분; failed 진단, unknown 보류, success에서만 completion; repeat merge 0회. |
| EX-D21 | merged 정책 변경과 unmerged 정책 변경 | narrow completion-only는 실제 owned merge에만 적용; 신규 구현/publish/merge 0회. |
| EX-D22 | 부분 전달 뒤 취소, closed Issue cleanup pending, active label 유실, partial provider inventory | 전달한 결과·증거 보존, 남은 책임 재발견 또는 orphan/unknown; repeat delivery·zero-active/complete/Quit 추정 0회. |
| EX-D23 | 높은 priority가 human/CI wait, self-update/refresh/reopen, missed tick, unresolved ticket 유무 | 독립 작업은 선택 가능; self-update·refresh만으로 Hydra 추가 model 호출 0회, tick 수만큼 task 생성 0회. native 예약 자체 비용은 별도. verified complete reopen만으로 재실행 0회; unknown ticket이면 host writer 추가 0회. |
| EX-D24 | public record에 task ID/path/prompt/secret sentinel 및 unknown JSON key | allowlist 거절·safe error; public payload/log에 private sentinel 0개, transcript persistence 0회. |
| EX-D25 | 새 binding의 attempt anchor 발행 후 정상 서버 restart, 원문·binding 불변 | 같은 GitHub anchor/comment ID/digest/source/contract로 정확한 책임 복원; 새 attempt·새 binding·중복 dispatch 0회. 기존 unresolved native 실행은 별도 관측한다. |
| EX-D26 | anchor 또는 binding comment 수정·삭제·중복, source/contract 불일치 | 일반 candidate checkpoint/new effect hold, edits·pending intent 보존; 최신 comment 자동 채택·진행률 초기화 0회. exact confirmed-stopped의 기존 좁은 보존만 허용. |
| EX-D27 | attempt anchor POST 성공 뒤 응답 유실, complete/partial lookup 각각 | complete의 정확한 1개 anchor 재사용, partial/unknown은 hold; 두 번째 POST·ticket 할당·dispatch 0회. 원본으로 성공이 확인되면 정상 단계로 진행 가능. |
| EX-D28 | post-merge infrastructure 실패, 허용/미허용 rerun, 요청 응답 유실·이미 running | 허용된 exact run만 bounded 요청/read-back; 중복 요청·권한 없는 rerun 0회. newer valid success면 실제 완료 경로로 전진. |
| EX-D29 | 같은 원래 merge의 실제 코드 결함, 중복 wake·repair 생성 응답 유실·restart | WR key/author/read-back으로 repair Issue 하나만 재사용; partial lookup·미위임은 hold/정확한 결정. old PR 재병합·무조건 새 Issue·자동 rollback 0회. |
| EX-D30 | 위임된 코드 결함 repair가 회귀 TC·review·protected merge·post-merge를 성공 | 원래 실패 증거를 유지하며 repair revision으로 해당 요구의 후속 책임 해소, goal의 다음 요구/정리로 전진. 원래 SHA 성공을 별도 요구하면 그 조건만 유지. |
| EX-D31 | paused/stopped의 기본 continuation·명시적 exact cleanup 요청, owner/보존/공유 참조 변경·ACK 유실·restart | 기본 정리 0회, 유효 별도 요청은 해당 자원만 실제 정리·read-back. admission bytes/revision 불변, 업무 배정/전달/close 0회. unknown/foreign/active/미보존은 유지하며 재시작 뒤 원래 효과 대사 전 삭제 재전송 0회. |

EX-D12는 같은 suite 안에서 다음 고정 fixture를 사용한다. 의미 해석은 수용/대체가 명시된 fixture로
주고 D가 자연어 판단을 채점하지 않는다. 음성 사례는 바꾸려는 guard 외의 위임·소유·head·spec을
모두 유효하게 두며, 동일 진입점의 정상 control이 실제 다음 행동까지 진행해야 PASS다.

| variant | 고정 oracle |
| --- | --- |
| 최초/호출 전 restart | durable exact proposal 및 실제 미호출 근거에서 context→receipt→pinned resume UUID→한 assignment. 가상 first-send flag 불필요. POST/PATCH 직전·직후가 구별되지 않는 crash 창은 별도 unknown oracle이며 public 0개만으로 미호출을 발명하지 않음 |
| context/receipt 응답 유실·late 동일 POST | 같은 author/key/exact body는 한 semantic pair, 표시 pin은 결정적. 물리 중복을 성공적으로 접고 추가 semantic 적용/assignment 0회. 같은 key의 다른 body는 conflict |
| trusted pair와 outsider 복제 혼합 | 확인된 service ID+login의 후보만 fold/conflict 대상으로 사용. outsider의 같은 key/다른 body는 제외하고 정상 재개; pinned trusted ref 불일치와 provider actor 미확인은 각각 invalid/unknown |
| complete 0·partial·budget 미확인 | 0을 미적용 증거로 바꾸지 않음. 동일 append-only와 known remaining budget에서만 bounded retry, count unknown은 read-back/진단. raw body 재생성 0회 |
| resume PATCH 유실 | exact new record면 동일 resume UUID로 정상 전진; old/partial record면 retry/새 UUID/새 assignment 0회. 뒤늦게 matching record가 확인되면 같은 책임에서 전진 |
| paused 답변→restart→Resume | 같은 Q/A와 선택을 원본에서 재발견, paused 신규 dispatch 0회. 같은 project의 명시 Resume 후 현재 기준 확인→정상 다음 write 행동→candidate_ready checkpoint. 이미 retired된 old step 거절만으로 PASS 불가 |
| 명시 답변 수정 4시점 | 공개 전/context만/resolved 미소비/소비 뒤 각각 §7.3 대체·replan을 사용해 수정된 다음 행동까지 진행. 옛 pair/edits 보존, old selection의 신규 배정 0회 |
| 읽기 직후 원격 수정·Pause | 이미 보낸 효과와 이후 guard를 분리. 원래 intent로 read-back 후 새 영향 효과 보류; mutable 원격 source에 atomic 보장 발명 0회 |
| 원본 소실·위조·autoResolution·UI 소실 | 범위에 맞는 unknown/미해결 유지. public human marker fallback·가짜 권한·새 질문 반복 0회. 동일 source가 복구된 정상 fixture에서는 재개 가능 |

판단 평가 `EX-L01`은 충분한 설계와 일부 완료된 구현을 주고 정확한 미충족 요구·TC만 선택하는지,
`EX-L02`는 내부 구현 선택과 제품 계약 변경을 구분해 필요한 질문만 하는지, 답변의 수용/대체 의미를
현재 위임과 연결하고 private 원문을 복사하지 않은 exact 공개 제안을 준비하는지 평가한다.
독립 평가자는 요구 누락·중복 구현·기준 약화·무의미한 wake를 실패로 판정한다. fixture oracle,
prompt/model/revision을 고정하고 실제 판단 평가와 deterministic replay를 분리한다.

| 관측 ID | 실제 설치/외부 환경에서 확인할 결과 |
| --- | --- |
| EX-O01 | 실제 지원 표면에서 exact step↔task/turn을 연결하고 응답 유실 뒤 원본으로 재발견. task ID는 public에 없음. |
| EX-O02 | 동일 native 작업의 중단 요청과 실제 ended를 구분하고 restart 뒤 중복 실행 없이 원 phase를 재개. |
| EX-O03 | 실제 필요한 같은 질문→원격 답변→paused 상태의 controller restart/복원→같은 project의 명시 Resume→현재 근거로 safe semantic pair→pinned fresh attempt의 실제 행동과 candidate_ready checkpoint. 실제 native 원본·GitHub 결과·Pause dispatch 경계를 별도 증거로 확인하며 인위적 질문/다른 chat 재답변으로 대체하지 않음. |
| EX-O04 | 서로 다른 두 프로젝트 계약에서 기존 설계를 따르는 구현·TC·review·protected delivery·post-merge를 동일 경로로 완료. 허용된 fixture에서 terminal post-merge 실패→단일 repair→해당 요구의 실제 후속 충족도 확인하며 원래 실패 증거를 보존. |
| EX-O05 | 실제 소유 worktree/task/schedule 보존·정리와 닫힌 Issue discovery, cleanup 실패 후 재시작 대사. paused/stopped에서 명시적 정리 요청만 실행되고 admission이 그대로이며 기본 continuation/무관 자원은 영향받지 않음을 확인. |
| EX-O06 | 기존 native re-entry가 실제 허용된 다음 결과를 진행하며 unchanged wait는 조용히 유지. one-shot 종료 뒤 불필요한 예약 책임 없음. |

## 12. 구현 완료의 경계

이 계약의 구현 완료에는 source/contract TC, 기존 suite 회귀, 독립 spec·code/security 검토,
최종 revision의 필수 CI가 필요하다. native integration 완료에는 EX-O01–O03, 운영 완료에는
EX-O04–O06과 전체 v1.0.0의 다른 계약 증거가 필요하다. `NOT RUN`·`BLOCKED`·unsupported를 성공으로
합산하지 않는다. install·merge·one-shot 시연 각각만으로 목표 완료를 선언하지 않는다.

상세 구현은 현재 책임을 유지하는 작은 변경으로 한다: 기존 identity/전이 TC 확정 → 새 control-plane
명령의 효과 상한과 legacy 호환 → provider qualification 결과 연결 → recovery/discovery 통합 → 실제 운영 증거.
공통 runner 전면 재작성, 영속 데이터 복제, 자동 scheduler 추가는 이 계약에 포함되지 않는다.

## Shared-installation project admission

P02's explicitly enabled STDIO installation profile can delegate project Pause and
explicit Resume to all agents sharing that connection. It does not authenticate
human intent or grant host control, native turn control, decision application or
workflow effects. A separate current admission_set(running) command is still required;
answer reception, wake, retry and ordinary continuation cannot issue an implicit
Resume. Host Pause/Stop remains dominant. Revoking the profile does not clear a
project's Pause or terminate native work. Preserve exact expectations and original
effect read-back; the profile adds no command journal or lifecycle mirror.
