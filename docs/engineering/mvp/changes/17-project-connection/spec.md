# P17 — 기존 host에 프로젝트를 연결하고 남은 책임을 보존해 해제

Revision: 2 · 상태: 설계 후보 · 2026-10-19 · 번호는 계획 ID이며 실제 PR 번호가 아니다.
공통 기준은 [PR 규약](../README.md)이다. 이 명세의 구현·실제 연결 관측은 NOT RUN이다.

## 1. 목적·요구·범위

[제품 F01](../../../../product/mvp-design.md#42-전체-기능-조작표)의 연결·설정·해제에 구현 owner를 둔다.
R01/R06/R12–16과 [PC-R1–7](../../contracts/project-connection.md)을 구현한다. P16 화면에 이미
등록된 프로젝트만 표시하는 것으로 새 연결과 해제를 대신하지 않는다.

| 여섯 설계 항목 | 이 기능의 결과 |
| --- | --- |
| 목적 | 대상·실제 원본·지원 한계를 확인하며 연결하고 잔여 책임을 잃지 않고 해제 |
| 책임 | 기존 host config가 연결 의도, admission이 신규 효과 제한, 원래 provider가 자격/자원 사실 |
| 동작 | read-only preview→exact config/admission CAS→원본 read-back→source 관측 |
| 실패·복구 | 두 store의 부분 적용과 유실을 기존 설정/원본으로 재발견, 중복 연결/자동 Resume 없음 |
| 완료 | 새 연결·update·restart·해제 대기→정상 해제·마지막 0-project·자격 철회의 D/O |
| 범위 | 같은 host registry/lock 재사용. 새 DB·자격 provider·프로젝트/task 생성·워크플로우 위임 제외 |

## 2. 현재 source와 선행

현재 `hydra_sdlc/cli.py`에는 init/add/connect/config writer가 없다. `load_host_config`는
bounded/no-follow host TOML을 읽고 repos 1개 이상, canonical repository, task locator subset을
검사한다. `OperatingControl`은 등록되지 않은 target을 거절하고 제거된 override는 보존한다.
`load_project`는 실제 GitHub numeric ID와 protected `.hydra.toml`을 대조한다. 이를 그대로 재사용한다.

선행은 현재 안전한 host 설정·admission 및 현재 runtime/config identity다. 신규 설정 profile은
구버전 loaded writer가 끝나고 pending 효과를 대사한 뒤 활성화한다. P02의 stale guard/P15의
exact cleanup 능력은 해당 효과에만 필요하며 P09 전체 전환을 전역 선행으로 두지 않는다.
native binding은 NC/P07의 실제 source가 확인된 만큼만 표시한다. 미지원은 GitHub read를 막지 않는다.
P02는 기존 admission v1 호환을 소유하며 P17은 이후 v2의 단일 trusted config locator/profile 확장을
소유한다. mode·revision 의미를 바꾸거나 P02 단계에 미리 새 version을 요구하지 않는다.

첫 host의 runtime/config 선택은 기존 trusted launcher/설치 경로를 따른다. P17은 provider 모듈·
자격·service 설치를 자동 구성하지 않는다. 기존 host에 비어 있는 새 profile을 사용할 수 있게 하며
임의 cwd·renderer payload에서 runtime/config 경로를 선택하지 않는다.

## 3. 입력·출력·구체 변경 소유

PC §2–4가 `connection_schema=1`, `project_connections`, ConnectionRequestV1/ReplyV1의
유일한 정본이다. 이 파일에 필드를 다시 정의하지 않는다. source action은 fixed CLI와 bounded
stdin JSON이다. 사람의 CLI/허용된 native caller/앱 모두 동일 core validation을 사용한다.
현재 CP CommandV1이나 다섯 MCP 도구를 미등록 config mutation으로 재해석하지 않는다.

필수 사용자 창구는 원격 Codex다. P17의 원격 경로는 PC가 허용하는 **Codex의 native caller →
trusted launcher가 고정한 connection CLI → 같은 core**다. caller가 실제 설치 host의 이 경로에
접근할 수 있는지, 원래 사용자 지시·정확한 대상·현재 권한을 전달하고 typed reply를 받을 수 있는지
최소 양성 실증으로 확인한다. 해당 접근이 없으면 remote connection capability는 미지원이며
사용자에게 로컬 CLI/앱 조작을 요구하는 우회로 v1 수용을 통과시키지 않는다. 새 MCP wrapper를
암묵적으로 추가하지 않으며 PC의 bounded JSON·fixed argv·config binding 경계를 유지한다.

이 명세는 core/원격 연결과 후속 보조 앱 통합 PR에 재사용한다. core·CLI·guard의 D 통과는
source 단계의 병합 근거이고, 실제 원격 Codex 연결·재시작·해제의 O가 필수 기능 완료 근거다.
앱 통합은 P16이 아래 wire fixture를 소비해 별도로 검증하며 그 전에는 앱 조작을 활성화하지 않는다.
앱 미완료는 검증된 원격 경로를 막지 않고, 원격 성공은 앱 검증을 대신하지 않는다.

| source | 구체 변경 |
| --- | --- |
| `hydra_sdlc/control.py` | profile 1 parser, 0-repo 지원, 설정 preview/read-back와 현재 desired 검사 |
| `hydra_sdlc/cli.py` | planned connection preview/apply/status, run/serve `--config`와 기존 argv/binding 대조, bounded JSON |
| `hydra_sdlc/operations.py` | version 2의 trusted config binding, 기존 exclusive barrier 안 config CAS/새 대상 stopped 선기록·부분 적용 대사 |
| `hydra_sdlc/runtime_identity.py` | 새 설정 필드의 canonical digest와 실제 startup identity/파일 read-back 구분 |
| `hydra_sdlc/mcp.py`, `native.py`, 기존 실행 effect 경계 | trusted config binding을 보유하고 fresh desired guard 적용; stale loaded controller의 쓰기 차단 |
| `hydra_sdlc/github.py`, `project.py` | 기존 실제 repository/protected policy 조회 재사용. 새 credential 경로 없음 |
| 예정 `tests/test_project_connection.py`, 기존 control/CLI/operations/runtime suite | preview·두 store crash·재시작·consumer·회귀 |
| P16의 `process.rs`, `protocol.rs`, app model | fixed-argv connection source action/strict reply 소비. 화면은 P16, producer와 wire fixture는 P17 |

내부 함수/모듈 분해는 재량이다. arbitrary shell command·provider factory 입력·새 registration DB는
재량이 아니다. CP read DTO와 직접 호환되지 않는 reply를 몰래 주입하지 않고 전용 typed consumer를 붙인다.

## 4. 구현 순서와 정상 경로

1. PC의 정상/유실/경합 expected를 독립 fixture로 작성한다. 무조건 hold·전부 unavailable도 실패하게 한다.
2. 기존 parser/identity를 additive profile로 확장하고 legacy 의미를 보존한다. unknown key/version과 zero-repo 차이를 시험한다.
3. read-only preview에서 실제 repo ID·현재 protected contract·선택된 native source·중복 이름/ID를 대조한다.
   같은 이름의 다른 ID, 같은 ID의 중복 등록, 다른 host/task의 locator를 임의 채택하지 않는다.
4. 기존 barrier의 내부 helper로 CAS/fsync/read-back과 v1→v2 전환을 구현한다. old writer 종료 뒤 admission binding→config profile 순서를 지키고 같은 lock을 재귀 취득하지 않는다.
5. connect는 stopped 먼저→설정 추가, disconnect는 durable desired 먼저→stopped를 구현한다.
   모든 신규 업무 효과의 fresh desired guard가 두 번째 순서의 crash를 막는지 함께 검증한다.
6. pending disconnect를 재시작에서 읽고 원본 대사→허용된 P15 정리/명시 인계→finalize까지 잇는다.
7. 마지막 제거의 빈 registry와 native/resource coverage unknown을 구분한다. 앱/CLI/MCP status가 빈 설정을 읽는 정상 결과를 검사한다.
8. core→CLI JSON→허용된 native caller의 실제 왕복과 기존 회귀를 확인하고 독립 리뷰한다.
   P16에는 같은 producer의 실제 wire·독립 기대값·오류 사례를 넘기고 Rust/TS consumer가 준비되면 별도 왕복을 검증한다.
9. 검토한 설치 후보에서 원격 Codex로 연결→read→해제 대기→잔여 해결→해제와 자격 철회 관측을 분리 수행한다.

## 5. 정상·장애 TC와 독립 oracle

| TC·요구 | 초기 상태/자극 | PASS oracle / 금지 효과 |
| --- | --- | --- |
| PC-D01 / R1–3 | running host에 새 valid repo 연결, native source partial·직접 config 추가 | stopped 선기록 뒤 한 등록, 미준비 override 없는 대상은 차단, GitHub read·native 한계 표시, task/Issue/Resume 0 |
| PC-D02 / R2–4 | duplicate name/ID·rename·다른 ID 재생성·foreign native locator | 정확한 동일 ID rename만 update, 충돌은 거절; 이름 기반 work/owner 승계 0 |
| PC-D03 / R2–5 | stale config digest/admission R, concurrent candidate 둘 | 하나만 적용·다른 요청 rejected; 최신 expected로 자동 재시도 0 |
| PC-D04 / R4–5 | connect의 stopped 전/후, config replace 전/후 crash·ACK 유실 | 미등록+stopped 또는 등록+stopped; 재조회/동일 요청 검증 뒤 정상 완료, dispatch 0 |
| PC-D05 / R4–6 | disconnect intent fsync 후 stopped 전 crash, CLI run/serve와 MCP controller의 cached running | trusted control binding에서 fresh desired 읽기, 재시작 전후 신규 업무 효과 0; desired 복원→stopped→같은 pending 책임 |
| PC-D06 / R5–6 | active/unknown/partial owner와 disconnect, 이후 실제 종료·보존 | pending에 원본/등록 유지, scoped cleanup-only 정상 진행→finalize; 자동 Resume/타 자원 삭제 0 |
| PC-D07 / R2·6 | 마지막 프로젝트 finalize, host에 무관 native 실행 | repos/locator/선언 빈 설정을 정상 조회, host zero-active/Quit 성공 추정 0 |
| PC-D08 / R7 | pending 중 credentials 철회·403, 뒤에 명시 재연결 | 즉시 provider 철회 허용·원본 unavailable·최소 참조 보존, 복구 뒤 같은 책임 정리. token 보존/계정 fallback 0 |
| PC-D09 / R2·4 | symlink/parent 교체·hardlink·쓰기 권한·크기·unknown profile·악성 stdin | 기존 설정 보존, raw 오류/secret 유출·provider import·임의 shell 0 |
| PC-D10 / R2·5 | v1/v2 runtime·old writer·migration 중간 crash·no-config/다른 config argv·MCP binding | legacy read 유지, old writer 종료 후 전환, unknown version·binding mismatch 쓰기 거절; trusted source 복구 후 정상 진행 |
| PC-D11 / R3·4 | CLI 정상 reply→native caller 및 준비된 Rust/TS, malformed/late/다른 operation·target reply | 각 경로별 정상 config/stopped/finalized를 구분, 다른 receipt 채택 0·partial 상태 유지. 한 경로의 PASS로 다른 경로를 완료 처리하지 않음 |
| PC-D12 / R1·6 | alpha 해제 pending/외부 config 제거, beta 정상, closed work/공유 schedule/인계 | 기존 override/ticket/provider로 alpha 책임 재발견, 공유 참조/beta 보존, 인수/보존 증거 뒤 alpha만 정상 해제 |

fault fixture는 store 파일·current guard·실제 consumer를 거친다. 함수 호출 횟수만으로 crash 원자성이나
normal progress를 통과시키지 않는다. PC-D05는 CLI `operate`와 MCP controller의 실제 효과 경계
각각에 old cached config를 보내고, PC-D10은 trusted binding을 request payload로 교체할 수 없음을 확인한다.

## 6. 검증·리뷰·회복·끝조건

| 상태 | 실행할 명령/관측 |
| --- | --- |
| 기존 suite, 새 사례 추가 | `python3 -m unittest discover -s tests -p 'test_control.py' -v` |
| 기존 suite | `python3 -m unittest discover -s tests -p 'test_cli.py' -v` |
| 기존 suite | `python3 -m unittest discover -s tests -p 'test_operations.py' -v` |
| 기존 suite | `python3 -m unittest discover -s tests -p 'test_runtime_identity.py' -v` |
| 예정; 생성·수집 확인 후 | `python3 -m unittest discover -s tests -p 'test_project_connection.py' -v` |
| consumer 연계, 기존 명령 | `npm --prefix apps/mac test`, `cargo test --locked --manifest-path apps/mac/src-tauri/Cargo.toml` |
| 예정 CLI; 현재 실행 불가 | `hydra connection status --config <installed-config>` 및 fixture의 preview/apply stdin |

공통 규약의 허용 runner를 사용한다. 이번 문서 작업에서는 명령·runtime을 실행하지 않았다.
D는 필수, L은 N/A다. typed 설정/identity/CAS에 taste 판단을 두지 않으며 자연어는 정확한 요청으로
해석될 때만 명령화한다. O는 원격 Codex의 허용된 native caller를 통한 실제 host의 새 등록·restart·pending 해제→잔여 해결→최종 해제와
자격 철회 후 한계 표시를 확인한다. destructive credential 시험은 별도 허용된 test 자격만 사용한다.
로컬 CLI 직접 실행은 core 관측이며 원격 O를 대체하지 않는다. 호출 경로가 unavailable이면 해당
O는 BLOCKED, 아직 실행하지 않았으면 NOT RUN이다. 앱 왕복·화면은 P16의 별도 수용 근거다.
review는 두 store 순서·fresh guard·source identity·실제 caller 권한·마지막 0-repo·private 경계를 본다.
source-only merge는 기능 비활성 상태로 가능하나 O 없이 실제 connection capability/v1을 완료하지 않는다.
실패 시 기존 설정/override/원본을 보존하고 현재 사실을 다시 읽는다. stale snapshot을 되써서 rollback,
자동 Resume·자격 복원·중복 연결·목표 재위임으로 복구하지 않는다.
