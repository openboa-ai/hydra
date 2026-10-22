# P02 — 프로젝트 admission의 정확한 변경

Status: Design contract, revision 5, 2026-10-22. Operating acceptance remains separate.
수용 판본·구현 head·검증 결과는 구현 시 [공통 변경 절차](../README.md)에 따라 기존 작업에 연결한다.
이 문서는 전체 완료·설치 성공을 선언하지 않는다. 저장 계층의 부분 구현은 [검증 기록](verification.md)에 구분한다.
The accepted increment uses CP revision 9 and the integrated R requirements; pin immutable specifications before implementation.

## 1. 목적·요구·범위

사용자가 관측한 프로젝트 상태를 기준으로 Pause/Resume을 요청하면 같은 대상의 같은 설정
revision에서만 변경한다. 응답을 잃어도 원래 요청의 성공과 현재 설정을 혼동하지 않는다.
[R10/R12/R14/R16](../../spec.md#3-요구사항과-판정)의 stale 제어·복구·근거 표시를 담당한다.

| 항목 | 이 변경의 경계 |
| --- | --- |
| 책임 | `operations.py`의 기존 store/lock에서 CAS·durable read-back을 보장하고 core 명령에서 기대값을 보존 |
| 포함 | project Pause/Resume, 동일 mode 무쓰기, host 제한, 응답 유실, bounded effect와 Pause의 순서 |
| 제외 | 실제 native interrupt/resume, 전체 v3 UI, 질문 결정, 새 설정 DB·명령 journal |
| 입출력 정본 | [CP §8](../../contracts/control-plane.md#8-command-envelope와-공통-guard)의 admission_set·CommandReplyV1·admission receipt |
| Current increment | Existing CAS and typed admission gain the protected shared-installation STDIO adapter. Source evidence is revision-bound; installed/native qualification remains separate. |

## 2. 선행과 변경 소유

P01·P03·native 자격 검증 없이 시작할 수 있다. 기존 등록 프로젝트·격리된 임시 설정과
수용된 CP 판본이 선행이다. P05/P12가 같은 core를 사용할 때 interface 판본을 고정한다.
공통 handler의 P02 지원은 admission_set뿐이며 새 MCP tool은 등록하지 않는다.

이 명세는 같은 admission 책임의 후속 PR에서 재사용한다. [기존 검증 기록](verification.md)은
revision 2의 저장 계층·해당 파일 hash에 한정된 역사적 증거이며 이 개정으로 범위를 넓히지 않는다.

| 구현 단계 / PR 경계 | 선행과 완료 결과 | 후속 소비자 |
| --- | --- | --- |
| CAS 저장 계층 | 기존 부분 후보와 검증 파일을 대사해 재사용. exact store 판본의 lock/no-op/crash 결과만 인정 | 아래 typed command 단계 |
| typed admission 명령 | CP target/expected → numeric repository/runtime guard → CAS → 실제 read-back receipt. 저장 계층 TC와 command 정상·거절·unknown TC를 함께 통과 | P05의 core 제어, P12의 reply 소비, P16 및 허용된 native caller의 transport |

저장 계층의 통과는 handler 완료가 아니며 handler 완료도 원격 사용자·설치 앱의 조작 가능성을 뜻하지 않는다.
각 후속 경로는 같은 core를 사용하고 자기 transport/consumer 검증과 실제 권한 확인 후에만 활성화한다.

| 현재 경로 | 구체 변경 |
| --- | --- |
| `hydra_sdlc/operations.py` | legacy set_mode와 구분되는 CAS 진입, 같은 EX lock 내 expected 비교·no-op·write stage 분류 |
| `hydra_sdlc/control_commands.py`, 기존 `hydra_sdlc/control.py` | 전자가 CP typed admission handler·exact target/runtime·receipt를 소유하고 후자의 안전 config loader와 control 구성을 재사용 |
| `hydra_sdlc/runtime_identity.py` | 기존 identity 계산을 재사용; 새 identity/영속 binding 생성 없음 |
| `tests/test_operations.py`, `tests/test_operation_boundary.py`, `tests/test_operation_integration.py` | 실제 temp store·lock·시험 소유 process의 정상/경합/장애 사례 |
| `tests/test_control_commands.py` — 예정 | typed 입력·stale target·receipt/current-state 분리·오류 단계 검사 |
| `tests/test_control.py`, `tests/test_final_controls.py` | 기존 v2 의미·Stop/host 제한의 회귀 |

public CLI/앱의 v3 전환과 renderer 버튼 활성화는 P12/P16의 변경이다. P02의 core handler를
호출하는 시험 경로가 실제 mutation·read-back을 사용해야 하며 stub 성공으로 대체하지 않는다.

## 3. 입력·행동·불변조건

target·expected·nullable 규칙은 CP를 그대로 사용한다. project Pause와 Resume 모두 non-null
runtime_key/admission_revision을 요구하며 source_checks=[]·assignment=null·effect_key=null이다.
numeric repository ID는 현재 등록 이름과 대조하고, 다른 이름·binding으로 요청을 옮기지 않는다.
host 전체 제한 명령의 좁은 예외를 project에 확대하지 않는다.

1. 기존 parent/lock/config binding 검사를 통과한 뒤 exclusive lock 안에서 최신 설정을 읽는다.
2. 동일 mode 판단 **전** expected revision을 대조한다. 관련 없는 project 변경도 stale이면 거절한다.
3. project 저장 override를 변경한다. host 제한은 보존하고 stopped→paused 약화는 금지한다.
4. current no-op은 bytes/revision/updated_at이 불변이다. 실제 변경만 revision을 한 번 증가시킨다.
5. temp fsync→fingerprint 재검사→replace→parent fsync→exact read-back 후에만 applied receipt를 만든다.
6. 효과 직전 shared guard와 Pause의 exclusive write를 순서화한다. 전체 turn/응답 대기를 lock으로 감싸지 않는다.

replace가 local 설정의 선형화 지점이다. Pause 적용 이후 새 Hydra 업무 dispatch는 0회지만
이미 전송한 요청의 늦은 원격 commit까지 취소했다고 주장하지 않는다. runtime/config 기대값을
preflight의 최신 값으로 교체하지 않으며 UI가 보낸 stale 요청을 자동으로 재작성하지 않는다.

### 3.1. 내부 handler의 구체 연결

`control_commands.execute_admission_command(config_path, command, *, context_provider, github)`는
설치된 config 경로와 내부 의존성을 wire 밖에서 받는다. 이 단계는 repository target의
`paused`와 `running`만 지원한다. 유효한 admission envelope의 host target/stopped mode는
`rejected/unsupported_operation`이다. 다른 action의 상세 parser·endpoint는 구현하지 않는다.

`context_provider`는 신뢰된 adapter가 현재 호출의 `AdmissionCallContext(surface, binding_epoch,
repository_ids)` 또는 미확인을 반환하는 내부 callable이다. surface는 bridge/native를 명시한다.
bridge binding은 canonical non-null UUID이며 native binding은 null이다. 서로의 binding 규칙을
대신 사용하지 않고 두 surface 모두 현재 검증된 양의 numeric ID scope를 요구한다.
기본 grant가 없으며 command 안의 권한 필드는
거절한다. 이 context 타입 자체는 사용자 인증이나 native qualification의 증거가 아니다.
실제 transport가 현재 권한으로 이 context를 만드는 경로는 후속 구현이다. handler는 source
조회 전후 context를 확인하여 binding 변경·권한 철회가 있으면 쓰지 않는다.
context의 surface/binding 검증은 repository effect 권한 검사와 분리한다. 미지원 명령도
현재 검증된 context의 binding으로 응답하며 요청의 epoch를 그대로 echo하지 않는다.
context 미확인/불일치는 각각 authority_unavailable/stale_binding으로 거절한다. config를 읽을
수 없으면 host_config_unavailable이 우선하며 이미 검증된 binding만 보존한다. runtime identity가
불완전한 미지원 명령은 실제 관측 runtime과 unsupported_operation을 반환하며, 지원 명령의
쓰기에는 완전한 runtime key가 필수다. 미지원 host/action에 repository 권한을 합성하지 않는다.

malformed command는 고정 code `invalid_command`만 갖는 `InvalidAdmissionCommand`로
거절한다. raw 입력을 오류에 넣거나 target/request_id를 합성하지 않는다. 유효한 envelope의
지원 부족·stale·권한 미확인·source 실패는 CP의 완전한 `StandardCommandReplyV1`으로 반환한다.
common envelope에서 정규 request/binding ID·알려진 action·해석 가능한 host/repository/Issue target을
먼저 확인한다. 이 identity가 보존된 미지원 version/action은 unsupported reply를 반환하고 future
action body를 해석·복제·echo하지 않는다. 지원되는 admission만 상세 expected/parameters를 검증한다.
아직 해석할 수 없는 target identity는 합성하지 않고 parser 오류로 보존한다.
dict 진입은 이미 decoded된 값만 받으며 duplicate JSON key 검출은 후속 transport parser의 책임이다.
정수의 bool 대체, 비정규 UUID, 초과 길이, 누락/추가 key와 malformed Unicode를 허용하지 않는다.

현재 config는 안전한 기존 loader로 읽고 기존 `capture_runtime_identity`를 사용한다. 등록 이름의
`GitHub.repository` 읽기에서 numeric ID/full_name을 대조한다. lookup에 실패한 다른 등록 항목이
있어도 정확한 target을 확인하면 그 결과를 사용할 수 있다. 끝까지 target을 확인하지 못하면
조회 실패가 있었을 때 unknown, 완전 조회의 미등록일 때 rejected다. remote lookup은 lock 밖이며,
lookup 후 config/runtime와 context를 재확인한다. 원 expected를 최신 값으로 바꾸지 않는다.

typed handler는 `set_mode_if_current_observed(..., blocking=False)`로 같은 CAS의 exclusive lock을 한 번 시도한다.
경합이면 `waiting/operation_state_busy`를 반환하며 설정 변경·receipt·내부 대기/재시도는 없다.
후속 명시적 요청은 context/config/runtime/target을 다시 검증한다. legacy `set_mode`와 기존
CAS의 기본 `blocking=True`는 유지하고 async caller의 기존 nonblocking 동작도 유지한다.
불확실 쓰기 뒤 한 번의 `snapshot_observed(blocking=False)`도 경합을 기다리지 않는다. 이 관측이 busy이면
unknown과 observation/receipt 부재를 유지한다. `blocking`은 strict bool인 내부 인자다.
이 방식은 lock 대기 동안 오래된 grant/config가 보류되는 것을 막지만 외부 권한·config와 설정
CAS 전체를 하나의 원자적 transaction으로 만들지는 않는다. lock 안에서 callback이나 remote
조회로 권한을 갱신하지 않는다.

admission `ResourceRef`는 `{source:hydra, kind:admission, id:control_binding_digest}`다.
이미 관측된 설치 binding을 재사용하며 새 영속 ID를 만들지 않는다. 성공 observation의 key와
coverage.scope는 `command:<request_id>:admission-readback`, resource는 해당 admission이다.
revision은 실제 store revision의 monotonic 문자열이며 receipt/observed_refs가 같은 observation을
가리킨다. 값은 CAS가 lock 안에서 반환한 exact snapshot이고 후속 조회로 교체하지 않는다.
unknown의 한 번 관측은 `command:<request_id>:admission-current`로 분리하며 receipt=null이다.
no-op은 반환 revision과 원 expected의 동일성, stronger stopped는 반환된 실제 override로 판정한다.
현재 gate 사유는 대상 project와 host의 실제 mode에서 계산하며 실행 중단·재개를 나타내지 않는다.

### 3.2. 오류 분류·관측 시각·동시 변경 보충

`os.replace`의 정상 반환 뒤에 replacement 완료를 표시한다. EACCES/EPERM/EROFS와 같은 좁은
permission 실패에서 같은 잠금 안의 기존 destination fingerprint가 불변으로 확인된 경우만
확정 미적용으로 거절한다. EIO/EINTR/ENOENT·알 수 없는 실패나 변경/확인 불가 fingerprint는
교체가 이미 일어났을 수 있으므로 unknown이다. 실제 교체 후 fsync/read-back/lock·descriptor
정리 실패의 unknown은 유지한다. 확인을 성공 receipt로 바꾸거나 mutation을 다시 시도하지 않는다.

`AdmissionReadback(snapshot, observed_at)`는 호출별 자료다. 성공 CAS·no-op과 불확실 결과 뒤
한 번의 현재 관측은 각각 기존 잠금 안에서 snapshot과 시각을 함께 얻는다. reply formatter는
그 시각을 그대로 사용하며 새 clock/read를 호출하지 않는다. 뒤의 writer가 더 높은 revision을
써도 원 receipt의 snapshot/time을 바꾸지 않는다. 시각은 revision·명령 순서·권한의 대체물이 아니다.
새 observed API는 같은 store·CAS를 쓰며, 기존 set_mode/set_mode_if_current/snapshot의 dict
반환과 저장 schema는 유지한다. recovery의 read 또는 시각이 없으면 unknown/receipt=null을
유지하며 observation을 만들지 않는다.

미지원 schema/action은 기존 common object container·identity를 확인한 뒤 admission의 exact
expected key 및 상세 body 검사 전에 분기한다. future body는 해석·복제·echo하지 않는다.
지원 admission의 closed fields는 그대로 검증한다. remote lookup 뒤에는 current config/control/
runtime을 읽거나 실패를 보존한 다음 context/epoch를 마지막에 갱신한다. config 실패를 먼저
반환하고, 그 다음 current authority 오류와 repository 결과를 판정하며 효과 전 원 expected와
current runtime을 대조한다. config 실패에 과거 runtime identity를 현재 값처럼 붙이지 않으며,
config/runtime 관측 도중 철회된 grant로 CAS에 도달하지 않는다. 이 순서는 여러 외부 원본의 원자성을 주장하지 않는다.

## 4. 구현 순서와 의미 있는 RED

1. 기존 동작과 CP 기대값을 별도 fixture로 고정한다. current no-op의 revision 증가와 stale
   요청의 쓰기를 탐지하는 oracle을 먼저 만든다. import/API 미존재 오류는 behavior RED가 아니다.
2. 기존 mutation의 파일 안전성·legacy 동작을 유지하면서 CAS 비교와 no-op 분기를 분리한다.
3. write 전/replace 후/ACK 유실을 구분하는 typed 결과와 read-back receipt를 연결한다.
4. 같은 host revision을 공유하는 두 process와 실제 flock을 barrier로 경합시킨다.
5. core 명령→operations→실제 설정 bytes까지 검증하고 인접 회귀·독립 검토를 마친다.

| 정본 TC | 사건 | 독립 oracle / 금지 효과 |
| --- | --- | --- |
| CP-D09 정상 | A Pause→현재 R로 Resume, B override 존재 | A만 바뀌고 B/host 보존. 유효 Resume 뒤 같은 후보의 bounded 효과 진행 |
| CP-D09 no-op | 현재 R·동일 mode·revision 상한 | write/revision/time 증가 0. 상한에서 상태 변경만 거절 |
| CP-D09 경합 | 같은 R의 두 process를 lock 전 barrier에서 해제 | 한 번 R+1, 다른 요청 stale. desired mode가 같아도 stale 성공 합성 0 |
| CP-D07/09 | null/stale/runtime 변경·host paused·project stopped | 잘못된 쓰기 0, 강한 제한 유지, 다른 target 갱신 0 |
| CP-D12/18 | replace 전 실패/후 fsync 실패/ACK 유실/재시작 | 확정 무효과와 unknown 구분. snapshot 한 번, blind mutation retry·가짜 receipt 0 |
| CP-D13, VF-D07 | effect→Pause, Pause→effect, preflight→Pause→dispatch | 실제 dispatch 시각과 설정 bytes로 판정. 적용 후 신규 dispatch 0; 이전 전송의 late commit은 원래 효과로 대사 |

## 5. 검증·리뷰·완료 증거

명령은 저장소 루트 기준이며 허용된 격리 실행 환경 안에서 사용한다. 저장 계층과 후속 내부 handler의 실행 증거는 [검증 기록](verification.md)에 구분한다.
기존 suite를 확장하되 신규 selector는 파일·case가 만들어진 뒤 수집 결과를 확인한다.

```sh
# 기존 suite / 새 사례 포함
python3 -m unittest discover -s tests -p 'test_operations.py' -v
python3 -m unittest discover -s tests -p 'test_operation*.py' -v
python3 -m unittest discover -s tests -p 'test_control.py' -v
python3 -m unittest discover -s tests -p 'test_final_controls.py' -v
# 신규 저장 계층 suite
python3 -m unittest discover -s tests -p 'test_admission_cas.py' -v
# 내부 handler suite
python3 -m unittest discover -s tests -p 'test_control_commands.py' -v
```

D는 실제 임시 파일·OS lock/process까지 필수다. L은 N/A: 모델 판단·prompt를 바꾸지 않는다.
O의 native/앱 왕복은 이 core 단계의 범위가 아니며 P06/P16에서 확인한다. D 성공을 설치본의
중단/재개 증거로 세지 않는다. 최종 후보의 전체 Python/필수 CI는 공통 절차를 따른다.

독립 리뷰는 expected 보존, lock 업그레이드/대기, replace 전후 오류, no-op/상위 제한,
이미 전송된 원격 효과와 신규 dispatch 구분을 확인한다. 완료 증거는 exact head의 RED/GREEN,
barrier 사건열·최종 bytes, 수집된 사례, 회귀/CI/리뷰와 공개 가능한 diff다.

## 6. 호환·회복·인계

admission store version=1과 legacy set_mode/v2 응답 의미를 유지한다. 새 CAS 보장을 구형 호출에
소급 표시하지 않는다. 재시작 뒤 현재 설정은 복원하지만 사라진 request receipt는 발명하지 않는다.
unsafe state는 초기화하지 않고 원래 파일/owner를 보존한다. 캐시나 DB로 복구 기록을 추가하지 않는다.
다음 P05/P12에는 handler 판본·지원 action·시험 증거를 연결하고, native/UI 구현 여부는 별도로 남긴다.

## Installation-scoped STDIO admission profile

This increment completes the authority adapter for project Pause and explicit Resume.
The existing protected host configuration may contain `native_admission_control`:

```toml
[native_admission_control]
schema_version = 1
enabled = true
repository_ids = [101]
# expires_at = "2030-01-01T00:00:00Z"
```

The principal is every launcher or agent able to use this trusted installation's
STDIO connection and protected host configuration. This is an explicitly shared
principal, without a per-human or per-worker authentication claim. Registered names,
client metadata, task IDs and request arrival cannot grant authority by themselves.
The profile is absent by default. Its schema is closed: exact integer version 1,
strict boolean `enabled`, a list of zero through MAX_PROJECTS unique positive numeric
repository IDs within the command integer range, and optional UTC-second expiry in
`YYYY-MM-DDTHH:MM:SSZ` form. Boolean IDs, native TOML datetime objects, unknown keys,
duplicates, noncanonical or impossible timestamps and over-limit values are invalid.
An empty set grants no repository. An omitted expiry lasts until operator revocation.

The existing safe loader validates the profile. Semantic config identity includes
all profile fields with repository order normalized; absence preserves legacy config
identity. The provider is bound once to the command server's absolute config locator,
re-reads it at both existing authority checks, and returns only native admission_set
scope. Registered-name/current-numeric-ID matching, runtime/admission expectations,
nonblocking CAS and durable read-back remain in the common command core.

Removal, disablement, scope removal, expiry, unsafe/unreadable settings or a changed
runtime invalidate the affected command. Expectations are never silently refreshed.
Expiry at the current instant is expired. Revocation does not change admission state
or undo completed effects. The last authority read and the CAS are separate sources;
a revocation immediately after that read is not atomically coupled to the CAS.

Standalone STDIO main injects this optional provider. Embedded create_server callers
retain default deny unless they explicitly supply a trusted provider. No new wire
operation, listener, credential, scheduler, permission store or provider callback from
request data is introduced. This scope excludes host/global controls, project Stop,
native turn control, decision_apply, checkpoint, execution, delivery and protected
approvals. Answers, wakes and continuations cannot implicitly Resume a project.

Acceptance: actual temporary admission storage and the official SDK must demonstrate
Pause, read-back and a separate fresh-expectation Resume while preserving host/beta;
invalid/disabled/expired/foreign scopes and unsupported actions have zero effects;
source-time revocation/config replacement is rejected; main wiring and five legacy
tools remain covered. Freeze independent positive and forbidden-effect cases before
code, observe meaningful RED then GREEN and relevant regression, and retain exact-head
CI and independent reviews. Installed/native operation and deployment selection are
separate evidence and remain NOT RUN until the actual chosen installation is exercised.
