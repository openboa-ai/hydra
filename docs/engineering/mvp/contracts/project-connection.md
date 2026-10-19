# 프로젝트 연결·설정·해제 계약

Revision: 1 · 상태: 설계 후보 · 2026-10-19 · 구현·설치 관측: NOT RUN

[제품 F01](../../../product/mvp-design.md#42-전체-기능-조작표)의 정본이다. 작업·위임·실행은
[WR](work-records.md)/[EX](execution.md), native source는 [NC](native-capability.md),
표시는 [CP](control-plane.md), 정리는 [P15](../changes/15-resource-retirement/spec.md)를 따른다.

## 1. 목적·책임·현재 구현

| 항목 | 계약 |
| --- | --- |
| 목적 | 프로젝트를 연결해 현재 원본과 한계를 확인하고, 남은 책임을 잃지 않고 해제 |
| 책임 | host 설정은 Hydra, 자격은 기존 인증 provider, repository/정책은 GitHub, Project/task는 Codex |
| 동작 | 설정 후보와 현재 원본 확인 → 좁은 설정 변경 → 새 설정·admission read-back → 지원 source 조회 |
| 실패·복구 | 기존 설정과 원본에서 재대사. 403·partial·유실을 빈 성공으로 바꾸지 않음 |
| 완료 | 새 연결·재시작·해제 대기·정상 해제·마지막 항목 해제·자격 철회의 양성/장애 증거 |
| 범위 | 기존 host registry/admission 재사용. 새 DB·자격 저장소·프로젝트 생성·자동 위임·자동 실행 없음 |

현행 `load_host_config`는 `repos`와 선택적 `project_threads`를 읽는다. `project_threads`는
task locator이고 Codex Project나 ownership 증명이 아니다. CLI는 run/serve/status/identity/control만
제공하며 init/add/connect 명령은 없다. `load_project`는 현재 GitHub repository numeric ID와
protected default revision의 `.hydra.toml`을 대조한다. 아래 writer/profile은 **신규 후보**다.

PC-R1. 연결은 읽을 대상의 설정이며 실행 위임·work 생성·native task 생성·admission Resume가 아니다.
기존 유효 위임을 발견해도 연결 과정에서는 관측만 한다. 이후 명시적인 기존 실행 경로가 판단한다.

## 2. 최소 설정과 identity

기존 host TOML·물리 경로·소유권·크기 제한·provider 설정을 재사용한다. 새 설정 profile은
`connection_schema = 1`과 선택적 `project_connections`를 추가한다. 각 key는 `repos`에 있는
canonical `owner/name`이고 값은 아래 두 선언뿐이다. 새 workflow 상태를 저장하지 않는다.

| 설정 | 형식·의미 |
| --- | --- |
| `desired` | `connected` 또는 `disconnect_requested`. 해당 연결의 사용자 의도; 실제 가용성/완료가 아님 |
| `native_project_id` | 선택적 qualified native opaque Project locator. 없으면 미지정. 명칭/cwd로 자동 채움 금지 |

PC-R2. numeric repository ID·capability·원본 상태·자격·task 이력은 설정에 복제하지 않는다.
현재 GitHub identity와 protected `.hydra.toml`의 ID를 매번 대조한다. work/attempt의 ID와 다른
저장소를 이름만으로 승계하지 않는다. 이전 이름이 redirect되면 현재 이름/ID를 원본에서 확인하고
명시적 update로 설정을 바꾸며 stale 주소의 명령을 자동 변환하지 않는다.

기존 설정은 읽기 호환이다. `project_connections`가 없는 legacy 항목을 새 연결 검증 완료로
승격하지 않는다. 변경 대상만 새 선언을 가진다. profile 1은 `repos=[]`를 허용하되
`project_threads`/`project_connections`도 비어야 한다. 이는 등록 0이며 host의 미관리 실행 0이 아니다.
profile 없는 legacy 파일의 기존 cardinality는 바꾸지 않는다. 새 key를 모르는 구버전 loader는
거절한다. 이미 로드된 구버전 writer도 끝나고 pending 효과를 대사한 뒤 새 profile을 활성화한다.

PC-R3. native Project locator의 실제 host/project 존재·접근·task 관계와 capability는 NC가 확인한다.
현재 앱 도구 노출이나 `_meta`로 지원을 합성하지 않는다. 미확인은 GitHub 읽기를 막지 않지만
그 native 기능은 비활성이다. 다른 계정/host로 연결해도 위임·owner를 자동 승계하지 않는다.

### 기존 admission 설정의 단일 host binding

현재 arg-only run/serve도 같은 host에서 쓸 수 있으므로 호출자가 config를 전달할 것이라는 가정만으로
fresh guard를 보장하지 않는다. P17은 기존 admission 파일의 **version 2**를 소유한다. v1의 mode,
revision, project override 의미는 그대로 두고 `connection_config = {profile: 1, path: <absolute path>}`
하나를 필수로 추가한다. 이는 기존 설정의 trusted locator이며 registry·의도·원본·자격의 사본이 아니다.
path는 기존 host operator가 설치한 config만 선택하며 request/Issue/renderer에서 덮을 수 없다.

P02의 v1 호환은 초기 단계의 계약으로 유지한다. P17 전환은 old loaded writer 종료/pending 대사 후
기존 exclusive lock 안에서 v2 admission binding 먼저→새 config profile 순서로 영속화한다.
중간 crash에서 profile이 아직 없거나 다르면 신규 효과는 거절하고 같은 설치 대상에서 전환을 마친다.
revision은 증가시키고 최대값에서는 전환을 거절한다. 구버전 binary는 unknown version/key로 거절한다.
v2를 v1로 자동 downgrade하거나 binding을 삭제해 통과시키지 않는다.
전환 시 현재 등록 대상에도 explicit stopped override를 둔다. v2에서는 override가 없는 항목을
global running으로 자동 허용하지 않는다. 직접 config에 추가한 미준비 대상도 같은 guard를 적용한다.

모든 guard는 이 trusted control source에서 config를 찾는다. planned run/serve `--config`는 그
path와 일치해야 하며 기존 repo/issue·host·lock·workspace/provider argv도 같은 설정과 대조한다.
v2 host의 no-config/다른 binding 쓰기는 거절하고 read-only status는 유지한다. MCP도 동일 binding을
검사한다. path·물리 부모·파일 fingerprint와 no-follow 검사를 재사용하며 private path는 projection/log에 없다.

## 3. 요청·결과와 창구

P17은 planned `hydra connection preview|apply|status --config <installed-config>`를 소유한다.
preview/apply는 bounded stdin JSON만 받는다. config/runtime 경로는 trusted launcher가 고정하고,
renderer/Issue가 provider·command·path를 공급하지 못한다. 사람이 CLI로 요청하거나 허용된
native caller가 같은 CLI를 실행할 수 있다. 앱은 P16의 fixed-argv source action을 사용한다.
현재 MCP 다섯 도구 또는 CP `CommandV1`에 미등록 연결 mutation을 몰래 추가하지 않는다.

```text
ConnectionRequestV1 = {
  connection_schema: 1, request_id: UUID,
  operation: connect | update | disconnect | finalize_disconnect,
  repository: canonical owner/name,
  replacement_name: canonical owner/name | null,
  native_project_id: opaque string | null,
  expected: {config_digest: sha256, admission_revision: integer,
             repository_id: positive integer | null}
}
ConnectionReplyV1 = {
  connection_schema: 1, request_id: UUID | null,
  operation: connect | update | disconnect | finalize_disconnect | null,
  repository: canonical owner/name | null,
  outcome: preview | applied | waiting | rejected | unknown,
  reason: Reason | null, runtime: RuntimeIdentityV1,
  before_config_digest: sha256 | null, after_config_digest: sha256 | null,
  admission_revision: integer | null,
  config_applied: boolean | null, stopped_applied: boolean | null,
  finalized: boolean | null,
  configured: ConnectionSetting[] | null,
  proposed_configured: ConnectionSetting[] | null,
  observations: Observation<SourceValue>[]
}
ConnectionSetting = {repository: canonical owner/name,
                     desired: connected | disconnect_requested | null,
                     native_project_id: opaque string | null}
```

문자·정수·opaque ref 규칙은 CP, repository 형식/64 KiB 설정 상한은 기존 loader를 따른다.
JSON 입력도 64 KiB 이내이며 unknown/duplicate key를 거절한다. native locator는 1–256자,
제어문자 금지이며 qualified source의 opaque 값만 받는다. replacement는 update의 동일 numeric
ID rename에만, native locator 지정은 connect/update에만 허용한다. 나머지 경우 해당 값은 null이다.
모든 JSON key는 필수다. status는 요청 correlation/operation/repository를 null로 반환한다.
update는 지정 locator를 그대로 교체하며 null은 해제를 뜻한다. 현재 값을 임의로 추정해 유지하지 않는다.

preview는 변경 후보를 동일 validator로 검사하고 원본/권한/부족 범위를 반환한다. write·provider
factory import·task/Issue 생성은 0이다. apply는 동일 expected와 현재 원본을 다시 검증한다.
connect/update apply의 repository ID는 필수이며 실제 원본에 일치해야 한다. preview에서는 null로
시작해 실제 ID를 관측할 수 있고 이후 요청은 그 원본을 참조한다. disconnect는 자격을 잃어도
현재 등록된 대상의 제한만 적용할 수 있다. finalize의 필요한 잔여 확인이 불가하면 waiting이다.

request ID는 상관용이며 journal이 아니다. receipt는 실제 config/admission read-back만으로 만든다.
configured는 읽은 설정 선언이며 지원·실행 위임·native binding 완료를 뜻하지 않는다. legacy 선언
부재는 desired=null, config 읽기 실패는 configured=null로 유지한다. preview에만 검증한 변경 후보를
proposed_configured로 제공하여 현재 값과 비교하고 나머지는 null이다. mutation 접수·두 store 적용·finalize를 각각 표시하고, actual 관측이
없으면 nullable 결과를 성공으로 채우지 않는다. preview의 applied 값은 false다.
native를 포함해 CP observation으로 표현하지 못하는 사실은 추측하지 않으며 NC의 실제 field→
closed value→consumer mapping을 확정한 뒤 쓴다. reply를 ProjectionV3에 그대로 추가하지 않는다.
P16은 별도 profile의 operation/target/expected와 read-back을 검증하고 config·stopped·잔여 책임을 구분한다.

## 4. config와 admission의 갱신·crash 순서

PC-R4. 같은 host의 기존 admission exclusive barrier로 설정 CAS와 제한 변경을 직렬화한다.
긴 remote/native 조회는 barrier 밖에서 수행하고 진입 전 대상/현재성을 재확인한다.
no-follow·owner/mode·물리 부모·fingerprint·semantic config digest·admission revision을 모두
재검사한다. 불일치는 rejected이며 최신 expected로 자동 교체해 재송신하지 않는다.
config는 같은 안전한 부모의 0600 임시 파일→fsync→atomic replace→부모 fsync→read-back으로 쓴다.
임시 파일은 transaction journal이 아니며 재시작 때 의도로 채택하지 않는다.

| 조작 | barrier 내부 순서와 crash 판정 |
| --- | --- |
| connect | 검증한 후보 allowlist 내 새 대상의 stopped override를 기존 store에 먼저 영속화→repos/선언 추가. 중간 crash는 미등록+stopped. 동일 요청 재검증 뒤 등록 완료 |
| update | 대상 stopped와 owner/pending 정합 확인→같은 repo ID의 설정만 변경. rename 대상도 stopped 먼저 기록. 실행 중 연결 교체 없음 |
| disconnect | config에 `desired=disconnect_requested` 먼저 영속화→project stopped 기록. 중간 crash에도 아래 fresh guard가 신규 효과 차단. 원본에서 stopped 보완 |
| finalize | 잔여 종료/명시적 인계 확인→repos/해당 locator/선언을 원자적으로 제거. 기존 stopped override는 보존해도 됨. 마지막 repo도 정상 종료 |

PC-R5. 새 profile의 모든 writer는 **각 신규 효과 직전** current config binding/등록/desired를 읽는다.
trusted admission의 binding을 사용하며 요청 payload나 process의 오래된 argv로 source를 고르지 않는다.
disconnect_requested는 신규 업무 dispatch를 막는다. 원본 읽기·이미 전송한 효과의 대사와 P15의
명시적으로 허용된 exact cleanup-only 효과, qualified Stop/좁은 보존 checkpoint, 이 계약의
finalize는 각자의 권한/전제 guard로 계속할 수 있다. 이는 Resume·새 업무
허가가 아니다. 설정 변경·읽기 실패 시 옛 cached 설정으로 효과를 진행하지 않는다. 두 store 사이
crash를 닫는 이 guard 없이 새 profile을 켜지 않는다. 두 store의 동시 atomic commit을 주장하지 않는다.
새 등록/재등록은 반드시 stopped이며 host running을 자동 상속하지 않는다.

runtime 응답은 실제 replying process의 startup identity다. after_config_digest는 현재 설정 파일의
read-back이며 이미 실행 중인 controller가 새 설정을 로드했다는 증거가 아니다. 기존 controller는
binding 변화 뒤 새 효과를 거절한다. 지원된 reload/restart 후 identity/read-back을 확인해야 다시 쓴다.
설정만 바꿔 active owner를 교체하거나 승인되지 않은 service 재시작을 수행하지 않는다.

## 5. 해제·자격 철회·정상 복구

PC-R6. disconnect는 새 자동 효과를 제한하고 등록과 원본 참조는 남긴다. GitHub open/closed
work·pending 효과, bounded ticket, native task/turn/schedule, owned workspace의 현재 범위를
P15로 대사한다. 해당 책임의 active/unknown/partial 또는 소유 충돌을 숨겨 finalize하지 않는다.
무관한 foreign 자원은 보존하며 자기 책임으로 채택하지 않는다. 허용된 cleanup-only
경로에서 책임이 끝나거나 명시적 handoff의 원 owner 종료·보존·책임 인수가 확인될 때만 finalize한다.
인계받는 대상에 자동 권한이나 성공 결과를 만들지 않는다.

PC-R7. 즉시 자격 철회는 기존 인증 provider에서 할 수 있으며 cleanup 완료를 조건으로 막지 않는다.
Hydra는 token을 보관/연장/복원하지 않는다. 이후 read 실패는 source unavailable로 표시하고
잔여 책임과 최소 원본 참조를 기존 work/provider/config에 남긴다. 다른 account로 몰래 전환하지 않는다.
자격 철회는 실행 종료·ticket 해제·config 삭제의 증거가 아니다. native 독립 실행 중단은 NC/P07의 별도 경로다.

재시작은 설정 의도→현재 admission→원본을 대사한다. disconnect_requested이면 stopped를 보완하고
같은 책임에서 계속한다. ACK 유실은 두 store를 읽어 이미 적용된 요청을 반복하지 않는다.
connect 뒤 source가 실패해도 등록을 지우지 않고 partial을 표시한다. finalize 후 부재는 등록 해제만
입증하며 host 전체 zero-active/Quit 성공을 뜻하지 않는다. 자격 복구 뒤 같은 원본을 재발견하여
정상 cleanup/finalize까지 진행한다. 무관한 프로젝트의 설정·작업·관측은 보존한다.
외부에서 config 항목을 먼저 지운 경우 지원된 finalize로 간주하지 않는다. 기존 admission override의
대상과 ticket/provider 원본을 대사해 미등록 잔여 책임을 표시하며 설정 누락만으로 정리를 완료하지 않는다.
그 참조로 신규 업무 권한을 만들지 않고 허용된 read/정확한 recovery 범위만 사용한다.

## 6. 검증 소유

[P17](../changes/17-project-connection/spec.md)이 PC-D01–12의 fixture/consumer/실제 연결을 소유한다.
P16은 이 profile의 화면, P07은 native Project/owner source, P15는 잔여 종료/보존을 공급한다.
typed 설정/CAS는 D, 의미 판단을 포함하지 않으므로 L은 N/A다. 실제 연결·해제·자격 철회에 따른
한계 표시는 O로 확인한다. 새 profile·fresh guard·두 store 복구·strict reply consumer가 갖춰지기 전
설정 mutation을 활성화하지 않는다. fail-closed만으로 정상 등록/해제의 완료를 주장하지 않는다.
