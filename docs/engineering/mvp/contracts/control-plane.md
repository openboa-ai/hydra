# Control plane: projection과 안전한 명령

Status: Design contract, revision 11, 2026-10-25. P06 pre-workspace continuation compatibility.

상위 계약은 [SDLC 통합 설계](../../../architecture/sdlc.md)다. 이 문서는 W3/W7의
wire contract, 관측·화면·명령·호환·TC를 소유한다. native 연동 qualification 이전의
설계이며 API의 존재, 구현 수용, 테스트 실행 또는 설치 환경에서의 성공을 선언하지 않는다.

### P17 admission source compatibility

The admission `SourceValue` retains `revision`, `global_mode`,
`project_overrides` and `gate_reason`. It adds optional `default_project_mode`,
whose only accepted values are `running` and `stopped`. Absence means the existing
version-1 running default. A version-2 admission source declares `stopped` and
does not fabricate missing stored overrides. Producers and strict Python, Rust
and TypeScript consumers use that default when validating effective admission.
The trusted connection-config path remains private and is absent from this value.

This closes the source representation needed by PC's existing explicit-stopped
rule; it does not change operating authority. Legacy source bytes remain valid.
An older strict consumer rejects the new source field rather than interpreting
it with an unsafe running default. Profile activation requires the matching
consumer; legacy schema-2 control rejects the connection profile before mutation.

## 1. 목적·책임·범위

| 항목 | 계약 |
| --- | --- |
| 목적 | 사용자가 Hydra에서 목표부터 결과·남은 책임까지 확인하고, 각 정본에 안전하게 명령한다. 같은 사실을 두 곳에서 수정하지 않는다. |
| 책임 | GitHub가 작업·설계·전달 사실, Codex가 private task·질문·실행·예약, 기존 provider가 자원 사실을 소유한다. Hydra는 조회·연결·admission·효과 전 확인을 책임진다. |
| 동작 | 원본별 observation을 받아 순수 projection을 만들고, 명령 시 필요한 사실만 새로 확인해 해당 소유자의 지원 경로로 실행한 후 read-back한다. |
| 실패·복구 | 누락·부분 조회·오래된 응답을 표시한다. 원본 확인 전 중복 효과·실행 종료·전체 완료를 선언하지 않는다. 캐시 소실은 원본 재조회로 복구한다. |
| 완료 | 아래 CP-D/CP-O 검증에서 원본 변경·부분 장애·재시작·역순 응답에도 사실과 제어 의미가 유지되고 두 일반 프로젝트를 구분해서 볼 수 있다. |
| 범위 | 기존 Python core + Rust bridge + TypeScript UI를 확장한다. tracker, inbox, transcript store, DB, event journal, scheduler 또는 모델 서비스는 추가하지 않는다. |

현재 `control.py`는 schema v2, 전체/프로젝트 admission, 인증된 progress 요약을 반환한다.
`progress.py`는 이미 조회한 결과의 안내를 만들며 실행 권한이 아니다. `operations.py`가
기존 admission 파일·lock을 소유한다. Rust와 TypeScript는 v2의 키를 엄격히 검사한다.
따라서 아래 확장은 **v3**로 도입하며 기존 v2 응답에 필드를 몰래 추가하지 않는다.

이번 revision은 project 설정의 CAS, 효과 직전 확인과 전송의 경계, 명령 유실·재시작,
첫 흐름의 결정 표시와 좁은 checkpoint를 구현·소비하는 계약을 구체화한다. 전체 UI나 native
역방향 제어가 이미 지원된다는 뜻이 아니다. 현행 구현 계약은 기존 GitHub workflow spec이며,
이 후보의 수용·구현·설치 관측은 각각 기록한다.
Revision 5는 이후 변경 P06/P13의 continue·verify_only와 P14/P15의 전달·정리 입력/결과,
현재 native assignment의 private 반환 profile을 추가한다. 기존 첫 세 명령 profile과
다섯 legacy 도구의 의미는 바꾸지 않는다. 각 후속 profile은 해당 구현·자격 확인 전에는 unsupported다.

### 필수 원격 경로와 공통 명령

원격 Codex → Hydra MCP → 이 공통 core를 필수 사용자 경로로 검증한다. 앱/CLI adapter도
같은 action의 의미와 guard를 보존한다. 원격에서 unavailable인 필수 기능을 로컬 버튼 성공으로
수용하지 않는다. 기존 다섯 도구와 예정 `hydra_command_v1`의 효과 한도는 §8이 소유한다.
일반 요구사항은 Codex native 질문이 담당하고 MCP의 입력 요청은 특정 호출의 누락 입력용이다.
답변·Plan·Goal을 CP에 별도 편집 가능한 데이터로 저장하지 않는다.

MCP 요청이 도달했다는 사실은 사람의 지시나 제어 권한의 증거가 아니다. 현재 source/transport가
보장하는 권한을 사용하며 caller가 전달한 `authorized`·task ID로 보완하지 않는다. 명령의 실제
적용·거절·unknown은 기존 reply 의미를 그대로 반환하고 unknown 후에는 원본을 먼저 대사한다.

## 2. 저장과 구현 책임

| 위치 | 영속 자료 | 메모리에만 존재하는 자료 |
| --- | --- | --- |
| Hydra host | 기존 설치/연결 설정, admission 설정, bounded owner ticket | 조회 결과, 연결 관계, pending command, page cursor |
| GitHub | 목표/작업 Issue와 native 관계, 작업 기록 계약의 수용 binding, 인증된 progress·effect intent, PR/check/review | Hydra가 조회한 화면용 발췌 |
| Codex | 기존 task/session, 원래 질문·답변, 지원되는 native 연결·예약 | 허용된 관측 결과와 private 원본 이동 참조 |
| 자원 provider | 기존 lifecycle 소유/보존/retirement 기록과 실제 자원 | Hydra의 해당 자원 관측 |

private Codex 정보는 local/native surface에서만 다룬다. GitHub effect intent에 task ID,
질문 원문, private 경로를 넣지 않는다. native binding을 소유 시스템에서 복원할 수 없으면
owner ticket만으로 대화를 재구성하거나 로컬 session journal을 추가하지 않는다.

- `control.py`: 조회 adapter 호출, source별 검증, projection 조립. 조회 함수에 mutation
  client/provider의 쓰기 기능을 전달하지 않는다. 정본을 찾지 못해도 Issue를 만들지 않는다.
- `progress.py`: 입력을 받아 안내만 산출하는 순수 함수. `next_action`은 제안이며 명령이 아니다.
- `operations.py`: 기존 admission 저장·직렬화와 effect guard. UI 전용의 별도 gate를 만들지 않는다.
- Rust bridge: 설치된 core의 고정 argv 호출, 출력/시간 제한, schema 검사, memory cache,
  typed command 전달, 허용된 원본 이동. 임의 shell·URL·filesystem 명령을 노출하지 않는다.
- TypeScript: 순수 reducer와 view. 화면의 버튼 비활성화는 편의이며 server guard를 대체하지 않는다.

Python CLI가 매 조회마다 종료되는 현재 구조를 유지해도 된다. 지속되는 조회 cache는 Rust
bridge 메모리에 두고 renderer에는 현재 화면에 필요한 자료만 전달한다. process 재시작 시
cache, request 순서, cursor는 사라진다. 이를 복구하기 위한 파일을 만들지 않는다.

현재 소스와 이번 변경의 접점은 다음과 같다. 아래 현재 상태는 source 관찰이며 설치본의 상태가 아니다.

| 현재 경계 | 이번 후보에서 필요한 변경 |
| --- | --- |
| `operations.set_mode`는 exclusive lock 안에서 revision 증가·atomic replace·read-back을 하지만 expected revision을 받지 않음 | 별도의 v3 CAS 진입에서 expected를 같은 lock 안에 대조하고 동일 mode는 무쓰기. 기존 파일 version과 legacy 호출 의미는 유지 |
| `control_result`와 CLI는 v2 action/target을 전달 | v3 typed command를 별도 handler로 전달. v2에 CAS 보장이 생겼다고 표시하지 않음 |
| `runner._effect`는 bounded callback을 shared admission guard로 감쌈 | 각 효과의 owner·source·ceiling 확인과 전송을 아래 경계로 연결. shared guard를 writer 간 mutex나 원격 transaction으로 부르지 않음 |
| Rust `mutate_locked`의 preflight는 등록 project를 확인하고 v2 action/target만 전송 | 사용자 관측의 expected를 끝까지 보존하고 read-back receipt와 현재 상태를 따로 검증 |
| TS `Observations`는 전체 v2 snapshot의 순서를 관리하며 DecisionView가 없음 | v3 source별 순서·종속 Fact 무효화·명령 feedback을 함께 구현 |
| `runtime_identity`는 startup package source·config·control path의 identity, `progress_hint`는 순수 안내 | identity는 대상 일치의 근거이고 설치 qualification이 아님. hint로 명령을 자동 실행하지 않음 |

[NC §2.4](native-capability.md#24-다음-qualification-단위-설치본과-호출-문맥-읽기)의
`native_context: NativeContextProbeV1`은 MCP `hydra_status`의 진단이다. CP v2/v3의 필드도,
SourceValue도 아니다. 그 진단을 CP에 그대로 주입하지 않으며 caller/task binding이나
native 제어 capability를 켜는 근거로 쓰지 않는다. 같은 runtime identity를 대조할 수 있다는
사실과 두 응답이 같은 wire라는 주장은 다르다.

## 3. 식별자와 공통 observation

JSON은 UTF-8, 정수는 `0..2^53-1`, 시간은 UTC RFC3339다. 필수 nullable 필드는 생략할 수 없다.
정규화된 wire의 알 수 없는 enum/key, 중복 key, 잘못된 날짜, 초과 길이는 `invalid_response`다. 아래 타입은
구현 언어를 강제하지 않는 wire 정의다.

```text
ResourceRef = { source, kind, id }
source = github | codex | resource_provider | hydra
Revision = { kind: opaque | monotonic, value: string }
Coverage = {
  state: complete | partial | unavailable,
  scope: string, returned_count: integer,
  total_count: integer | null, next_cursor: string | null,
  reason: Reason | null
}
Observation<T> = {
  key: string, resource: ResourceRef,
  revision: Revision | null,
  observed_at: timestamp | null, last_attempt_at: timestamp,
  availability: current | stale | unavailable | unsupported,
  coverage: Coverage,
  reason: Reason | null, value: T | null
}
EvidenceRef = { observation_key: string, revision: Revision | null }
Fact<T> = { value: T | null, evidence: EvidenceRef[], reason: Reason | null }
```

`key`는 한 연결 generation 안의 정규화한 resource/scope 식별자다. Github work key는
`github:<repository_numeric_id>:issue:<number>`이며 `owner/name`은 표시·주소용이다.
repository rename 시 numeric ID가 같아도 이전 URL을 그대로 명령에 쓰지 않고 현재 이름을
재조회한다. native ID는 qualified adapter의 opaque ID로만 취급한다. 제목·PID·경로 유사도로
task와 Issue를 연결하지 않는다. `Reason`은 `[a-z0-9][a-z0-9_-]{0,119}`의 bounded code다.

Revision의 `opaque` 값은 같음만 비교한다. Git SHA, ETag, 내용을 대표하는 digest를 사전순이나
숫자 크기로 비교하지 않는다. `monotonic`은 source가 같은 resource의 순서를 보장할 때만 쓴다.
GitHub 원문에 revision이 없으면 `null`이다. Hydra가 계산한 payload digest는 별도 command
precondition이며 source revision이라고 부르지 않는다. `observed_at`도 revision이 아니다.

| 상태 | `value`와 시간의 의미 |
| --- | --- |
| current | 해당 resource/scope를 성공적으로 관측했다. `observed_at` 필수. 이후의 무변경이나 다른 source와 원자적 일관성을 보장하지 않는다. |
| stale | 같은 연결에서 얻은 이전 value를 보존한다. `observed_at`은 원래 성공 시각, `last_attempt_at`은 최근 조회 시각이다. 값이 없으면 stale이 아니라 unavailable이다. |
| unavailable | 조회하지 못했거나 시작 전이다. `value=null`; `observed_at=null`; 원인을 `not_requested`, `access_denied`, `transport_failed`, `invalid_source` 등으로 구분한다. |
| unsupported | 설치된 adapter에 이 읽기 capability가 없다. `value=null`; 재시도가 해결책이 아니다. 기능 지원 여부를 timeout과 혼동하지 않는다. |

`coverage.scope`는 예를 들어 `repo:101;managed-work;open+closed;filter:v1`처럼 조회한
집합을 명시한다. 서버가 모두 반환했어도 필터가 일부면 그 작은 scope에 대해서만 complete다.
목록의 `partial`은 페이지·상한·권한·부분 오류를 포함하며 알려진 prefix를 보존한다.
단일 resource 조회는 `scope=resource:<id>`, 성공 시 complete/1이다. 404는 삭제와 권한 상실을
구별할 수 있을 때만 `source_missing`으로 판정한다. `unavailable`을 빈 성공 목록으로 바꾸지 않는다.

`Fact`는 source 사실 또는 검증된 사실에서 유도한 UI 값이다. 모든 값에 필요한 EvidenceRef를
붙인다. 같은 key여도 새로 수용한 observation마다 Fact를 다시 계산한다. revision이 null이거나
같다는 이유로 이전 Fact를 재사용하지 않는다. EvidenceRef는 **현재 ProjectionV3 또는 §8의
CommandReplyV1 안의** observation을 가리키며 다른 request/binding에 이식할 수 없다. source가 부분/unknown이면 그 사실에 의존하는
Fact도 unknown이지만 독립 source의 Fact는 유지한다.

## 4. v3 projection payload와 상태 축

```text
ProjectionV3 = {
  schema_version: 3, runtime: RuntimeIdentityV1,
  binding_epoch: string, request_id: string, assembled_at: timestamp,
  observations: Observation<SourceValue>[],
  projects: ProjectView[], work: WorkView[], relations: RelationView[],
  page: Coverage, capabilities: Capability[], retry_hints: RetryHint[],
  request: CommandResult | null
}
```

`retry_hints`는 아직 구현되지 않은 v3 조회 경계의 개정이며 기존 v2·`StandardCommandReplyV1`·
`Observation`의 필드 집합을 바꾸지 않는다. 세 v3 producer/consumer가 함께 수용하기 전까지
이 필드를 생략한 v3를 호환 성공으로 처리하지 않는다.

```text
RetryHint = {
  observation_key: string, scope: string,
  after_seconds: integer, basis: provider | fallback
}
```

모든 key는 필수다. 힌트가 없으면 빈 배열이다. `observation_key`는 같은 frame의 실제
제한/실패 관측을 가리키고 `scope`는 해당 adapter가 정한 provider/connection의 요청 제한
범위다. scope는 연결 generation 안의 256자 이하 opaque 값으로 같음만 비교한다.
실제 관측의 source와 scope를 함께 key로 써서 서로 다른 provider를 합치지 않는다.
표시할 Issue의 제목·본문·모델 제안으로 범위를 만들지 않는다. 같은 credential을 공유하는
GitHub 요청처럼 제한 범위가 공유되면 해당 scope의 자동 조회를 함께 대기하되 정상 관측과
local admission을 실패로 덮지 않는다. source나 credential이 다른 연결에 힌트를 이식하지 않는다.

`after_seconds`는 조립 시점의 **남은 대기 시간을 올림한** 0 이상 safe integer다.
`basis=provider`는 검증한 `Retry-After` 또는 primary-limit reset 등의 실제 응답 메타데이터에서
얻은 값이다. 명시된 0과 미확인은 다르다. header를 읽지 못한 것을 provider=0으로 만들지 않는다.
`basis=fallback`은 관측한 제한 오류에 적용하는 공개된 adapter 재시도 정책이며 source 사실이
아니다. GitHub는 알려진 provider 대기보다 먼저 요청하지 않고, 유효한 대기 정보가 없으면
최소 60초 이후부터 증가하는 bounded backoff를 사용한다. 정상 poll 간격도 하한으로 유지한다.
GitHub fallback의 연속 실패 대기는 60→120→240→480→900초이며 다섯 번의 자동 재시도 뒤에는
같은 scope의 자동 조회를 멈추고 명시적 복구 조회를 기다린다. provider가 알려준 더 긴 대기는
이 fallback 상한으로 줄이지 않는다. 다른 source나 같은 scope의 무관한 조회 성공은 실패 횟수를 지우지 않는다. 실패한 조회 또는
제한 원본의 실제 회복을 확인한 경우만 해당 실패 횟수를 해소한다.
이 값과 정상/실패 event열을 adapter·Rust·TS TC에 고정한다. raw headers·오류 본문·token은 wire에 넣지 않는다.

bridge/renderer는 실제 응답 수신 시 단조 시계로 대기를 시작하고 같은 cached frame을 다시
보여주는 것으로 대기를 줄이거나 늘리지 않는다. 더 엄격한 같은-scope 힌트는 보존하며 다른
source의 성공·수동 Refresh·화면 복귀로 provider 대기를 우회하지 않는다. sleep/clock skew는
freshness를 무효화하지만 남은 provider 대기를 지우는 근거가 아니다. 이 자료는 메모리 수명만
가지며 admission·실행·source revision·명령 권한이 아니다. serializer가 record prefix를 줄일 때도
남겨 둔 힌트의 관측을 함께 보존하며 유실/손상 힌트를 즉시 재조회 허가로 바꾸지 않는다.

`RuntimeIdentityV1`은 현재 package/version/code/config/control binding identity를 그대로 쓴다.
`binding_epoch`는 bridge process 시작과 binding 변경 시 발급하는 메모리 UUID다. persistent
session ID가 아니며 재시작을 넘어 같다고 가정하지 않는다. `request_id`는 bridge가 발급한
조회 UUID로 echo한다. `assembled_at`은 조립 시각이며 모든 source의 관측 시각을 덮지 않는다.

SourceValue는 ResourceRef.kind로 선택하는 닫힌 union이다. 원본의 전체 JSON을 실어 보내지 않는다.

| kind | 허용 value 필드 |
| --- | --- |
| repository | `numeric_id`, `full_name`, `url`, `contract_ref`(path/revision 또는 null) |
| issue | `number`, `title`, `state`, `url`, `work_kind`(goal/work/null), `parent_refs`, `requirement_refs`, `description_excerpt`, `description_truncated` |
| progress | `issue_ref`, `attempt_id`, `phase`, `native_step`, `head`, `contract_revision`, `branch`, `expected_head`, `expected_base`, `published_head`, `wait_reason`, `next_action`, `pending_action`, `pr_ref`, `completion_refs`, `cleanup_state` |
| pull_request | `number`, `url`, `state`, `head`, `base`, `merge_commit`, `required_check_refs`, `review_refs` |
| check | `producer`, `name`, `head`, `status`, `conclusion`, `url` |
| review | `producer`, `head`, `state`, `unresolved_count`, `url` |
| native_task_metadata | 아래 최소 읽기의 `task_ref`, `reported_status` |
| native_history_page | 아래 최소 읽기의 `task_ref`, `turns`, `page` |
| native_task | `task_ref`, `assignment_ref`, `execution`, `question_ref`, `schedule_refs`, `open_ref`; 각 의미를 검증한 adapter만 생성 |
| native_schedule | `schedule_ref`, `task_ref`, `status`, `next_wake_at`, `open_ref` |
| resource | `resource_ref`, `owner_ref`, `activity`, `preservation`, `retirement`, `open_ref` |
| admission | `revision`, `global_mode`, `project_overrides`, `gate_reason` |
| ownership | `state`, `scope_digest`, `step_nonce`; no PID/name-based inferred owner |

참조 필드는 ResourceRef, 복수 참조는 배열이다. source 필드에서 unknown을 표현할 수 없으면
nullable로 둔다. 기존 progress field 이름과 enum은 현재 parser의 의미를 유지한다. 위 표는
표시 allowlist이며 GitHub progress schema의 교체가 아니다. `description_excerpt`는 이미
공개·열람 허용된 원문의 처음 4,096 code points, `title`은 최대 512, URL/open_ref는 최대
2,048, ID/reason은 최대 256/120이다. 나머지는 원본으로 이동해 읽는다. native 질문 원문을
GitHub excerpt에 넣지 않는다. source payload에 없는 선택적 사실은 null이며 모든 key는 필수다.
예외적으로 `requirement_refs`, `spec_refs`, `parent_refs`, `goal_refs`는 [작업 기록 계약](work-records.md)의
RequirementRef와 IssueRef/GoalRef를 그대로 사용한다. 이 타입을 ResourceRef의 opaque ID로
손실 변환하지 않는다. observation 조회용 ResourceRef와 제품 요구의 정밀 참조를 구분한다.

### SourceValue의 구현용 타입

앞의 표는 key 집합의 정본이며 다음은 그 key의 타입이다. nullable은 key 생략을 허용하지 않는다.
UInt는 0..2^53−1 JSON 정수(bool 제외), Positive는 1 이상의 UInt, Code는 `Reason`과 같은
bounded public code, Ref는 ResourceRef다. ExecutionView는 이 절의 실행 축과 같은
{state: unobserved/running/ended, active_count: UInt 또는 null}다. source가 읽지 않은 선택 사실과 목록은 null이며
조회로 확인한 빈 목록만 `[]`다. 표에 없는 임의 object/JSON payload는 받지 않는다. 닫힌 kind 집합은 value=null인
unavailable/unsupported 관측에도 적용한다. native_context는 이 관측 kind에 추가하지 않는다.

| kind | 타입과 추가 제약 |
| --- | --- |
| repository | numeric_id: Positive; full_name: canonical owner/name; url: string(2048); contract_ref: null 또는 {path: string(512), revision: git_sha 또는 null}. numeric ID가 없으면 repository value 자체를 unavailable로 두고 숫자를 추측하지 않는다. |
| issue | number: Positive; title: string(512); state: open/closed; url: string(2048); work_kind: goal/work/null; parent_refs: (IssueRef 또는 GoalRef)[] 또는 null; requirement_refs: RequirementRef[] 또는 null; description_excerpt: string(4096) 또는 null; description_truncated: bool 또는 null. 설명을 읽지 않았으면 두 description 필드는 모두 null이며, 실제 빈 본문을 확인한 경우만 빈 excerpt/false를 쓴다. |
| progress | issue_ref: Ref(kind=issue); attempt_id/native_step: UUID 또는 null; phase/wait_reason/next_action/pending_action/cleanup_state: Code 또는 null; head/contract_revision/expected_head/expected_base/published_head: git_sha 또는 null; branch: 기존 owned branch validator 또는 null; pr_ref: Ref 또는 null; completion_refs: Ref[] 또는 null. 기존 parser가 제공하지 않는 cleanup_state 등은 null이다. |
| pull_request | number: Positive; url: string(2048); state: open/closed; head/base/merge_commit: git_sha 또는 null; required_check_refs/review_refs: Ref[] 또는 null. provider가 merged임을 확인하기 전에는 synthetic merge_commit_sha를 merge_commit에 넣지 않는다. |
| check | producer: Ref 또는 null; name: string(512); head: git_sha 또는 null; status: Code; conclusion: Code 또는 null; url: string(2048) 또는 null. producer는 실제 app/actor locator이며 표시 이름을 identity로 쓰지 않는다. |
| review | producer: Ref 또는 null; head: git_sha 또는 null; state: Code; unresolved_count: UInt 또는 null; url: string(2048) 또는 null. source Code는 표시 값이고 approved/완료 자격은 별도 검증한다. |
| native_task_metadata/native_history_page | 아래 최소 profile의 정확한 타입. metadata/history resource 및 native_task/native_turn/native_message locator의 source는 codex다. |
| native_task | task_ref: Ref(kind=native_task); assignment_ref/question_ref: Ref 또는 null; execution: ExecutionView 또는 null; schedule_refs: Ref[] 또는 null; open_ref: string(2048) 또는 null. |
| native_schedule | schedule_ref: Ref(kind=native_schedule); task_ref: Ref 또는 null; status: Code; next_wake_at: timestamp 또는 null; open_ref: string(2048) 또는 null. |
| resource | resource_ref: Ref; owner_ref: Ref 또는 null; activity/preservation/retirement: Code 또는 null; open_ref: string(2048) 또는 null. qualified adapter만 해당 Code의 의미를 해석한다. |
| admission | revision: UInt; global_mode: running/paused/stopped; project_overrides: canonical repository name→같은 mode의 object(최대 1024개); gate_reason: Code 또는 null. |
| ownership | state: free/absent/owned/busy/native/unknown; scope_digest: SHA-256 또는 null; step_nonce: UUID 또는 null. free/absent만으로 execution=ended나 active_count=0을 만들지 않는다. |

Revision.monotonic.value는 leading zero 없는 음이 아닌 십진 문자열(0 포함)이다. 문자열을
JSON number나 부동소수로 바꾸지 않고 길이·숫자 의미로 비교한다. opaque revision에는
이 순서를 적용하지 않는다. key/coverage.scope는 최대 512자, ref ID는 최대 256자다.
native metadata/history에는 revision=null만 허용한다. stale 값은 원래 observed_at을 유지한다.

ProjectView의 source_refs는 Ref[]이고 WorkView의 evidence_refs 및 Fact.evidence는
EvidenceRef[]다. goal_refs는 작업 기록 계약의 정확한 GoalRef
`{repository_id, issue_number, source_digest}` 배열이다. 두 ID는 Positive,
source_digest는 위임 당시 범위를 고정한 소문자 64hex다. digest를 버리거나 현재 원문으로
덮지 않고 opaque Ref로도 바꾸지 않는다. parent_refs 안 GoalRef에도 같은 세 필드를 보존한다.
spec_refs/requirement_refs는 RequirementRef[]다.
알려진 Fact에는 같은 frame의 current·complete 관측과 일치하는 revision을 가진 근거가
필요하다. unknown Fact는 null과 reason을 갖는다. typed DecisionView를 표현할 수 있다는
사실은 아직 미확인인 decision source mapping이나 실제 원격 답변 qualification을 완료시키지 않는다.

ProjectView는 `repository_ref`, `goal_refs`, `work_refs`, `admission`, `execution`,
`attention_refs`, `coverage`, `source_refs`를 갖는다. WorkView는 `issue_ref`, `goal_refs`,
`spec_refs`, `requirement_refs`, `readiness`, `stage`, `admission`, `execution`, `wait`,
`decision`, `delivery`, `result`, `cleanup`, `next_action`, `task_refs`, `resource_refs`, `evidence_refs`를 갖는다.
RelationView는 `from`, `to`, `kind`, `evidence`이며 kind는 parent/depends_on/implements/
verifies/delivers다. 원본에 없는 관계를 projection이 추정해 저장하지 않는다.
현재 parent/dependency는 GitHub 원본 관계를 표시하고 작업 binding의 `delegated_goal`은
수용한 위임의 근거로 구분한다. 현재 parent의 변경을 위임 변경으로 자동 적용하지 않으며,
`work_source=legacy_issue|github_native`, native 경로의 `hydra-work:v2`와 `input_contract`,
priority의 원본 선택과 unavailable 처리는 작업 기록 계약을 따른다. 이 선택을 CP에서 다시
정의하거나 legacy source를 native adoption 완료로 표시하지 않는다.

아래 상태는 Fact로 출력한다. 상태가 미확인이면 `value=null`과 reason을 반환하며 UI는
이를 “미확인”으로 표시한다. null과 enum unknown을 중복해서 쓰지 않는다.

| 축 | 알려진 value | 판정 규칙 |
| --- | --- | --- |
| readiness | 아래 ReadinessView | 작업 기록 계약의 actionable/needs_info/propose/quarantined를 그대로 사용. 별도 상태 머신을 만들지 않는다. |
| admission | `allowed`, `paused`, `stopped` | global blocked가 project에 우선. project override를 지우지 않는다. 설정의 running을 실제 실행 중으로 표시하지 않는다. |
| stage | `prepare`, `design`, `implement`, `verify`, `deliver`, `observe`, `complete` | 인증된 progress와 작업 계약에서 매핑. 알 수 없는 기존 phase를 complete로 바꾸지 않는다. |
| execution | `{state: unobserved/running/ended, active_count: integer|null}` | 발행된 assignment는 unobserved. 실제 provider/task 관측만 running/ended의 근거가 된다. |
| wait | `{kind: human/external/resource, owner_ref, wake_ref, reason}` 또는 `none` | progress와 실제 질문 identity를 대조. native 질문을 읽지 못하면 공개 가능한 대기 이유만 표시하며 답변 완료를 추측하지 않는다. |
| delivery | `candidate`, `published`, `merged`, `post_merge_verified`, `deployment_observed` | exact head/base와 producer를 검증. 앞 단계만으로 뒤 단계를 추정하지 않는다. 불필요한 배포를 요구하지 않는다. |
| result | `incomplete`, `complete`, `cancelled` | acceptance와 증거로 판정. Issue closed, green CI, Stop만으로 complete가 되지 않는다. |
| cleanup | `not_required`, `pending`, `complete` | 소유 자원·task·schedule과 남은 책임을 대상별로 대조. 전체 대상 범위를 모르면 null. |

`next_action`은 `{code, target_ref, rationale_excerpt, evidence}` 후보이며 code는 현재
progress hint와 작업 계약의 허용 enum을 따른다. 자유문을 실행 payload로 쓰지 않는다.
목표 달성은 화면 집계가 변경하지 않으며 요구별 증거를 평가하는 목표 완료 경로가 소유한다.

### 최소 native 읽기: 관측과 결정 근거 분리

한 native read 응답에서도 task metadata와 대화 page는 서로 다른 범위다. 다음 두 관측으로
분리해 최근 기록의 partial이 현재 metadata를 가리거나, metadata의 complete가 전체 대화의
complete로 승격되지 않게 한다. 새 외부 API 이름이 아닌 v3 adapter의 출력 타입이다.

```text
NativeTaskMetadataValue = {
  task_ref: ResourceRef, reported_status: string
}
NativeHistoryPageValue = {
  task_ref: ResourceRef,
  turns: [{
    turn_ref: ResourceRef, reported_status: string,
    started_at: timestamp | null, completed_at: timestamp | null,
    messages: [{message_ref: ResourceRef, message_type: userMessage | agentMessage}]
  }],
  page: {order: newest_first, limit: positive integer, has_more: boolean}
}
```

`task_ref`는 검증된 provider/connection/host/task, turn/message ref는 해당 task/turn/item에
귀속된 opaque 참조다. display name·cwd·preview로 연결하지 않는다. source의 같은 ID가
다른 task에 나타나도 같은 자원으로 합치지 않는다. resource kind는 위 union의 관측 종류,
value 안 ref의 kind는 각각 `native_task`, `native_turn`, `native_message`로 고정한다.
locator kind가 새 SourceValue observation variant를 선언하는 것은 아니다. task마다 metadata key 하나,
history는 task와 query/page scope별 key를 갖고 binding/조회 seq 규칙을 그대로 적용한다.

- metadata 성공은 해당 task metadata에 한정한 complete/1이다. history는 반환 turn 수와
  `total_count=null`, `partial`을 사용한다. `has_more=true`이면 reason은 `more_pages`,
  false여도 전체 원본의 보존·질문 항목 coverage를 증명하지 못하므로 `history_scope_unverified`다.
  typed 질문 source를 별도로 검증하기 전에는 끝 page도 질문 부재의 근거가 아니다.
- `Coverage.next_cursor`가 source page cursor의 유일한 저장 위치다. has_more=true이면
  비어 있지 않은 cursor, false이면 null이어야 한다. cursor는 provider/task/query/binding에
  묶인 메모리 값이며 디코딩하거나 source revision으로 해석하지 않는다. 새 조회로 페이지를
  합쳐도 원자적 snapshot으로 간주하지 않는다. 한 page의 중복 locator는 거절한다. page 간
  중복은 같은 task/turn/type이면 locator 하나로 합칠 수 있으나 다른 귀속/type은 상충이다.
  본문을 보존하지 않는 이 profile은 locator 일치를 본문 무변경으로 해석하지 않는다.
- source timestamp가 Unix seconds이면 adapter가 범위·타입을 검증해 UTC RFC3339로 변환한다.
  boolean/소수/잘못된 값은 거절하며 nullable을 0으로 채우지 않는다. `reported_status`는 최대
  120자의 `[A-Za-z][A-Za-z0-9_-]{0,119}`에 맞는 단순 표시용 source 문자열이다.
  source의 `active`나 turn의 `completed`를 Hydra의
  실행·완료 enum으로 변환하지 않는다. 알 수 없는 code도 실행권한이나 종료 증거가 되지 않는다.
- 이 최소 profile의 revision은 null이다. updatedAt·조회 시각·내용 digest를 revision으로
  만들지 않는다. 같은 item ID/내용의 반복 관측은 해당 조회 사이의 일치만 보여준다.
- message에는 locator와 type만 둔다. 본문·title·preview·phase·cwd·tool arguments/results·
  reasoning은 출력/캐시에 넣지 않는다. source의 userMessage role이나 clientId는 사람의
  인증 identity/권한이 아니다. 읽지 않은 field나 제외한 tool item을 질문 없음으로 해석하지 않는다.
- 별도 work/attempt binding 근거가 없으면 observations에서 읽은 task만 표시하며
  `WorkView.task_refs`나 assignment/ownership 관계를 채우지 않는다. 일반 task metadata나
  일부 turn만으로 실행 ended, active_count=0, ticket 해제, 완료/정리 완료를 도출하지 않는다.
- 이 두 관측만 있는 경우 DecisionView의 네 Fact는 모두 null,
  reason=`decision_provenance_unverified`다. question=none, answer=awaiting/received,
  acceptance=accepted, application=applied로 채우지 않는다. 검증된 별도 decision source가
  있으면 그 source의 Fact를 사용하며 낮은 수준의 읽기 결과로 덮지 않는다.

adapter는 지원되는 source 결과를 typed allowlist로 추출한다. upstream의 추가 필드나 표시하지
않는 item 종류는 저장 없이 제외할 수 있으나, envelope/schema version·대상 identity·허용 필드의
타입은 검증한다. 잘못된 identity는 두 관측을 모두 거절한다. metadata가 유효하고 history만
손상됐다면 metadata는 유지하고 history만 stale/unavailable로 만든다. 정규화된 v3 consumer가
unknown key를 거절하는 규칙과 upstream 전체 JSON의 무조건 거절을 혼동하지 않는다.

raw 입력은 source adapter 경계에서 1 MiB 상한을 적용하고 초과·잘림·손상 시 성공으로
projection하지 않는다. 지원 transport가 읽기 byte 상한을 집행할 수 없으면 해당 adapter의
실사용 qualification은 미완료다. `includeOutputs=false`나 source의 출력 길이 옵션만으로
본문·도구 인자가 제거된다고 가정하지 않는다. raw 응답·예외를 log/fixture에 저장하지 않으며
fixture는 같은 형태의 합성 값으로 만든다. 정규화 결과와 cache 상한은 §6을 따른다.

이 profile의 유용한 결과는 **어떤 native task/turn/message 위치를 읽었는지**와 task가 보고한
상태다. Hydra로 원본 결과를 전달하는 지원 경로와 caller/owner binding은 [NC](native-capability.md)의
별도 qualification을 요구한다. 모델이 제출한 유사 JSON을 trusted observation으로 받지 않는다.

### 첫 흐름의 private DecisionView

`WorkView.decision`은 다음 메모리 projection이다. 질문이 없는 작업은 원본 조회로 이를
확인한 `question.value=none`을 사용한다. 조회 실패를 질문 없음/답변 대기로 바꾸지 않는다.

```text
DecisionView = {
  question: Fact<none | {
    source_attempt_id: string, task_ref: ResourceRef,
    question_ref: ResourceRef, revision: Revision | null
  }>,
  answer: Fact<
    { state: awaiting } |
    { state: received, answer_ref: ResourceRef, revision: Revision | null }
  >,
  acceptance: Fact<pending | accepted | conflict | invalid>,
  application: Fact<{
    state: pending | context_recorded | applied,
    context_ref: ResourceRef | null, resolved_ref: ResourceRef | null
  }>
}
```

- 각 `value=null`은 미확인이다. 질문이 없으면 종속 Fact도 null과 `not_applicable`을 쓴다.
  답변의 미관측을 `awaiting`으로 만들지 않으며, source가 답변 부재를 확인한 경우만 awaiting이다.
- acceptance는 선택한 같은 answer ref/revision과 현재 spec/policy/authority 근거에 묶인다.
  수정된 답변에 옛 accepted를 붙이지 않는다. accepted는 admission 또는 실행 허가가 아니다.
- context_recorded는 exact context만 read-back된 부분 적용이다. applied는 선택한 답변과
  exact context/resolved 쌍의 연결·내용·순서를 확인한 경우다. 단순 resolved 발견은 부족하다.
  source 상충/부분 조회는 reason과 null로 표시하고 이전 관측은 stale로 보존한다.
- 실제 재개는 기존 admission·assignment·execution 근거로 나타낸다. 별도 resumed 상태를
  만들거나 decision applied를 native 실행으로 표시하지 않는다.

`application.value`가 pending이면 두 ref는 null, context_recorded이면 context_ref만 non-null,
applied이면 둘 다 non-null이어야 한다. 이것은 원본 연결을 검증한 뒤의 값이다. GitHub 목록에서
하나를 발견하지 못했다는 이유로 pending을 합성하지 않는다. source 불확실성은 null이며,
확인된 순서·내용 상충은 acceptance의 conflict/invalid와 해당 reason으로 나타낸다.

| 관측한 사실 | 표시·허용되는 해석 | 아직 확인하지 않은 사실 |
| --- | --- | --- |
| 같은 질문에 received, project paused | 답변 수신 · 일시정지로 적용 대기 | 답변 채택, context 게시, 실행 재개 |
| accepted, application pending | 현재 기준으로 답변 채택 · 적용 대기 | admission 해제, 결정 게시, 새 assignment |
| context_recorded | 결정 일부 기록 · 해소 확인 대기 | resolved 성공·전체 적용 |
| applied, project running | 결정 적용 확인 · 다음 실행 확인 대기 | 새 assignment 또는 native 시작 |
| 새 exact assignment만 확인 | 다음 작업 배정 · 실제 실행 미확인 | running/완료 |
| 동일 assignment의 qualified 실행 관측 | 해당 실행의 running/ended | 전체 task 종료·목표 완료·정리 완료 |

새 source 관측마다 질문→선택 답변→현재 기준/권한→적용 pair의 종속성을 다시 계산한다.
답변 판본·source attempt·선택·binding 중 하나가 바뀌면 종속 accepted/applied를 이전 값에서
이어 붙이지 않는다. 늦은 응답은 §7 순서 규칙으로 버리고, 부분 장애는 영향받는 Fact만 null로
만든다. 이전 원본 관측을 보여줄 때는 stale임을 명시하며 현재 결정 상태와 합치지 않는다.
Resume 응답 직후 다시 Pause가 적용돼도 적용 receipt와 현재 gate를 각각 표시한다.

이 타입은 private adapter/consumer의 요구 계약이다. 질문/답변 원문·공개 전 초안·새 영속
자료를 UI에 추가하지 않는다. Fact의 evidence를 공급할 실제 source observation과 허용 필드
매핑은 [NC §2.1](native-capability.md#21-질문과-재개를-위한-원본-연결)에서 아직 NOT RUN이다.
위 최소 읽기는 결정 근거의 mapping을 대체하지 않는다. decision source의 매핑을 §4의 닫힌
SourceValue union에 반영하고 encoder/consumer가 함께 검증하기 전에는
이 축을 활성화하지 않는다. 구현 전에 남은 계약 항목이며 generic JSON이나 임의 reason 문자열로
대체하지 않는다. 현행 strict v2는 그대로 유지하고 협상된 v3 경계에서만 연결한다.

### 원본 Issue와 해석된 작업을 함께 보기

등록되지 않은 일반 Issue도 허용된 조회 범위에서 발견하면 제안 후보로 보여준다. 자유 형식,
다른 template, 외부 contributor의 내용이라는 이유로 가치 있는 요청을 숨기지 않는다. UI는
“원본 요청 / 해석한 목적·요구 / 부족한 정보 / 실행 가능 조건”을 구분하고 모두 원본 revision에
연결한다. `needs_info`는 빠진 의미와 해결 주체를, `propose`는 채택·위임이 미확정인 제안을 뜻한다.
`actionable`도 특정 다음 행동의 가능성이며 모델이 임의 실행권한을 부여하지 못한다. `quarantined`는
위험한 지시 부분을 실행 입력에서 격리한 상태다. 유용한 요구는 별도로 제안할 수 있다.

해석 결과는 transient projection 또는 작업 계약의 기존 공개 가능한 기록을 사용한다. 원문과
추출 결과를 별도 로컬 inbox/DB에 저장하지 않는다. 해석된 requirement에는 원문 위치와 source
revision을 붙이며, 새 관측에서 원문이 바뀌면 stale interpretation으로 표시해 재검토한다.
외부 내용의 유용한 요구는 보존하되 “권한을 무시하라/secret을 읽어라” 같은 지시는 실행 권한으로
받지 않는다. 문서 순서·헤더가 아니라 의미 충족과 별도 trust/authority 검증이 실행 binding의 조건이다.

원문 전체를 자동 복제하지 않으면서 구체적으로 보여줄 해석 필드는 다음으로 고정한다.

```text
ReadinessView = {
  disposition: actionable | needs_info | propose | quarantined,
  source_ref: ResourceRef, source_revision: Revision | null,
  interpretation_ref: ResourceRef | null, binding_ref: ResourceRef | null,
  extracted: {purpose_excerpt: string | null,
              requirement_refs: RequirementRef[], scope_excerpt: string | null},
  missing: [{code: Reason, detail: string, owner_ref: ResourceRef | null}],
  authority: confirmed | missing | unknown,
  trust_reason: Reason | null
}
```

`detail`과 각 excerpt는 1,024 code points 이하의 안전한 표시 텍스트다. transient 해석의
`interpretation_ref=null`을 허용하지만 그 해석만으로 command를 승인하지 않는다. managed work와
candidate discovery는 별도 scope/budget을 써서 외부 Issue가 많아도 진행 중 책임을 숨기지 않는다.

## 5. Native actor와 capability 경계

```text
Capability = {
  source: github | codex | resource_provider | hydra,
  operation: string,
  state: available | unsupported | unavailable,
  actor: core | native_actor | provider,
  qualification_ref: string | null, reason: Reason | null
}
```

W1에서 실제 검증한 connector/actor binding과 installed runtime이 일치할 때만 capability를
available로 둔다. 설정 boolean, source test, 다른 세션의 tool 이름은 qualification이 아니다.
native tool을 Codex task 안에서 사용할 수 있어도 standalone Mac app이 그 결과를 읽을 수
있다는 뜻은 아니다. app에 도달하는 **지원되는** 인증/private read 경로가 없으면 native-task
관측은 unsupported, 실제 실행은 미확인으로 표시한다.

native actor에 요청할 때는 기존 task/assignment의 qualified binding, 원래 위임, 실제 호출
권한을 확인한다. 지원되는 수신 경로가 없으면 원본 이동만 제공하며 UI가 가상의 resume/interrupt를
dispatch하지 않는다. v1.0.0에 필요한 관측·제어를 만족할 수 없으면 W1/W7은 BLOCKED다.
unsupported를 표시하는 mock이 통과해도 전체 v1.0.0의 실행 능력이 입증된 것은 아니다.

## 6. 메모리 상한·freshness·목록의 완전성

다음 v1.0.0 기본값은 구현 시 경계 TC를 갖는다.

- 응답 하나는 현재 Rust `MAX_OUTPUT`과 같은 1 MiB, 등록 project는 기존 최대 1,024개다.
  work summary는 repository별 128, host 합계 512, detail cache는 최대 16개다.
- bridge cache는 serialized payload 합계 4 MiB LRU, renderer는 현재 표시 중 최대 1 MiB다.
  오래된 detail을 먼저 버린다. serializer 중간을 잘라 보내지 않으며 완전한 record의 prefix와
  partial coverage를 반환한다. header조차 들어가지 않는 잘못된 입력은 invalid_response다.
- 상한에 닿으면 “총 512개”나 “active=0”으로 표시하지 않는다. `returned_count`와 “나머지 미확인”을
  보여주고 원본 adapter가 pagination을 지원하면 opaque cursor로 다음을 읽는다. cursor는
  같은 binding/query scope에서만 유효하며 이전 연결의 cursor는 거절한다.
- local admission/ownership은 15초, GitHub/native/resource의 현재 상태는 60초가 표시 freshness
  기준이다. 수신 후 경과는 단조 시계로 확인한다. TTL 안에서도 효과 전 원본 재조회를 생략하지
  않는다. clock skew, sleep/resume, binding 변경은 새 관측을 요구한다.
- 수동 Refresh, 화면 복귀, 대상 명령 완료 시 필요한 source를 재조회한다. 보이는 동안 local은
  최대 5초에 한 번, remote는 60초에 한 번이다. 비가시 상태는 UI poll을 중단한다. poll은 모델
  호출/native wake를 만들지 않는다. source의 rate limit/retry-after를 우선한다.

기존 managed-work discovery와 closed+active lookup을 사용한다. 일반 Issue가 많다는 이유로
진행 중 work가 조회 예산에서 밀려나면 안 된다. 화면에서 제외된 closed work도 cleanup marker와
owner ticket/provider의 대조 대상이다. cache eviction은 책임 종료가 아니다. 정확한 전체
active_count와 Quit 허용에는 등록 대상의 전체 coverage, 기존 owner, 잔존 worker, 미해결
assignment, 관리된 예약 ingress를 모두 현재 사실로 확인해야 한다. cache 부재는 원본 부재가 아니다.

P12의 조회 비용 검증은 기존 상한을 제품 처리 용량 주장으로 바꾸지 않는다. 화면에 필요한
source와 실제 효과가 의존하는 read set을 나누고, 지원되는 batch/조건부 GET은 identity·query·
권한 범위가 같은 cache에만 적용한다. 304는 scope 전체 조회나 authority 갱신의 대체물이 아니다.
두 complete 관계 읽기도 원자적 snapshot 보장이 아니다. effect 직전 WR/EX guard는 유지한다.
조회 호출 수·지연·rate limit·반환 bytes를 작은/상한/partial 사례에서 측정하고 retry-after와
bounded backoff를 지킨다. 보이지 않는 프로젝트를 미확인으로 두는 것과 책임을 잊는 것을 구분한다.

## 7. UI와 reducer

같은 projection으로 다음 보기를 제공한다. 별도 작업 편집 tracker/inbox를 만들지 않는다.

| 보기 | 필수 내용 | 조작 |
| --- | --- | --- |
| 전체 | project별 목적, 실제 진전 증거, 실행, 대기, 필요한 판단, source별 freshness/coverage | project/goal/detail, Refresh, global admission |
| goal | 원문의 목적·기준·설계, 요구→작업→증거, 미충족 요구와 다음 행동 | 원본 이동, 위임 내 typed 작업 등록, 기존 operating task 이동 |
| work | 원본 요청과 해석·readiness, 설계 revision, 단계, task/workspace, TC/CI/review, delivery/result/cleanup | 지원되는 단계 조작, 원본 이동, 필요한 재대조 |
| 판단·제어 | 실제 질문/판단 주체/영향, admission과 native 실행의 별도 표시, 남은 자원 책임 | qualified 질문 이동, 대상 admission, qualified stop/cleanup |

GitHub 본문은 text로 렌더링한다. backend가 ResourceRef에서 허용된 origin/path로 URL을
해결해 연다. Issue 본문이나 native 결과를 임의 URL/command 실행 권한으로 쓰지 않는다.
private 상세를 볼 수 없으면 이유와 허용된 원본 이동을 표시한다. unsupported를 숨겨 Hydra에서
모든 것을 관측하고 있다고 주장하지 않는다.

Issue/PR/log/README 미리보기는 text가 기본이다. Markdown을 지원해도 HTML, script,
javascript/data URL, iframe, 외부 이미지·stylesheet 등 자동 remote resource를 렌더링하지 않는다.
링크된 문서의 미리보기는 허용된 source connector와 현재 repository/권한 범위에서만 읽는다.
본문에 들어온 임의 URL을 backend가 fetch하지 않는다. 원본 이동은 사용자의 명시적 조작과
허용된 ResourceRef 해결을 거치며, 표시·미리보기만으로 자동 네트워크 호출이나 코드 실행이
발생하지 않아야 한다. source의 접근 권한이 사라지면 재조회해 접근 불가로 바꾼다.

Reducer state는 `{binding_epoch, source_slots, selected_ref, pending_commands, feedback}`다.
source slot마다 `latest_issued_seq`, `latest_settled_seq`, observation을 둔다. 이벤트는
`read_started`, `read_succeeded`, `read_failed`, `command_started`, `command_result`,
`binding_changed`, `clock_resumed`, `selection_changed`의 닫힌 union이다.

1. binding 변경 시 모든 source cache와 pending 표시의 binding을 무효화한다. 새 read 전까지
   enabling action을 막되 이전 command의 효과를 미실행으로 추정하지 않는다.
2. source별 seq로 오래된 성공/실패가 새 결과를 덮지 못하게 한다. opaque revision은 대소 비교하지
   않는다. 같은 revision을 새로 조회한 경우 freshness는 갱신할 수 있다.
3. failed read는 같은 source의 이전 값을 stale로 만들고 다른 source는 유지한다. runtime/schema/
   binding 자체가 잘못되면 이전 표시를 명령 근거로 사용하지 않는다.
4. command failure/unknown은 별도 feedback에 보존하며 무관한 성공 poll로 지우지 않는다.
   같은 대상의 read-back으로 해결되면 해소한다. 알림 닫기는 미확인 효과를 해결하지 않는다.
5. pending command의 같은 effect는 이중 전송하지 않는다. remote read lane은 Stop의 mutation
   lane을 막지 않는다. 비활성 이유를 표시하고 optimistic applied로 실제 값을 바꾸지 않는다.

## 8. Command envelope와 공통 guard

```text
CommandV1 = {
  command_schema: 1, request_id: UUID,
  binding_epoch: UUID | null,
  action: Action, target: TypedTarget,
  expected: {
    runtime_key: string | null, admission_revision: integer | null,
    source_checks: [{resource: ResourceRef, revision: Revision | null,
                     actionable_digest: sha256 | null}],
    assignment: {attempt_id: string, step_id: string, head: string,
                 contract_revision: string, spec_revision: string | null} | null
  },
  effect_key: string | null, parameters: ActionParameters
}
CommandResult = {
  request_id: UUID, action: Action, target: TypedTarget,
  outcome: applied | waiting | rejected | unknown,
  reason: Reason | null, effect_refs: ResourceRef[],
  observed_refs: EvidenceRef[], receipt: CommandReceipt | null,
  required_next: none | refresh | reconcile | open_source
}
CommandReplyV1 = StandardCommandReplyV1 | NativeCommandReplyV1
StandardCommandReplyV1 = {
  command_schema: 1, runtime: RuntimeIdentityV1,
  binding_epoch: UUID | null,
  request: CommandResult, observations: Observation<SourceValue>[]
}
CommandReceipt =
  { kind: admission, readback: EvidenceRef } |
  { kind: checkpoint, assignment: ExactAssignment, outcome: CheckpointOutcome,
    checkpoint_head: string, progress_ref: ResourceRef,
    step_retired: true, ticket_released: true } |
  { kind: decision, source_attempt: UUID, round: positive integer,
    intent_ref: ResourceRef, context_ref: ResourceRef, resolved_ref: ResourceRef,
    resume_attempt: UUID } |
  ContinueReceipt | VerificationReceipt | VerificationReviewReceipt |
  PublicationReceipt | DeliveryReceipt | CleanupReceipt
```

Action/Target/Parameters는 아래의 tagged union이다. 누락된 target을 host 전체로 바꾸지 않는다.
caller의 `authorized=true`나 임의 shell/URL/prompt를 받지 않는다. backend가 실제 자격·위임·
project allowlist를 확인한다. 이 v3 surface는 기존 다섯 native tool 이름과 exact assignment
계약을 교체하지 않는다.

`CommandReplyV1`은 명령의 검증 가능한 결과를 운반한다. `observed_refs`는 같은 reply 안의
observation만 가리킨다. bridge가 이를 ProjectionV3에 포함할 때 필요한 observation도 함께
넣고 현재 source slot과 혼동하지 않는다. MCP reply는 전체 ProjectionV3를 가장하지 않는다.
따라서 §3의 EvidenceRef 범위는 projection 또는 이 명령 reply 하나이며 다른 응답의 ref를
그대로 이식하지 않는다. reply에 native_context 진단을 추가하지 않는다.

ExactAssignment는 expected.assignment의 non-null 타입이며 CheckpointOutcome은 아래 좁은
checkpoint payload의 outcome이다. 첫 구현의 세 operation에서 applied는 해당 receipt를
필수로 갖고 나머지 결과는 receipt=null이다. receipt는 요청에 귀속된 handler의 read-back 결과이며
새 source record가 아니다. checkpoint의 assignment/outcome은 이 호출에서 exact 원본과 대조한
입력이고 checkpoint_head는 실제 보존 후 head다. retirement/ticket 확인 뒤에만 두 true를 보낸다.
decision의 refs와 resume_attempt는 EX의 인증된 intent와 실제 게시 결과에서 얻는다. 임의 code,
generic JSON, 요청 값 echo만으로 receipt를 만들지 않는다. Rust/TS는 request의 target/assignment/
operation과 일치 여부 및 receipt의 필수 필드를 검사한다. 이 memory receipt로 DecisionView source
mapping, 원본의 영속 복원 또는 실제 native 시작을 입증하지 않는다.

| Action | TypedTarget / Parameters | 효과 경로·필수 사실 |
| --- | --- | --- |
| admission_set | `{kind:host}` 또는 `{kind:repository,repository_id}` / `{mode:running\|paused\|stopped}` | operations의 기존 store/lock, runtime/config binding, 설정 revision. running은 native 시작이 아니다. |
| work_create | `{repository_id}` / `{draft_ref: WorkCreateDraftRef, draft_digest: sha256}` | [작업 기록 계약 §8](work-records.md)의 immutable WorkCreateDraft, 실제 위임, 기존 intent·중복 조회. `effect_key`는 draft의 `create_key`와 일치해야 한다. |
| workflow_step | `{repository_id,issue_number}` / 아래 operation별 typed payload | 기존 core guard와 exact assignment, 원래 spec/policy/intake/head, 아래의 operation별 effect ceiling. |
| native_control | task/assignment ref / resume,interrupt | W1 qualified actor와 native ownership. 미지원이면 dispatch하지 않는다. |
| cleanup | 아래 CleanupTarget / preserve,retire,archive,remove_schedule | 명시된 자원 한 개, 원래 provider, 실제 비활성·보존·exact owner·공유 책임. 일반 continuation과 별도인 좁은 정리 효과. |
| open_record | ResourceRef / none | 현재 binding과 원본 identity. 외부 효과의 위임으로 사용하지 않는다. |

`WorkCreateDraft`, `WorkCreateDraftRef`, draft digest의 정규화는 작업 기록 계약이 소유한다.
부모 목표와 공개할 exact title/body·binding 제안은 draft 원본에 있고 command에서 다시 받지 않는다.
backend는 해당 qualified source reader로 draft를 읽어 digest, `target_repository_id`, `create_key`를
대조한다. 변경·잘림·중복·권한 부족·미지원 native lookup이면 생성하지 않는다. cache의 이전
본문이나 모델이 다시 생성한 본문으로 대체하지 않는다. 같은 create_key에 다른 draft payload는
`rejected/creation_payload_conflict`이며 조회·dispatch 모두 원래 의도에 귀속된다. 생성 후에는
실제 GitHub Issue가 작업 정본이고 draft는 그 최초 명령의 근거다. 별도 draft DB를 두지 않는다.

`actionable_digest`는 adapter가 명시한 정규화 field 집합의 SHA-256이다. Issue는 bound intake,
PR은 head/base/state, native는 exact task/assignment/control state를 사용한다. timestamp,
표시 excerpt, 우연한 배열 순서를 쓰지 않는다. digest는 화면의 stale 여부를 탐지할 뿐 provider의
atomic compare-and-set 기능을 만들어내지 않는다.

Guard 순서는 (1) schema/allowlist/binding, (2) 실제 권한·위임, (3) 필요한 source 재조회와 expected
대조, (4) exact owner/assignment, (5) admission, (6) intent와 기존 효과 대사, (7) guarded dispatch,
(8) read-back이다. 무거운 remote read 중에는 admission lock을 보유하지 않으며 기존 core의
bounded effect 직전에 다시 guard한다. 필요한 precondition이 변경됐거나 미확인이면
rejected/unknown이며 요청을 새 target으로 자동 변환하지 않는다.
후속 publish/deliver/cleanup의 유실 복구에서는 기존 효과의 read-only 대사를 새 mutation의 stale
판정보다 먼저 할 수 있다. 이는 현재 권한·admission·source guard를 통과하지 않은 새 dispatch를 허용하지 않는다.

Source가 conditional mutation을 제공하면 사용한다. 없으면 기존 owner 직렬화와 전송 직전
대조가 제공하는 실제 보장 범위를 명시한다. 외부 writer와의 경합을 안전하게 처리할 수 없는
파괴적 명령은 unavailable로 두고 원본의 지원되는 조작으로 안내한다.

### 첫 명령 경로와 정확한 입력

다음은 구현할 경로이며 현재 endpoint가 아니다. reader 단위는 기존 다섯 MCP 도구를 유지한다.
좁은 명령 단위에서만 여섯 번째 `hydra_command_v1(command: CommandV1) -> CommandReplyV1`을
추가한다. native caller와 향후 CLI/Rust bridge가 공통 versioned handler를 사용하며,
handler가 operation별 controller 경로를 선택한다. 임의 메서드 이름이나 legacy tool name을
payload에서 받아 호출하지 않는다. 새 endpoint의 존재는 모든 action의 구현을 뜻하지 않는다.
내부 effect_limit은 handler가 `checkpoint_only_v1` 또는 `decision_apply_v1`로 고정하며
caller 필드로 받지 않는다. controller의 하위 효과 경로도 이 제한을 유지한다. 공통 handler가
아닌 기존 MCP 함수를 호출하고 이름만 바꾸는 구현은 이 계약을 충족하지 않는다.

- bridge 호출은 현재 bridge의 non-null binding_epoch를 대조한다. native MCP 호출은
  binding_epoch=null이며 지원 transport의 실제 호출 문맥과 runtime/현재 project/원본 assignment를
  별도로 확인한다. null이 다른 surface의 binding 검사를 생략하는 옵션이 아니다.
- runtime_key는 기존 identity의 `[version,code_digest,config_digest,control_binding_digest]`를
  공백 없는 JSON 배열로 직렬화한 값이다. 하나라도 null이거나 identity_reason이 있으면 enabling
  명령을 허용하지 않는다. 화면 preflight가 이 값이나 admission_revision을 새 값으로 교체하지 않는다.
  **project Pause/Resume과 두 workflow operation은 runtime_key가 반드시 non-null**이다.
  null 예외는 아래 trusted host 전체 제한 명령뿐이다. native transport의 null binding_epoch가
  project의 runtime/config/control binding 비교를 생략하지 않는다.
- repository_id/issue_number는 양의 정수다. numeric ID→현재 repository 이름은 qualified GitHub
  조회와 현재 등록 allowlist에서 해결한다. 설정에 ID 사본이나 이름 유사도 mapping을 추가하지 않는다.
- assignment는 server가 반환한 exact attempt/step/head/contract_revision/spec_revision을 그대로
  대조한다. spec 미생성 단계의 null은 기존 assignment의 null과 같아야 한다. 현재 반환하지 않는
  policy_revision/intake_digest를 caller에게 만들게 하지 않는다. server는 기존 인증 progress와
  project/accepted anchor에서 policy/intake를 재확인한다.
- source_checks의 revision은 원본이 제공한 값이다. null이면 adapter가 정의한 actionable_digest로
  해당 의미 변경을 검사한다. 해당 operation에 필요한 판본/변경 검출이 둘 다 없으면 실행하지 않는다.
  표시에 쓰는 title/summary/time에서 digest나 권한을 유도하지 않는다.

첫 admission/checkpoint 호출의 source_checks는 빈 배열이다. admission은 local CAS와 등록
identity를, checkpoint는 exact assignment와 server의 현재 progress/intake/policy anchor를
대조한다. projection에 없는 digest를 renderer가 만들어 제출하지 않는다. decision_apply의
source_checks는 proposal_ref 하나에 대해 qualified reader가 제공한 revision 또는 채택 내용의
변경 검출 digest를 담는다. 이 최소 reader의 exact 출력/정규화가 NC에서 검증되지 않았으면
decision_apply는 unsupported다. source_attempt의 공개 progress는 server가 별도로 재조회한다.
그 밖의 source_checks 조합은 이 첫 handler에서 invalid_command이며 향후 operation의 수용
계약 없이 임의 source를 fetch하지 않는다.
admission_set의 expected.assignment와 effect_key는 모두 null이다. 이 설정 연산에 외부
workflow effect key를 붙여 영속 중복 방지를 가장하지 않는다.

첫 흐름의 workflow payload는 다음 둘이다. command의 알 수 없는 key/operation/outcome은
`rejected/invalid_command`, 미구현 version/operation은 `rejected/unsupported_operation`이며
provider mutation을 호출하지 않는다. 다른 workflow operation의 payload는 별도 수용 계약과
capability가 있기 전까지 unsupported다.

```text
CheckpointOnly = {
  operation: checkpoint_only,
  outcome: candidate_ready | needs_decision | stopped,
  summary: string
}
DecisionApply = {
  operation: decision_apply,
  proposal_ref: ResourceRef,
  source_attempt: UUID, round: positive integer
}
```

checkpoint_only는 non-null expected.assignment와 현재 admission_revision을 요구한다.
effect_key는 `checkpoint:<attempt_id>:<step_id>`이고 summary는 기존 private summary와 같은
24,000 code points 이하이다. 처음 구현할 phase는 design/implementation/correction이며,
phase는 caller 입력이 아니라 현재 assignment에서 얻는다. review phase는 이 좁은 경로에서
unsupported다. summary는 GitHub payload·projection·공개 log에 넣지 않는다.
failed는 legacy에는 유효하지만 이 첫 좁은 operation에서는 `rejected/unsupported_outcome`이다.
실패의 correction 배정까지 좁은 checkpoint에서 자동 시작하지 않는다.

공통 handler → exact native controller binding/owner → 좁은 checkpoint 경로로 전달한다.
그 경로는 결과 기록/read-back, owned edits와 원 phase의 재시작 가능한 checkpoint 보존,
아래 원 phase의 완료/대기 기록, exact step retirement 및 matching ticket 확인까지 수행하고
반환한다. 기존 `_finish_design`, `_finish_implementation`, `_finish_correction`에서 **원 단계의
검증·완료 record만** 분리해 공유하며 전체 continuation 함수를 호출하지 않는다.

| outcome/원 phase | retirement 전 필수 record/read-back | 다음 명령까지 하지 않는 일 |
| --- | --- | --- |
| candidate_ready/design | 기존 scoped design 경로·내용·tracked 검사를 통과한 head, `phase=design_done`, `next_action=spec_review` | 설계 수용·review 배정/실행 |
| candidate_ready/implementation | owned checkpoint head와 accepted spec 변경 검사를 통과한 `phase=implementation_done`, `next_action=verification` | 검증·후속 review·publish |
| candidate_ready/correction | 기존 correction reason/attempt·원 completed phase·resume/origin 관계·remote expected head 검사를 보존한 완료 record | 새 correction·검증/통합·전달 |
| needs_decision/쓰기 phase | 재시작 가능한 원 phase, `wait_reason=product_decision`, `next_action=operator_decision` | 질문 해결·다음 배정 |
| stopped/쓰기 phase | 현재 exact stopped-preservation의 checkpoint와 대기 사유 | 종료 추측·자동 재개 |

분기는 phase 문자열만으로 고르지 않는다. 현재 assignment의 native_correction이 있으면
phase=design인 spec-only correction도 correction 완료 분기가 우선이다. 기존 spec_only,
origin/resume, reason/attempt, remote expected head를 유지하고 일반 design 완료로 바꾸지 않는다.
candidate_ready라도 scope/spec/원 phase 완료 조건이 충족되지 않으면 보존한 checkpoint와
기존 diagnose/replan 대기를 표시한다. 완료 record를 만들거나 임의 다음 phase로 전진하지 않는다.
필수 read-back에 실패하면 owner/ticket을 유지하고 부분 상태를 대사한다. 정상 candidate는
이 원 단계 완료까지 진행하므로 재질문이나 불필요한 Stop 없이 실제 진전과 checkpoint를 증명할 수 있다.
단순히 native_outcome을 지우고 반환하여 이후 begin이 같은 작업을 반복하게 만드는 구현은 불가하다.

`_candidate_result` 전체 호출, correction 후속 실행, `advance`, 새 assignment·review·publish·
merge·close는 금지다. `stopped` 문자열은 실행 종료 증명이
아니며 기존 exact stopped-preservation guard를 통과한 경우만 같은 좁은 예외를 사용한다.
paused에서 일반 checkpoint를 stopped로 자동 바꾸지 않는다.

decision_apply는 expected.assignment=null과 non-null current admission_revision을 요구하며
현재 source attempt의 progress와 source_checks의 지원되는 proposal 원본을 대조한다. effect_key는
`decision:<source_attempt>:<round>`다. private qualified reader가 proposal_ref를 다시 읽어
질문·선택한 답변·채택 판본/권한·exact public draft의 연결을 제공해야 한다. caller의 구조화된
제안은 입력이지 그 사실의 증명이 아니다. 실제 reader/원본 mapping이 없으면 unsupported다.
공통 handler → [EX §7](execution.md#7-질문결정다음-wake)의 decision resolver가 정확한 공개
intent/context와 resolved의 게시·read-back까지만 수행한다. context 자체가 intent인 EX 경로에서
receipt의 intent_ref와 context_ref는 같은 원본을 가리킨다. source attempt/round와
미리 정한 resume_attempt UUID는 해당 public intent가 소유하며 command에서 새 UUID를 받지 않는다.
EX가 같은 service actor/key/exact body의 physical duplicate를 하나의 의미상 효과로 대사한
경우 표시 ref는 그 계약의 canonical comment를 사용한다. 하나의 ref가 physical at-most-once를 뜻하지 않는다.
fresh attempt/ticket·개발·전달은 0회다. 이후 begin/continue가 공통 guard로 같은 intent의
resume_attempt를 소비한다. 해당 project-v2 최소 loader/guard와 기존 intake 호환은 EX가 소유한다.

Capability.operation은 `workflow_step.checkpoint_only`, `workflow_step.decision_apply`처럼
정확한 action/operation 쌍으로 광고한다. 각 controller·effect filter·원본 자격이 수용된 경우만
available이다. 범용 native_control이나 다른 operation을 함께 켜지 않는다. legacy 다섯 도구는
기존 의미를 유지하며 새 handler 실패 시 fallback 대상으로 사용하지 않는다.

좁은 경로에서 applied는 **해당 operation의** 모든 필수 read-back 완료다. 확인한 효과만
effect_refs에 넣고, 부분 완료는 waiting 또는 unknown과 확인한 refs를 반환한다. 반환할 수 없는
source 필드를 임의 SourceValue로 만들지 않는다. command 성공은 DecisionView의 private 원본
mapping, actual execution 또는 전체 결과 완료를 대신하지 않는다. retirement 후 old step/outcome의
정확한 근거가 사라졌다면 재요청을 이미 성공한 checkpoint로 판정할 수 없다. unknown으로 두고
원본을 대사하며 process-local consumed set만으로 재시작 후 성공을 복원하지 않는다.
이 old request의 귀속 미확인이 현재 work의 확인된 원 phase 완료까지 부정하지는 않는다.
current progress와 전체 guard가 다음 단계를 허용하면 별도 명시 continue가 정상 진행할 수 있다.
옛 checkpoint 재전송과 다음 lifecycle 명령을 같은 retry로 취급하지 않는다.

### 후속 continue·verify_only profile

아래 입력은 [P06](../changes/06-decision-resume/spec.md)과
[P13](../changes/13-verification-evidence/spec.md)의 구현 범위다. 첫 좁은 명령 구현만으로
활성화하지 않는다. 이 절이 typed profile의 정본이며 change spec에는 복제하지 않는다.

```text
CandidatePin = {attempt_id: UUID, head: git_sha, contract_revision: git_sha}
ProgressPin = {attempt_id: UUID, head: git_sha | null, contract_revision: git_sha, phase: string}
Continue = {operation: continue, progress: ProgressPin | null,
            reply_profile: standard_v1 | native_handoff_v1}
VerifyOnly =
  {operation: verify_only, stage: run, candidate: CandidatePin,
   reply_profile: standard_v1 | native_handoff_v1} |
  {operation: verify_only, stage: review_checkpoint, candidate: CandidatePin,
   outcome: candidate_ready | failed | needs_decision, summary: string,
   reply_profile: standard_v1 | native_handoff_v1}
ContinueReceipt = {
  kind: continuation, progress_ref: ResourceRef,
  attempt_id: UUID, head: git_sha | null, contract_revision: git_sha,
  boundary: progress_recorded | assignment_returned | existing_result_reconciled
}
VerificationReceipt = {
  kind: verification, candidate: CandidatePin, verdict: passed | failed,
  review: pending | accepted | failed | not_required | null,
  progress_ref: ResourceRef, evidence_refs: ResourceRef[]
}
VerificationReviewReceipt = {
  kind: verification_review, candidate: CandidatePin, assignment: ExactAssignment,
  review: accepted | failed | pending,
  progress_ref: ResourceRef, evidence_refs: ResourceRef[],
  step_retired: true, ticket_released: true
}
NativeCommandReplyV1 = {
  command_schema: 1, reply_profile: native_handoff_v1,
  runtime: RuntimeIdentityV1, binding_epoch: null,
  request: CommandResult, observations: Observation<SourceValue>[],
  handoff: {kind: native_assignment, assignment: NativeAssignment} | null
}
NativeAssignment = {
  repository: string, issue: positive integer, action: native_task,
  attempt_id: UUID, step_id: string, phase: string, head: git_sha,
  contract_revision: git_sha, spec_revision: git_sha | null,
  cwd: string, mode: string, prompt: string
}
```

NativeAssignment는 현행 native controller의 assignment 반환 필드를 그대로 타입으로 옮긴 것이다.
phase/mode/step 형식은 EX의 기존 허용 값과 validator를 사용하며 임의 phase를 받지 않는다.
새 task ID·resource ref나 호출자 identity를 만들지 않는다. 전체 reply는 기존 1 MiB 상한을 따르고
초과 시 잘라서 유효 assignment로 반환하지 않는다. 미확인 반환은 원본 assignment 대사 대상이다.

continue와 verify_only/run의 target은 `{repository_id,issue_number}`, expected.assignment=null,
source_checks=[], effect_key=null이며 runtime_key/admission_revision은 non-null current 값이다.
끝난 step을 active assignment로 꾸미지 않는다. caller가 임의 candidate digest·phase override·resume UUID·
effect ceiling을 넣을 수 없다. 각 실제 효과의 intent/idempotency는 기존 EX 경로에서 대사한다.

continue의 ProgressPin은 현재 CP progress의 실제 네 필드이며 phase는 기존 progress enum이다.
server가 원본을 재조회해 pin과 먼저 대조하고 다르면 `rejected/stale_progress`다. null은 조회로
확인한 미시작 상태를 기대하며 실제 record가 있으면 stale이다. 조회 불가는 record 없음이 아니다.
그 뒤 **같은 Issue의 현재 위임된 다음 행동**을 선택한다. server가 owner·intake/spec/policy/head와
native 결정 연결을 다시 읽고 기존 공통 begin/advance guard를 사용한다. pin이 맞아도 새로운
scope·철회된 권한·변경된 입력을 승인하지 않는다. consumer는 최신 pin으로 요청을 몰래 바꾸지 않는다.
pending assignment는 재사용/대기로 처리하고 새 owner를 만들지 않는다. 기존 위임 밖 새 scope는
자동 채택하지 않는다. receipt는 실제 progress read-back 또는 현재 controller가 반환한 exact
assignment와 연결한다. `assignment_returned`는 실제 Codex 실행 시작 증거가 아니다.

#### Pre-workspace continuation compatibility

A `null` ProgressPin expects a successfully observed absence of progress. An object
whose required `head` is `null` instead pins an existing pre-workspace record.
Attempt, phase, contract revision and nullable head must all match the current
original. Unavailable or incomplete reads establish neither condition. Do not
allocate a workspace or invent a commit merely to represent a dependency wait.

A ContinueReceipt describes the confirmed result after the operation. Its head
may be null only for `boundary=progress_recorded` backed by the actual pre-workspace
progress read-back. `assignment_returned` and `existing_result_reconciled` require
a Git SHA. CandidatePin, ExactAssignment, NativeAssignment, verification,
publication and delivery retain their existing non-null SHA requirements.

The submitted ProgressPin is a precondition, not an expected result. A valid
continuation may produce a different head or attempt, including when a dependency
closes or a selected decision is consumed. Consumers correlate the returned
receipt with the actual progress observation and exact request/target/runtime;
they do not compare post-state to the old input pin or silently rewrite that pin.
Schema compatibility does not qualify a continuation route: consumers that do not
yet support this capability keep their existing unsupported behavior.

Required deterministic cases cover an open dependency without workspace creation,
its repeated nullable pin, closure followed by a real SHA/assignment, stale
null/SHA/phase/attempt pins, absent versus unavailable progress, strict candidate
and assignment heads, and preservation of unsupported consumer gates.

verify_only는 current progress의 attempt/head/contract를 **요청한 CandidatePin과 먼저 대조**한다.
현재 accepted spec/intake/policy와 branch/base 경계도 기존 runner 검사로 확인한다. 다르면 `rejected/stale_candidate`이며
새 head로 바꾸지 않는다. registered verification·그 후보의 안전한 local checkpoint·독립 후보
검토만 허용한다. checkpoint가 head를 바꾸면 옛 후보 verdict를 재사용하지 않고 변경된 head에서
검증하지도 않는다. `waiting/candidate_changed`, receipt=null과 현재 원본을 반환하고 새 pin의
명시 명령을 요구한다. 같은 요청에서 candidate를 자동 refresh하지 않는다. 새 implementation·publish·PR·원격 review
요청·merge·close·자원 retirement는 0회다. 원래 위임의 broad continuation으로 fallback하지 않는다.

run의 verification receipt는 **그 호출에서 실제 수행한 검증 결과**와 같은 후보의 실제 review 근거만
담는다. 실행 완료나 verdict=passed를 후보 수용/전달 완료로 표시하지 않는다. 필수 review가
남으면 `waiting`과 review=pending/null, 이미 수행한 검증 receipt를 반환할 수 있다. 검증 실패는
verdict=failed로 명시하고 자동 correction을 시작하지 않는다. evidence_refs에는 실제 조회 가능한
원본만 넣으며 private process-local 결과에 가짜 URL/ref를 만들지 않는다. 그 경우 배열은 비어
있을 수 있지만 현재 invocation의 검증 관측은 필요하다. 재시작 후 receipt를 복원할 원본이 없으면
verdict를 재생성하지 않고 unknown으로 둔다. 현재 source에 연결되지 않은 임의 결과 JSON은 거절한다.

verify_only/review_checkpoint는 P13이 같은 후보의 독립 review를 완료하는 좁은 경로다. target과
runtime/admission은 run과 같고 source_checks=[]이나 expected.assignment는 **현재 exact live
change_review**다. CandidatePin의 attempt/head/contract와 일치하고 원본 spec_revision·owner·
read_only 범위를 대조한다. effect_key는 `checkpoint:<attempt_id>:<step_id>`다. summary는 기존
24,000 code points 이내 private 결과이며 공개 progress/receipt/projection/log에 복사하지 않는다.
`stopped`와 다른 phase는 이 variant에서 unsupported이며 기존 stopped 보존 경로를 대체하지 않는다.

native의 기존 review 결과 소비에서 검증·bounded outcome 기록과 원 단계 완료 부분만 분리한다.
현재 head/clean 상태·accepted spec·실제 검증 run의 pending_verifications와 review_steps 연결을
확인한다. 현재 두 cache의 `(repo,issue,head,policy)` key 일치만으로 같은 실행을 증명하지 않는다.
P13은 배정이 읽은 실제 invocation의 argv/result/output-digest 연결을 기존 private 메모리 수명 안에서
확인하고 같은 head의 다른 run과 구별한다. 이 연결이 없으면 proof 소실이다. 새 DB나 공개 run 자료는
만들지 않는다. accepted는 candidate_ready 문장만으로 만들지 않는다. 아래 final record를 read-back한
뒤 exact step retirement와 matching ticket release를 확인하고 반환한다. `_checkpoint` 전체,
`runner.step`, `_correct`, publish 또는 proof 소실 시 자동 새 review 배정 경로를 호출하지 않는다.

| 원본 결과/근거 | 원 단계 종점과 receipt | 다음 호출 전 금지 |
| --- | --- | --- |
| candidate_ready + 같은 실제 D run/독립 review/불변 후보 근거 | 기존 change_review_done·locally_verified 경계, review=accepted | publish·PR·전달·자원 정리 |
| failed | change_review_done와 review_findings/diagnose_review 대기, review=failed | correction 배정·실행 |
| needs_decision | change_review_done, resume_phase=change_review, product_decision/operator_decision 대기, review=pending | 질문·task 자동 생성, 결정 적용 |
| candidate_ready이나 D run/review_steps 근거 소실 | 기존 bounded outcome read-back·exact step 종료, verification_evidence_unknown/verification 대기, review=pending | accepted·현재 호출의 D PASS·자동 재검증/새 review |

마지막 행의 pending 사유는 공개 가능한 기존 progress reason/next_action에 남기며 원문이나 새
증거 저장소를 만들지 않는다. needs_decision은 D proof 소실 때문에 재검증 대기로 덮지 않고 원래
결정 대기를 유지한다. 현재 불변 후보가 확인되지 않으면 stale로 보류하고 step을 해제하지
않는다. 원본과 final record가 확인된 finished step만 종료할 수 있다. 퇴역 후 old step/outcome
귀속이 사라진 재전송은 unknown이며 새 step을 대신 종료하지 않는다. 이 variant는 별도의
VerificationReviewReceipt를 써서 이전 run의 D verdict를 이번 호출의 검증 결과로 포장하지 않는다.
receipt의 두 true는 실제 read-back 뒤에만 가능하며 pending/failed 판정을 accepted로 올리지 않는다.
성공적으로 이 좁은 완료를 기록하면 applied일 수 있지만 후보 수용 여부는 review 필드대로 표시한다.

native_handoff_v1은 **현재 native MCP 호출에 대한 private 반환**이다. 같은 `hydra_command_v1`의
typed reply이며 새 tool·원본·저장소가 아니다. 기존 controller의 assignment를 strict serializer가
검증해 반환하고 native caller가 EX의 exact assignment 계약으로 소비한다. verify_only의 handoff는
같은 pinned 후보의 독립 read-only review에만 허용하며 원 검토 범위를 넘는 쓰기 배정은 금지한다.
지원되는 독립 reviewer 전달이 없으면 검증을 마친 뒤 review 대기로 남긴다.
review assignment를 만들기 전에 지원되는 reviewer 전달 **및 review_checkpoint 완료 경로**를
확인한다. 둘 중 하나라도 없으면 생성 전 waiting/open_source다. 모든 caller에서 standard_v1만
선택했거나 exact assignment를 전달할 경로가 없으면 같은 원칙을 적용한다. review_checkpoint는
새 assignment를 만들지 않으므로 native profile에서도 handoff=null이다.
handoff가 있을 때 repository/issue는 요청 target의 현재 GitHub identity, attempt/head/contract는
실제 반환한 controller record와 일치해야 한다. verify_only는 CandidatePin과도 같아야 하며
mode=read_only와 허용된 candidate-review phase를 검사한다. 불일치 assignment를 반환하지 않는다.
선택한 native profile은 거절·대기에도 그대로 반환하되 실제 assignment가 없으면 handoff=null이다.
profile을 조용히 standard로 바꾸거나 placeholder assignment를 만들지 않는다. handoff가 있다는
이유만으로 outcome=applied나 review=accepted를 만들지 않으며 실제 명령 경계가 판정을 정한다.

`workflow_step.continue`, `workflow_step.verify_only.run`, `workflow_step.verify_only.review_checkpoint`,
`command_reply.native_handoff_v1`의 capability를
각각 qualification한다. caller의 profile 선택만으로 private 반환/실행 권한이 생기지 않는다.
bridge/renderer 경로는 native handoff를 지원하지 않으며 **assignment를 만들기 전에**
waiting/open_source로 반환한다. standard_v1은 기존 StandardCommandReplyV1과 같은 wire다.
bridge는 native profile 요청을 dispatch 전에 거절한다. native 전용 profile 응답이 잘못 도착하면
strict 거절하고 자체 안전한 unsupported feedback만 표시하며 handoff 내용을 renderer로 넘기지 않는다.
native assignment의 cwd/prompt는 ProjectionV3·renderer·cache·공개 log에 넣지 않는다. P12는 두 reply
profile을 strict하게 식별하고 native-only reply의 bridge 유입을 거절한다. 구형 strict reader에
필드를 몰래 추가하지 않으며 unsupported profile을 legacy 호출로 바꾸지 않는다.

### 후속 publish_candidate·deliver profile

[P14](../changes/14-protected-delivery/spec.md)가 아래 두 handler를 소유한다. 공통 envelope의
target은 `{repository_id,issue_number}`, expected.assignment=null, source_checks=[], effect_key=null이며
runtime_key/admission_revision은 non-null이다. reply는 StandardCommandReplyV1이다. 실제 위임·accepted
spec/intake/policy·candidate review·branch 소유권은 server가 원래 progress와 GitHub에서 다시 검사한다.
caller가 없는 digest·review 판정·권한을 만들지 않으며 좁은 요청을 legacy deliver/verify로 치환하지 않는다.

```text
PublishCandidate = {
  operation: publish_candidate, candidate: CandidatePin,
  branch: string, expected_remote_head: git_sha | null
}
Deliver = {
  operation: deliver, candidate: CandidatePin,
  pr_number: positive integer, integration_base: git_sha
}
PublicationReceipt = {
  kind: publication, candidate: CandidatePin, branch: string,
  observed_remote_head: git_sha, pr_ref: ResourceRef | null,
  review_request_refs: ResourceRef[], progress_ref: ResourceRef,
  stage: branch_published | pr_ready | publication_ready
}
DeliveryReceipt = {
  kind: delivery, candidate: CandidatePin, pr_ref: ResourceRef,
  integration_base: git_sha, merge_commit: git_sha,
  post_merge: pending | success | failed | unknown,
  issue_closed: boolean | null, progress_ref: ResourceRef
}
```

branch와 expected_remote_head는 인증된 progress의 실제 branch/expected_head에서 얻고 기존
branch validator를 사용한다. null은 해당 기대가 확정된 branch 부재이며 누락/partial 조회를 뜻하지
않는다. `pull_request.base`는 조회한 base commit SHA다. 최초 deliver의 integration_base는 이 값,
재대사의 기준은 기존 intent/merge receipt의 원래 expected_base다. §4의 progress 추가 필드는
현재 parser에 이미 있는 원본 필드이며 새 저장 자료가 아니다. P12가 nullable·SHA·branch 형식과
Python→Rust→TS mapping을 검증한다. pin을 읽을 수 없는 surface는 이 명령을 활성화하지 않는다.

publish는 exact candidate의 등록 검증·필수 독립 review가 확인되고 local HEAD가 그대로일 때만
기존 push→owned PR→필요한 remote review 요청·read-back까지 수행한다. 새 commit/수정/검증/배정은
하지 않는다. dirty 또는 head 변경이면 `waiting/candidate_changed`이며 새 후보로 자동 전환하지 않는다.
branch 이름/expected head가 다르면 신규 push는 `rejected/stale_publication`이다. PR creation/update와
review 요청도 기존 exact intent·정책·공개 payload 검사와 bounded retry를 사용한다. merge·close·자원 정리는 0회다.

deliver는 exact owned PR의 head와 CandidatePin, 원래 integration base를 확인한 뒤 fresh protected
review/CI/merge 정책으로 merge→exact squash read-back→필수 post-merge 관측→조건부 Issue close까지만
진행한다. publish/새 PR/새 구현·repair·검증 assignment·자원 retirement는 0회다. base 변경은 새 merge
전 `rejected/stale_delivery`이며 자동 repin하지 않는다. queue가 필수인데 지원되지 않으면 hold한다.
post-merge 실패는 원래 실패와 다음 책임을 표시하고 repair 생성을 별도 continuation에 남긴다.

응답 유실·재시작에서는 **새 효과의 stale 대조 전에** 기존 trusted intent와 exact 결과를 읽어
같은 효과인지 대사한다. publish의 old/null expected remote head가 이미 pinned candidate가 된 것은
기존 intent/owned branch/PR의 일치로만 수용한다. 다른 candidate를 현재 값으로 채택하지 않는다.
deliver는 현재 main tip이 아니라 원래 expected_base와 immutable squash receipt로 과거 merge를
확인한다. 대사 뒤 남은 새 효과는 현재 admission·권한·fresh source guard를 다시 통과해야 한다.
원본 귀속·attempt budget이 복원되지 않으면 unknown이며 request_id나 cache로 중복 안전성을 만들지 않는다.

receipt는 실제 read-back한 단계만 담는다. publication_ready는 필수 PR/요청까지 확인됐다는 뜻이며
review 승인·merge가 아니다. 해당 후보·branch·PR의 일치와 필수 read-back이 모두 확인돼야 publish는
applied다. deliver receipt는 실제 merge_commit 확인 후에만 있으며 pending/failed/unknown post-merge는
waiting/unknown으로 남는다. 원래 요구의 post-merge 성공과 close read-back까지 확인해야 applied다.
이 applied도 cleanup 완료가 아니다. 부분 완료는 확인한 receipt/refs를 보존하고 허용되지 않은
다음 operation을 자동 호출하지 않는다. capability는 두 exact operation을 각각 자격 확인한다.

### 명시적 cleanup profile

[P15](../changes/15-resource-retirement/spec.md)가 action=cleanup을 구현한다. **정리만 수행하라는
실제 scoped 요청**에 해당하며 기본 Pause/Stop·취소·일반 Goal에서 합성하지 않는다. 업무 admission은
현재 paused/stopped/running 그대로 유지하며 미확인/invalid admission에서는 실행하지 않는다.
one command는 one exact resource의 one operation이다. UI/native의 실제 요청과 기존 위임을 확인하며
`authorized=true`, `cleanup=true`, caller allowlist, 새 persistent intent flag를 받지 않는다.

```text
CleanupTarget = {
  kind: owned_resource, repository_id: positive integer, issue_number: positive integer,
  source_attempt: UUID, resource: ResourceRef
}
Cleanup = {operation: preserve | archive | retire | remove_schedule}
CleanupReceipt = {
  kind: cleanup, resource: ResourceRef,
  operation: preserve | archive | retire | remove_schedule,
  result: preserved | archived | retired | schedule_removed,
  evidence_refs: ResourceRef[]
}
```

expected는 non-null current runtime/admission과 assignment=null이다. source_checks에는 target.resource
하나의 qualified revision 또는 adapter가 제공한 actionable_digest를 넣으며 effect_key=null이다.
대상 resource ref는 provider instance와 원래 resource를 정확히 식별해야 한다. 그 revision/digest는
현재 owner·work/attempt binding·activity·preservation·공유 책임 범위까지 변경 검출할 수 있어야 한다.
caller는 표시 문장·경로에서 digest를 만들지 않는다. 실제 provider별 source→ref/pin 생성, 원래 권한,
조건부 변경/직렬화와 read-back mapping은 P15/NC가 자격 확인하고 strict producer/consumer에 연결하기
전까지 미완료다. revision 없는 provider에 추측한 digest를 요구하거나 임의 새로운 SourceValue를 싣지
않는다. 그 surface가 해당 pin을 전달하지 못하면 `rejected/unsupported_operation`이다.

공통 handler는 내부 `cleanup_only_v1` 제한으로 target의 현재 owner·실제 비활성·보존·전체 참조를
재조회하고 원래 provider에만 dispatch한다. preserve는 이미 존재하는 owned 결과의 회복 가능한
보존만 허용한다. archive/retire/remove_schedule은 필요한 보존과 **해당 자원**의 남은/공유 책임
해소가 확인돼야 한다. Goal 전체 완료는 선행 조건이 아니다. enabled schedule 자체를 실제 active
turn으로 보지 않으며 현재 책임 종료·공유 없음·실행 비활성이 확인되면 지원되는 제거가 가능하다.
취소로 불필요해진 질문은 원본의 취소 범위로 판정하며 답변 완료를 만들지 않는다. stale resource/owner는
`rejected/stale_cleanup`, partial/unknown은 대기다. admission lock 안에서 일시적으로 running을 만들거나
일반 completed/advance callback을 호출하지 않는다. 필요한 정리 상태 기록/read-back만 같은 제한에
포함하며 다른 업무가 남은 원 work의 phase/wait/next_action을 덮지 않는다. 전체 책임 해소 전 active
표식을 제거하지 않는다. 모든 의무가 해소된 terminal 정리의 표식 해제는 EX/P15의 기존 bookkeeping만
사용한다. 새 모델·업무 commit·push·PR·merge·Issue close·resume·타 자원 변경은 0회다.

최초 효과는 실제 요청 문맥과 현재 원본 검사를 통과하면 가능하며 모든 provider에 새 durable flag를
요구하지 않는다. 유실·재시작 후에는 기존 request/intent/receipt와 owned inventory를 대사한다.
자동 재전송은 원래 권한·정확한 미적용·기존 budget이 복원된 경우만 가능하다. 미확인 또는 source가
없는 경우 unknown/read-only 대사를 유지하며 부재·404·timeout을 정리 성공으로 바꾸지 않는다.
receipt의 result는 요청 operation과 일대일이고 실제 exact provider read-back의 evidence_refs가
최소 하나 있어야 한다. applied는 그 효과만 확인됐다는 뜻이며 전체 cleanup/실행 종료/Quit가 아니다.
귀속 가능한 원본 receipt가 없으면 request receipt를 재생성하지 않는다. 현재 확인된 resource 상태와
이전 command 귀속은 별도로 표시한다. native source의 private refs는 공개 GitHub에 전달하지 않는다.
`cleanup.preserve/archive/retire/remove_schedule`은 각각 별도 capability다. 하나가 지원돼도 다른
operation이나 native_control을 켜지 않는다. 첫 흐름의 기존 stopped checkpoint 예외는 그대로 유지한다.

### 아직 닫히지 않은 source별 profile

native_control은 P07, work_create의 최종 receipt/원본 mapping은 P10, project 연결은 P17,
delegation change는 P18이 소유한다. 각 변경은 실제 지원 source의 identity·권한·판본/변경 검출·
반환 shape를 확인하고 이 CP 정본의 exact input/expected/reply와 strict consumer TC를 닫은 뒤에만
해당 capability를 활성화한다. 기존 표의 개념적 action이나 모델이 만든 ref를 endpoint 지원으로
광고하지 않는다. 미확정 provider 필드를 지금 union에 넣지 않으며 raw JSON passthrough로 연결하지 않는다.
이 미완료 범위는 독립적인 위 typed profile의 구현을 막는 전역 gate가 아니다.

### 명령 이름과 실제 효과의 일치

현행 다섯 MCP 이름은 continuation entry다. 예를 들어 기존 `hydra_verify` 호출이 이후의 전달
동작으로 이어질 수 있으므로 이름만 보고 “검증만” 버튼에 연결하지 않는다. 새 CommandV1의
operation은 [실행 계약](execution.md)의 동일한 runner effect filter를 사용한다. 제한은 caller가
제공하는 임의 allowlist가 아니라 server가 version에 따라 선택하는 닫힌 집합이다.

| operation | 최대 허용 효과 |
| --- | --- |
| continue | 기존 위임과 guard 안의 lifecycle continuation. UI는 이어서 진행으로 표시한다. |
| verify_only | 정확한 후보의 지정 검증, 안전한 local candidate checkpoint, 독립 후보 검토. branch publish/PR/원격 review 요청/merge/close/retire 금지. |
| checkpoint_only | exact assignment의 결과·owned checkpoint·원 단계 완료/대기 기록과 read-back/retirement. 새 단계 배정·실행·전달 금지. |
| decision_apply | exact source attempt의 공개 가능한 결정 intent/context/resolved 기록과 read-back. fresh attempt/ticket·개발·전달 금지. |
| publish_candidate | 이미 검증된 exact 후보의 push/owned PR/필요 remote review 요청·read-back. 새 commit·배정·merge/Issue close/retire 금지. |
| deliver | 기존 승인된 exact PR/head/base의 보호된 merge·post-merge·조건부 close. publish·새 PR·새 구현/repair·자원 retirement 금지; 미충족 gate는 hold. |
| cleanup.* | 명시된 자원의 one operation·원래 cleanup bookkeeping/read-back. admission 불변, 새 업무·전달·무관 자원 변경 금지. |

실제 필요한 전이가 ceiling을 넘으면 `waiting/effect_not_allowed`와 필요한 다음 행동을 반환한다. 다른 operation으로
자동 승격하지 않는다. ceiling을 전달·집행하는 runner 계약이 없거나 구버전이면 해당 operation은
unsupported다. legacy 호출의 의미는 그대로 유지하며 새 UI에서 좁은 효과라고 거짓 표시하지 않는다.

### Admission의 좁은 예외

전체 Pause/Stop은 명령이 host core에 도달하고 안전한 local installed binding을 확인할 수 있을 때
GitHub/native 원본 일부가 unavailable이어도 가능하다. 원격 Codex/MCP 또는 host 자체에
도달하지 못한 경우까지 적용을 보장하는 문장이 아니다.
이는 admission을 제한하는 설정만의 예외이며 native 중단·ticket 해제·자원 삭제를 포함하지 않는다.
최신 local state를 lock 안에서 읽고 Stop 상태를 Pause로 약화하지 않으며 같은 mode는 수정 없이
read-back한다. 최초 연결에서 아직 표시할 expected가 없으면 null을 허용하지만 backend가 trusted
installation을 해결하지 못하면 rejected다. 이 단조 제한 처리는 v3의 신규 동작이다.

Start/Resume은 null/stale expected를 허용하지 않으며 lock 안에서 revision을 대조한다.
설정 변경이 경합하면 stale revision으로 거절한다. 전체 Resume은 project override를 보존한다.
gate만 바뀌면 “admission applied”이며 실제 실행 중단/재개를 뜻하지 않는다.

### 첫 흐름의 project Pause/Resume

[EX §7](execution.md#7-질문결정다음-wake)의 첫 흐름에는 기존 단일 host admission revision을
사용한다. 프로젝트별 새 revision/설정 DB는 만들지 않는다. `admission_set`의 정확한 repository
ID와 현재 이름/설치 binding을 대조하며, project Pause와 Resume 모두 non-null current
`expected.admission_revision`을 요구한다. 위의 전체 host 제한 예외를 project로 확대하지 않는다.

| 입력·현재 상태 | lock 안의 처리·결과 |
| --- | --- |
| current expected, project running → Pause | project만 paused로 저장하고 revision 한 번 증가·read-back. host와 다른 project는 유지 |
| current expected, 이미 같은 mode | 쓰기·revision 증가 없이 현재 상태 확인. 실제 native 실행을 추정하지 않음 |
| stale 또는 null expected | rejected/stale_revision 또는 precondition_required. 쓰기 0회, 현재 상태를 다시 읽을 경로 제공 |
| project stopped → Pause | stopped 유지, 더 강한 제한을 약화하지 않음. 원하는 제한이 이미 충족됨을 표시 |
| current expected, host running, project paused → Resume | project만 running으로 저장·read-back. decision·실행·전달은 별도 continuation |
| host paused/stopped에서 project Resume | 상위 제한 유지, 요청 거절. 명시되지 않은 host Resume으로 바꾸지 않음 |
| runtime/config/target binding 변경 | 이전 요청 거절. 새 binding/다른 project로 자동 변환하지 않음 |

#### 설정 CAS의 정확한 순서

기존 version=1 파일, 단일 host revision, 안전한 parent/lock descriptor와 fingerprint 검사를
유지한다. 새 command 진입은 다음 순서를 갖고 기존 legacy `set_mode`의 API 의미와 구분한다.

1. schema·실제 호출 권한·runtime/config/control binding·등록 target을 확인한다. 화면에서 보낸
   expected를 그대로 보존한다. 다른 project의 최신 revision을 얻었다고 expected를 교체하지 않는다.
2. 기존 exclusive lock을 얻고 파일·lock binding을 검사한 뒤 최신 상태를 읽는다. lock busy는
   `waiting/operation_state_busy`이며 적용이 아니다. unsafe state를 초기화하거나 lock을 재생성하지 않는다.
3. **동일 mode 판단 전에** expected.admission_revision을 비교한다. 다른 project의 변경으로
   host revision이 증가했어도 stale_revision이다. 현재 원하는 mode와 같다는 이유로 stale/null을 수용하지 않는다.
4. running 요청은 global gate를 먼저 검사한다. 변경할 값은 유효 gate가 아니라 해당 project의
   저장 override(없으면 running)다. host stopped에서도 project Pause는 paused override를 남겨
   나중에 host Resume이 project를 뜻밖에 재개하지 않게 한다. project stopped→Pause는 stopped를 보존한다.
5. 같은 mode/더 강한 stopped를 유지하면 쓰기·revision·updated_at 변경 0회다. 결과는
   `applied/already_satisfied` 또는 `applied/stronger_mode_retained`다. 상태 변경이 필요할 때만
   revision 상한을 검사한다. 상한에서 no-op은 가능하지만 변경은 `rejected/revision_exhausted`다.
6. 변경은 기존 private temp-file write/fsync, settings/lock 재검사, atomic replace,
   parent fsync, 같은 exclusive lock 안의 정확한 read-back으로 마친다. replace가 설정의
   선형화 지점이며 성공 응답은 durable write와 read-back 확인 후에만 보낸다. host/다른 override는 보존한다.

동일 R을 본 두 경합 요청 중 한 요청만 R+1을 쓴다. 두 번째는 같은 mode여도 stale이다.
bridge는 살아 있는 같은 request의 이중 클릭만 메모리에서 합칠 수 있다. request_id가 같아도
target/expected/payload가 다르면 `rejected/request_payload_conflict`다. cache 소실 뒤에는 이
중복 판정을 복원했다고 주장하지 않으며 CAS를 다시 적용한다. 무조건 latest revision으로
갱신한 mutation 재시도는 없다.

admission reply의 observed_refs는 lock 안에서 확인한 admission observation을 가리킨다.
그 key/scope는 `command:<request_id>:admission-readback`으로 현재 조회 slot과 구별한다.
같은 reply에 최신 상태를 넣으면 별도 observation을 쓴다. 예를 들어 R+1에서 Resume이
적용되고 R+2에서 Pause가 적용됐다면 “Resume 적용 확인(R+1), 현재 일시정지(R+2)”이며,
옛 receipt를 현재 gate로 덮어쓰거나 현재 R+2 때문에 확인된 R+1 결과를 부정하지 않는다.
이 receipt는 응답의 메모리 자료이고 파일/journal로 저장하지 않는다.

#### 설정과 외부 효과 사이의 경계

source 재조회·intent 대사는 lock 밖에서 수행한다. 같은 host의 기존 owner/coordinator 범위와
operation ceiling을 대조하고, **각 bounded 효과의 실제 dispatch 직전** shared admission guard
안에서 현재 gate·exact owner·runtime/target을 다시 확인한다. 이미 재조회한 required source가
바뀐 사실을 알면 dispatch하지 않는다. 하나의 장시간 turn, LLM 판단, 사람 대기, network polling
루프 전체 동안 control lock을 잡지 않는다. 각 write/command handoff가 guard의 단위다.
같은 명령의 허용된 효과가 만든 예정된 source 변화는 exact read-back 결과를 다음 단계의
전제로 삼는다. 이것을 외부의 무관한 변경이나 바뀐 권한/범위까지 자동 채택하는 근거로 쓰지 않는다.
CommandV1이 요구한 admission_revision도 이 guard 안에서 대조한다. command 도중 다른 설정
변경으로 revision이 달라졌으면 이미 확인된 효과를 보존하고 다음 dispatch를 보류한다. backend가
원래 expected를 새 revision으로 자동 교체하지 않으며, 나중의 fresh command가 원본 intent를 대사한다.

| 먼저 확정된 경계 | 보장·후속 처리 |
| --- | --- |
| bounded effect가 shared guard에 진입하고 전송 | exclusive Pause는 그 guard가 풀린 뒤 적용된다. 이미 전송된 효과의 성공/실패/unknown을 보존한다. |
| exclusive Pause의 replace/read-back | 이후 shared guard는 새 업무 dispatch를 거절한다. Pause 전 source preflight를 마친 요청도 다시 gate를 읽어 거절한다. |
| 전송 뒤 timeout/응답 유실, 그 뒤 Pause | 원격이 늦게 commit할 수 있다. Pause 뒤 새 Hydra dispatch는 0회지만 원격의 늦은 결과까지 0회라고 보장하지 않는다. 원본 read-back만 수행한다. |
| Resume ACK 뒤 다시 Pause/Stop | 다음 context·resolved·assignment·checkpoint의 개별 guard가 새 gate를 따른다. 이전 ACK로 통과하지 않는다. |

guard는 cooperating Hydra의 local admission과 dispatch를 순서화한다. shared lock은 writer 간
mutex가 아니며 GitHub의 read→write를 atomic transaction으로 만들지 않는다. 현재 progress
comment PATCH에는 원격 CAS가 없으므로 owner/coordinator와 exact intent 재조회·후속 read-back의
한계를 유지한다. 외부 writer가 마지막 read 뒤 바꿀 가능성을 없앴다고 주장하지 않는다. 변경을
발견하면 추가 효과를 멈추고 대사한다. provider가 지원하는 conditional mutation만 별도로 사용한다.
생성·전송 중인 helper가 guard 밖에서 뒤늦게 새 dispatch를 시작할 수 있으면 아직 경계가 닫히지
않은 것이다. 기존 execution-boundary의 생성 확인·소유권 보존을 먼저 만족해야 한다.

첫 흐름의 paused 허용 lane은 조회와 projection으로 제한한다. Codex 원본 답변의 귀속/충돌을
읽을 수 있지만 GitHub context/resolved 쓰기·새 attempt/ticket·일반 checkpoint·업무 commit·
이 첫 흐름의 일반 continuation에서 전달·정리는 보류한다. 이후 별도의 명시적 cleanup profile을
수용한 경우에만 위 제한된 정리 효과를 사용할 수 있다. 실제 종료가 확인된 exact assignment의 stopped checkpoint 보존 예외는
현행 EX대로 유지한다. 범용 `cleanup=true`나 사용자 제공 allowlist로 이를 확대하지 않는다.

Resume은 admission 설정의 결과다. 답변이 없거나 source/owner가 unknown이면 설정 적용은
표시하되 실제 진행은 waiting이다. 적용 직후 Pause/Stop이 다시 들어올 수 있으므로 결정 기록,
배정, checkpoint의 각 효과 직전에 현재 gate와 필요한 source를 다시 확인한다. 이전 Resume
ACK나 답변 수신이 그 뒤의 실행 허가를 계속 보장하지 않는다.

상태 표시에는 최소한 다음 의미가 함께 있어야 한다. 질문·답변은 §4의 DecisionView,
나머지는 기존 source별 Fact를 사용하며 이 절에 별도 영속 schema를 만들지 않는다.

- 원래 질문과 답변의 수신 여부, 충돌/유효성, 결정 적용 여부와 대기 이유.
- project admission의 현재 mode/revision과 host의 유효 제한.
- gate 변경 결과와 새 assignment·실제 native 시작/결과의 각각의 근거.

명령 응답 유실 뒤에는 아래 read-back 규칙을 따른다. 현재 desired mode가 관측되면 그 상태가
충족됐다고 표시할 수 있지만 특정 요청이 적용됐다는 receipt나 native 재개 증거로 바꾸지 않는다.
이 확인만으로 continuation을 중복 요청하지 않는다. cache가 사라졌다면 새 조회의 revision으로
명시적 후속 명령을 판정하고, 원래 pending UI를 성공 또는 미실행으로 복원하지 않는다.

### 멱등·응답 유실·재시작

`request_id`는 UI 응답 연결용이며 영속 멱등 키가 아니다. workflow/create의 `effect_key`는
기존 GitHub intent/progress의 결과 식별자에 연결한다. native/resource는 원래 provider의
idempotency/lookup에 연결한다. 해당 source에 복구 가능한 intent와 lookup이 없으면 Hydra에
journal을 추가하지 않고 그 효과의 automatic retry를 비활성화한다.

응답을 잃으면 한 번 bounded read-back한다. **그 exact effect**가 원본의 intent/result로 확인되면
applied, 실제 진행 중이면 waiting, 판단 불가면 unknown이다. 일반 mutation을 자동 재송신하지 않는다.
아래 EX append-only 예외처럼 재시도 의미가 별도로 수용된 operation만 그 exact 계약을 따른다. 같은 효과 재요청도 원래 intent를
먼저 읽어 성공했으면 기존 effect_ref를 반환한다. 같은 key의 다른 payload는 rejected다.
local admission은 desired mode와 revision으로 확인하는 상태 연산이므로 별도 journal이 필요 없다.
cache가 사라지면 원본 intent를 다시 읽으며 이전 pending UI를 성공/미실행으로 가정하지 않는다.

| 실패 위치 | 결과·UI·복구 |
| --- | --- |
| validation/CAS/guard 거절 또는 replace 전 확정 실패 | rejected와 정확한 reason; 이 요청의 설정 쓰기/dispatch 0회. 현재 상태는 별도 조회 가능 |
| lock busy 또는 현재 gate/외부 조건 대기 | waiting; source 상태와 대기 이유 표시. 자동 enabling retry 없음 |
| replace 후 fsync/read-back 실패 | unknown; atomic replace 가능성을 보존하고 안전한 bounded snapshot 한 번. 성공/미실행 양쪽으로 단정하지 않음 |
| 성공 ACK만 유실 | unknown request feedback과 현재 관측을 함께 표시. mode 일치만으로 이 request의 receipt를 만들지 않음 |
| 원격 dispatch 결과 유실 | exact 원본 intent/result 조회. 조회 부재·404·partial을 미전송으로 취급하지 않음 |
| bridge/core 재시작 | 새 binding_epoch와 빈 메모리. 원본 현재 상태를 재구성하고 old pending에 대해 새 효과를 만들지 않음 |

원본에서 이미 확인한 과거 효과의 receipt와 현재 조회 실패는 다르다. 같은 runtime/binding 안에서
확인된 receipt는 유지할 수 있지만 현재 source Fact는 stale/unknown으로 내려간다. 반대로 원래
receipt가 없었다면 나중의 단순 desired-state 관측으로 만들어내지 않는다. request_id를 영속
effect identity로 취급하거나 UI 알림 닫기를 unknown 해소로 취급하지 않는다.

decision context/resolved의 재시도·중복 의미는 EX의 append-only 계약을 따른다. 같은 actor,
effect key, exact bytes로 확인한 중복을 하나의 의미상 효과로 대사할 수 있어도 원격 POST가
물리적으로 한 번이었다고 표시하지 않는다. 다른 payload는 충돌이다. 실제 resume progress PATCH는
별도의 변경이며 이 append-only 중복 규칙을 적용하지 않는다. 로컬 CAS, append-only 공개 결정,
원격 mutable progress의 서로 다른 재시도 보장을 공통 request_id 하나로 합치지 않는다.

## 9. 호환 전환과 완료 기준

1. Python v3 encoder, Rust parser, TypeScript parser/reducer와 같은 공개 fixture를 하나의
   reviewable candidate에 넣는다. expected는 계약에서 도출하며 producer 출력을 복사하지 않는다.
2. v3 client는 v2를 read-only compatibility view로 매핑한다. native/schedule·목표·result/cleanup은
   unsupported/unknown으로 유지한다. 예전 mode에서 실제 실행을 추정하지 않는다.
3. v2 client가 v3를 받으면 기존처럼 unsupported_runtime이다. 알 수 없는 key를 무시하거나 v3
   mutation을 v2로 재송신하지 않는다. 기존 installed CLI의 v2 제어 경로는 유지한다.
4. v3 expected precondition이 구현되기 전에 새 UI의 enabling mutation을 활성화하지 않는다.
   native qualification은 schema 전환과 별도의 증거다.
5. admission store format/version과 기존 progress schema는 이 변경에서 바꾸지 않는다.
   LRU/projection/request 이력을 위한 DB migration은 없다.

의미 있는 TC와 실제 세 계층의 계약 검증을 완료해야 한다. UI fixture 표시, Python test 통과,
packaged app 시작, 외부 관측 성공을 구분해 기록한다. native coverage나 실제 실행이 미확인이면
unsupported 표시 TC가 통과했어도 전체 v1.0.0을 PASS로 만들지 않는다.

## 10. 결정적 TC와 관측 시나리오

TC는 사전 상태→입력/사건 순서→기대값→금지 효과를 고정한다. fake clock과 제어된 adapter를
사용하며 source fixture와 UI 기대값은 독립적으로 도출한다. 파일명은 **구현 시 예정 경로**이고
이 문서는 test/code/CI 추가나 실행을 뜻하지 않는다.

| ID | 사전 상태·사건 | 기대값과 금지 효과 | 주된 예정 파일 |
| --- | --- | --- | --- |
| CP-D01 | v3 정상 payload, null revision, 누락/null/알 수 없는 enum/key/중복 key | 세 계층의 동일 수용/거절. null을 revision/0으로 만들지 않음 | `tests/test_control_projection.py`, `apps/mac/src-tauri/src/protocol.rs`, `apps/mac/tests/projection.test.ts` |
| CP-D02 | seq 2 성공 후 seq 1 성공/실패, opaque revision의 사전순 반전 | seq 2 유지. 오래된 성공으로 freshness를 회복하지 않음 | `apps/mac/tests/projection.test.ts` |
| CP-D03 | GitHub current, Codex unsupported, resource read failure | 정상 GitHub 유지, source별 오류 표시. native running/active=0 추정 금지 | projection Python/TS |
| CP-D04 | TTL 직전/동일/초과, sleep/resume, wall clock 역전 | 초과와 resume은 stale. clock으로 원본 revision 변경 금지 | projection Python/TS |
| CP-D05 | work 128/129, total 512/513, 1 MiB 경계, cache 4 MiB, 일반 Issue 다수 | 완전 record+partial scope, LRU, 재조회. 전체 complete/zero 오판 금지 | `tests/test_control_projection.py` |
| CP-D06 | closed work+cleanup pending, marker 누락+owner 잔존, source 권한 부족 | closed 재발견, orphan/unknown 유지. Quit·cleanup complete 금지 | `tests/test_control_projection.py`, `tests/test_control.py` |
| CP-D07 | runtime/config/binding 변경 후 이전 read/command 응답 | 다른 binding 응답을 표시/효과 확인에 사용하지 않음. 이전 효과 대사 | projection TS/Rust |
| CP-D08 | Issue 제목 변경/삭제/권한 상실, repository rename, PR head/base 변경 | numeric identity 유지, stale target 거절. 새 target으로 변환 금지 | `tests/test_control_commands.py` |
| CP-D09 | project Pause/Resume의 stale/null/current expected, 같은 mode, stopped→Pause, global paused에서 project Resume | 무효 쓰기 0, 같은 mode의 revision 증가 0, 강한 제한 유지, 정상 project만 갱신. gate 적용과 실제 재개 구별 | commands Python, 기존 operations tests |
| CP-D10 | remote timeout 중 Stop, Stop 뒤 Pause, 잘못된 local binding | Stop lane 독립, Stop 약화 금지, 잘못된 binding 쓰기 0. 실제 중단 추정 금지 | commands Python, Rust bridge tests |
| CP-D11 | admission ACK 중 native running, 미해결 schedule | admission stopped와 실제 running 병기. ticket 해제/삭제/Quit 금지 | projection/commands Python |
| CP-D12 | work_create의 같은 key/payload 중복, 같은 create_key에 다른 WorkCreateDraft digest, draft/target 불일치, 전송 뒤 응답 유실 | read-back/기존 효과 재사용/충돌 거절. 원본 payload 재생성 0, dispatch 한 번, blind retry 0 | `tests/test_control_commands.py` |
| CP-D13 | Stop과 dispatch 경합, A의 늦은 결과에 현재 B | guard 순서에 따른 이미 허용된 효과만 완료. B 변경/해제/전달 0 | commands Python, 기존 ownership tests |
| CP-D14 | progress completed+cleanup pending, Issue closed+증거 없음, wrong SHA CI | result/cleanup/delivery 독립, 불충분한 증거로 완료 금지 | `tests/test_control_projection.py` |
| CP-D15 | 미지원 native, 다른 task의 tool 결과, 미검증 actor, fake available flag | unsupported 명시, app lookup/dispatch 0. 자격 날조 금지 | `tests/test_control_projection.py`, `tests/test_control_commands.py` |
| CP-D16 | 악성 title/link/HTML/원격 이미지/문서 URL, private native text, credential/path가 들어간 오류 | text/허용 source preview/안전 reason만 표시. 표시로 자동 실행·네트워크 호출 0, GitHub payload·공개 log private 유출 0 | projection/commands Python, TS/Rust |
| CP-D17 | v2→v3, v3→v2, 미지원 v4, 실제 Python 출력→Rust→TS | 호환 표시/명시 거절, native unknown. 의미와 null을 세 계층에서 보존 | `tests/test_control_wire_contract.py`, Rust/TS fixture tests |
| CP-D18 | 관측→부분 실패→재시작→빈 cache→재조회, command 오류 중 다른 poll 성공 | 원래 상태·책임 재구성. read mutation 0, 미해결 오류 보존 | projection/commands Python, TS |
| CP-D19 | template 없는 유용한 외부 Issue, 주입 지시와 유용한 요구가 혼재, 원문 revision 변경 | propose/해석/부족한 의미 표시, 제목·헤더만으로 거절 금지. 위임 생성·secret 접근·stale 해석 실행 0 | `tests/test_control_projection.py`, `apps/mac/tests/projection.test.ts` |
| CP-D20 | 실제 source 제한 hint, 공유/독립 connection, header 부재, cached frame 반복, 시계 변경, 수동 Refresh | 같은 binding/scope 대기 보존, 다른 source 유지, missing→provider=0 금지, 알려진 provider 대기 우회 0. 실제 Python 출력→Rust→TS에서 hint·nullable source·남은 대기의 의미를 보존 | `tests/test_control_projection.py`, `tests/test_control_wire_contract.py`, Rust/TS projection tests |
| CP-O01 | installed app과 일반 repo 둘, 실제 Issue/PR 변경, 한쪽 연결 장애 | 변경이 app에 반영되고 다른 repo 유지. 화면·installed identity·source refs 기록 | installed acceptance receipt |
| CP-O02 | qualified native start/reentry/interrupt, Pause/Stop, 실제 질문/예약 | admission과 실제 동작 별도 관측. W1 미지원 부분 BLOCKED | native qualification+app receipt |
| CP-O03 | app 종료/재시작, work complete+cleanup pending, 복구 뒤 retire | DB 없이 책임 재발견. 실제 종료/보존/cleanup 확인 후 안전한 Quit 허용 | installed recovery receipt |

최소 native 읽기는 새 suite 대신 기존 사례에 다음 oracle을 포함한다.

| 기존 사례 | 합성 입력·사건 | 기대값 |
| --- | --- | --- |
| CP-D01/03 | task metadata 정상, 최근 turn page partial 또는 history만 손상 | metadata 유지, history partial/stale. 두 scope의 coverage를 합치지 않음 |
| CP-D01/05 | Unix seconds/null, 중복 locator, 잘못된 귀속/page/cursor, 입력 1 MiB 경계 | 정규화 또는 해당 source 거절; 원본 일부 잘림을 정상 값으로 채우지 않음 |
| CP-D02/07/18 | null revision에서 내용 변경, 같은 ID 두 번 조회, 늦은 page, 연결 교체·재시작 | 새 현재 Fact 재계산, 다른 binding 응답 배제. 반복 ID를 불변·복원 증명으로 승격하지 않음 |
| CP-D15 | 질문 같은 agent 문장과 userMessage 승인, active task와 과거 completed turn | decision/권한/work binding 생성 0; ended/active=0/ticket 해제/완료 추론 0 |
| CP-D16 | includeOutputs=false 응답에 본문·tool arguments·private canary | projection/cache/public log에 해당 값 0; 표시로 도구 실행 0 |

첫 흐름의 명령·consumer·fault oracle도 기존 ID의 구체 사례로 구현한다. 경합은 임의 sleep이나
문자열 호출 순서만으로 시험하지 않고 실제 temp store/lock과 제어된 process barrier를 사용한다.
외부 provider fixture는 dispatch와 원격 commit/read-back을 분리해 late commit을 재현한다.

| 기존 사례 | 사전 상태·제어된 사건 | 정확한 oracle·금지 효과 |
| --- | --- | --- |
| CP-D01/17 | 같은 CommandV1을 TS→Rust→CLI→Python 및 MCP handler에 전달 | target/expected/digest가 그대로 도달. preflight revision 교체 0. missing receipt, wrong assignment, false retirement flag, 다른 target receipt 거절. CP payload의 native_context 거절, MCP status 진단은 별도 검사 |
| CP-D09 | R을 본 두 project 요청을 EX lock 전 barrier에서 함께 해제; 같은 mode와 다른 mode 각각 | 한 번 R+1, 다른 요청 stale. stale라도 desired mode가 같으면 no-op 성공으로 바꾸지 않음. current no-op은 write/revision/time 변경 0. max revision에서 no-op 성공·실제 변경 거절 |
| CP-D09/07 | native epoch=null, runtime_key=null 또는 binding 변경 뒤 우연히 동일 R; host stopped에 project Pause; host paused에 project Resume | project 명령의 runtime 기대값 누락/변경 거절. Pause override 보존·host mode 유지. 상위 gate가 막은 Resume 쓰기 0. host 전체 제한 예외를 project에 확대하지 않음 |
| CP-D12/18 | temp fsync 전 실패, replace 전 실패, replace 후 parent fsync/read-back 실패, ACK만 유실, bridge 재시작 | 전송/replace 전 확정 실패와 효과 unknown 구별. 원본 bounded read 한 번·blind mutation retry 0. 현재 desired mode 일치가 원래 request receipt가 되지 않음 |
| CP-D12/07 | request R+1 receipt 수신 전 같은 target이 R+2로 바뀜; 같은 request_id 다른 payload; cache 소실 | R+1 receipt와 R+2 현재 상태 병기. 메모리 내 payload 충돌 거절. 재시작 뒤 request 중복 기록을 발명하지 않음 |
| CP-D13 | effect guard 진입→Pause; Pause→effect guard; source preflight→Pause→guard; timeout 후 remote late commit | 순서에 따라 기존 전송만 보존. Pause 적용 이후 신규 Hydra dispatch 0. 이미 전송된 late commit은 관측하고 재전송 0. 다른 owner B 수정/해제 0 |
| CP-D15 | candidate_ready/needs_decision/stopped의 정상 write phase, phase=design인 spec-only correction; review phase; failed; 잘못된 command version/operation | 정상 candidate는 정확한 원 phase 완료/read-back/retirement까지, correction 귀속 유지·다음 검증/배정 0. unsupported mutation 0. _candidate_result 전체 호출/advance/전달 0. legacy 다섯 도구는 원래 continuation 의미 유지 |
| CP-D12/15 | checkpoint 후 process 소실, old step/outcome이 이미 제거된 원본; exact decision pair와 native proposal 재조회 | checkpoint receipt 근거 없으면 unknown, 성공/재실행 추정 0. decision은 EX exact 중복 의미와 원본 refs를 검증하고 fresh attempt/ticket 0 |
| CP-D02/03/07/18 | answer received→pause→accepted→context only→applied; 원본 부분 실패·답변 변경·늦은 이전 응답 | 독립 gate 상태 유지. 적용 Fact의 ref/null invariant·종속 무효화. received/accepted/applied/Resume ACK를 actual running으로 승격 0 |
| CP-D16/17 | private summary와 native proposal canary; reader 단위와 좁은 명령 단위 | 공개 progress/log/projection 유출 0. reader 단위는 기존 5 tools, 좁은 명령 구현 단위에서만 6 tools. capability는 구현·검증된 exact operation만 available |
| CP-D08/15/17 | continue의 일치 ProgressPin/정상 next action, 같은 Issue의 phase/attempt/head 변경, null pin과 incomplete 조회 | 일치한 현재 책임의 양성 진전. stale_progress 거절·현재 pin 자동 교체 0, incomplete를 미시작으로 판정 0. unsupported route의 legacy fallback 0 |
| CP-D08/15/17 | verify_only의 일치 CandidatePin 정상 검증, 외부 head 변경, 자체 local checkpoint로 head 변경 | 정상은 실제 검증 verdict와 review 책임을 구분. 외부 stale은 거절, 자체 변경은 candidate_changed 대기. 새 head 자동 검증/verdict·구현/전달 효과 0 |
| CP-D01/15/16/17 | 기존 native controller assignment→native_handoff_v1 serializer→지원 native consumer, 동일 요청의 bridge 경로 | exact 기존 필드가 private 반환으로 전달, 배정≠실제 시작. bridge는 생성 전 대기, 반환된 native profile도 strict 거절. renderer/cache/public log의 cwd/prompt 0, 새 tool·가짜 ResourceRef 0 |
| CP-D08/12/15/16/17 | verify run→지원 read-only review assignment→review_checkpoint, source 변경·D proof 소실·완료 경로 미지원 | 정상은 같은 후보 review 수용+final read-back 뒤 exact step/ticket 종료. proof 소실은 pending 재검증 책임, stale 해제 0. unsupported/standard-only는 생성 전 대기, broad continuation/수정/다음 배정/전달/private 유출 0 |
| CP-D08/12/15/17 | publish의 검증된 exact 후보와 branch pin, dirty/stale, push 후 lost ACK·재시작 | 정상 push/owned PR/필수 review 요청까지 실제 진전. trusted matching 결과는 재사용, 새 commit/새 후보 자동 refresh/merge/close/retire 0 |
| CP-D08/12/14/17 | deliver의 exact PR/head/base, base 변경, merge lost ACK, 이후 main 진전·post-merge 실패 | 정상 보호 merge→post-merge→close, 과거 결과는 original base+squash receipt로 대사. 새 효과 fresh gate; publish/새 PR/repair 생성/retire 0, 실패를 completed로 덮기 0 |
| CP-D09/11/13/15/17 | paused/stopped에서 명시 cleanup one resource와 기본 continuation, incomplete Goal의 독립 inactive 자원·enabled 전용 schedule | 명시 정리의 one effect/read-back만 진행, admission revision/mode 불변. 기본 정리/모델/업무 commit/delivery/타 자원 0, active turn을 실제 종료로 추정 0 |
| CP-D08/12/16/18 | cleanup의 source/owner 교체·shared partial·보존 실패, 성공 뒤 ACK 유실/restart와 원본 receipt 없음 | stale/unknown 유지·대사, 정확한 현재 상태와 command 귀속 분리. 권한/budget 발명·blind delete·private ref 공개 0 |

`projection Python/TS`는 CP-D01의 Python/TS 파일, `commands Python`은
`tests/test_control_commands.py`다. Rust protocol/bridge tests는 기존 module unit tests에 넣는다.
공유 fixture는 예정 `tests/fixtures/control-v3/`에 공개 가능한 값만 사용한다.
native 좁은 경로는 기존 `tests/test_native.py`, `tests/test_mcp.py`, 경합은 기존
`tests/test_operations.py`, `tests/test_operation_boundary.py`, `tests/test_execution_boundary.py`에
해당 CP/EX 사례를 연결한다. fixture 기대값은 구현 출력의 복사가 아니라 위 사건/금지 효과에서 도출한다.

구현 후 대상 검사 명령(repo root 기준, 적용되는 기존 storage wrapper를 먼저 사용):

```sh
python3 -m unittest discover -s tests -p 'test_control*.py' -v
python3 -m unittest discover -s tests -p 'test_operation*.py' -v
python3 -m unittest discover -s tests -p 'test_native*.py' -v
python3 -m unittest discover -s tests -p 'test_mcp.py' -v
python3 -m unittest discover -s tests -p 'test_execution_boundary.py' -v
npm --prefix apps/mac test
npm --prefix apps/mac run build
cargo test --locked --manifest-path apps/mac/src-tauri/Cargo.toml
```

최종 후보는 기존 full Python suite와 필수 CI/review를 [구현 기준](../implementation-method.md)에
따라 실행한다. O는 위임된 실제 환경에서만 수행하며 fixture/source test를 그 증거로 사용하지 않는다.

## Explicit installation authority for STDIO project admission

The P02 installation-profile increment adds one server-owned authority source:
the optional protected `native_admission_control` host table. Its shared principal is
all agents/launchers able to use that installation, not an authenticated human/task.
Only configured numeric repository scopes may request admission_set(paused/running).
Arrival, client metadata, repository registration and caller-supplied context are not
grants. The adapter binds the same absolute config locator as the command core and
re-reads the profile before and after source lookup. Semantic config changes invalidate
old runtime expectations; expiry/revocation removes grants without automatically
changing admission. Existing parent-admission, CAS, uncertainty and receipt semantics
remain unchanged. No other operation gains authority. Full schema, failure cases,
expiry lifetime, non-atomic revocation limit and acceptance are owned by
[P02](../changes/02-project-admission/spec.md#installation-scoped-stdio-admission-profile).
