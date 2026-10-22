# P02 admission CAS — 저장 계층 검증

2026-10-19 · partial source candidate · 관련 작업: Issue #3 · P02 전체 미완료

[spec revision 2](spec.md), CP revision 7 중 `OperatingControl` 저장 경계만 구현했다.
`set_mode_if_current`는 expected revision을 같은 exclusive lock 안에서 비교한다.
기존 `set_mode`와 파일 version=1을 유지한다. 공통 typed command handler, numeric repository
identity 해결, runtime binding guard와 CommandReplyV1 receipt는 아직 구현되지 않았다.
이 내부 API를 MCP/CLI/앱의 안전한 원격 제어 기능으로 광고하지 않는다.

## 증거와 한계

| 검증 | 관측 결과 |
| --- | --- |
| 의미 있는 RED | 기존 동작에 current no-op과 stale same-mode 요구를 적용하자 두 assertion이 실패함 |
| CP-D09 | 현재 revision에서 no-op은 bytes/revision/time 불변; 실제 변경만 R+1; 타 project/host 제한 보존 |
| CP-D09 실제 process | 같은 R에서 두 process가 경쟁하면 한 번 적용되고 다른 요청은 stale_revision |
| CP-D13/VF-D07 | 실제 shared effect lock이 끝난 뒤 Pause가 적용되고 신규 effect는 거절됨 |
| CP-D12/18 | replace 이전 확정 실패, 교체 이후 fsync/read-back/lock 종료/descriptor 실패의 unknown, 한 번의 재관측·재시작 후 stale 거절 |
| 신규 suite | `test_admission_cas.py` 12개 PASS; fixture 성공을 native 실행 종료로 세지 않음 |
| 독립 검토 | 교체 후 lock 종료 실패가 일반 거절로 분류되던 문제를 RED로 재현 후 수정; 후속 scoped 검토에서 추가 P1/P2 없음 |


검증 환경은 Python 3.12와 repository pin의 `mcp==2.3.0`, `mcp-types==2.3.0`이다.
기존 변경을 보존한 격리 검증 checkout에서 실행했다. CI의 Python 3.11/3.14.2 결과를
대체하지 않는다. 원격 CI, merge, 설치·재시작 및 원격 Codex 종단 수용은 이 기록의 PASS가 아니다.

unknown의 observation은 현재 설정이며 원래 요청의 성공 receipt가 아니다. 결과가 불명확한
쓰기의 자동 재시도는 하지 않는다. snapshot 재관측도 실패하면 observation=null을 유지한다.
전송이 끝난 원격 효과나 native turn을 이 파일 변경으로 취소했다고 주장하지 않는다.

## 검증한 내용의 식별

| 파일 | SHA-256 |
| --- | --- |
| `hydra_sdlc/operations.py` | `7712dc7c1f50500a386a1d86fde1e6fce9115f3b30af2ec5ca26ca8f6acae4cc` |
| `tests/test_admission_cas.py` | `28b976add64de7df59060aaff36374b1ddd4dad8666e011f041cd48bb67dd3f0` |

## 다음 경계

P02의 남은 결과는 typed command→target/runtime 검증→이 CAS store→실제 read-back receipt다.
그 뒤에도 원격 사용자·transport 자격은 별도 검증해야 한다. P01 진단의 unverified 값을
권한으로 사용하거나, legacy broad 도구로 Pause/Resume을 대신하지 않는다.

전체 회귀 903개 실행·환경 누락 보완·해당 suite 13개 재실행과 25개 조건부 미실행의
근거는 [공유 회귀 기록](../01-native-context/verification.md#전체-회귀-실행--2026-10-19)에 있다.

## Typed admission core — 2026-10-19 후속 source 검증

위 저장 계층 기록과 hash는 당시 판본의 역사적 증거로 유지한다. 후속 구현은
[spec revision 4](spec.md)의 내부 handler 범위이며 공개 transport·설치·원격 운영을 포함하지 않는다.
`control_commands.execute_admission_command`가 안전한 config loader, 기존 repository reader,
명시적인 내부 caller context, 기존 CAS store를 연결한다. 기존 control/operations 구현은
이번 단계에서 수정하지 않았다. 별도 command journal·runtime·MCP tool은 추가하지 않았다.

| 검증 | 실행 결과와 oracle |
| --- | --- |
| 의미 있는 RED | typed guard 전 CAS forwarding baseline에서 stale runtime과 caller authority 없음 두 사건 모두 실제로 applied가 되어 2개 assertion FAIL. import/API 부재 오류가 아님 |
| 신규 handler TC | `test_control_commands.py` 25개 PASS. bridge/native의 명시적 scope와 binding, numeric target, 현재 runtime/config, strict malformed 입력, exact reply/receipt 확인 |
| 조회 중 변경 | 실제 독립 file description으로 remote lookup 중 admission lock이 비어 있음을 확인. context 권한·binding·config 변경은 쓰기 전 거절하며 callback이 원 command를 바꿔도 검증한 사본의 대상 유지 |
| receipt 경합 | 실제 CAS가 R+1을 적용한 직후 다른 writer가 R+2를 기록해도 원 receipt와 observation은 R+1을 보존 |
| 중복·불확실 | 동일 request의 이전 expected 재전송은 stale. 실제 replace 후 fsync 실패는 unknown과 현재 관측만 반환, receipt 생성·재변경 없음. 관측 미확인도 그대로 유지 |
| source 오류·비공개 경계 | config 조회 전후의 종료 오류·repository/context 오류를 고정 reason으로 반환. 경로·원문·합성 canary·미지원 future payload를 응답에 복제하지 않음 |
| 거절 응답의 binding | 독립 검토의 미지원 응답 binding 누락을 2개 TC의 5개 assertion RED로 확인. context 검증과 effect 권한 검사를 분리한 뒤 bridge UUID/native null 및 stale·미확인·config 실패 응답 확인 |
| 인접 회귀 | 아래 suite selector를 합쳐 167개 PASS, skip 0. 실제 파일/lock/process, legacy control와 MCP SDK stdio 경계 포함 |

실행 환경은 기존 Python 3.12와 고정 optional MCP dependencies다. 지정된 격리 storage runner에서
저장소 루트를 기준으로 다음과 동등한 내부 명령을 실행했다. 실행 환경의 private 경로는 공개하지 않는다.

```sh
# RED: 실제 두 거절 요구를 만족하지 못하는 baseline
python -m unittest discover -s tests -p test_control_commands.py -k stale_runtime -k missing_authority -v
# 검토 수정 RED: 수정 전 미지원 응답의 binding 및 stale 거절 요구
python -m unittest discover -s tests -p test_control_commands.py -k unsupported_reply -v
# GREEN: 같은 후보의 신규 및 인접 회귀
python -c 'import unittest; patterns=("test_control*.py","test_operations.py","test_operation_*.py","test_admission_cas.py","test_runtime_identity.py","test_mcp.py"); suite=unittest.TestSuite(unittest.defaultTestLoader.discover("tests",pattern=p) for p in patterns); result=unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())'
```

| source artifact | SHA-256 |
| --- | --- |
| `hydra_sdlc/control_commands.py` | `89400272f2ff79fe63415346d20b343a0ee7cebc5525b628958eee94b94811e2` |
| `tests/test_control_commands.py` | `edea18d070965744d8928cf003a4c5660f41433d90986c890e2217ecdfac084c` |

내부 context의 양성 fixture는 실제 사용자 인증이나 native source의 qualification을 입증하지
않는다. native null binding과 bridge UUID binding 모두 core에서 처리하지만 실제 transport가
현재 권한의 context를 생성하는 adapter는 없다. JSON duplicate key 검사는 decoded dict 이전
transport의 책임이며 이 단계에서 지원으로 표시하지 않는다. 원격 CI·최종 독립 리뷰·merge·설치와
원격 Codex 종단 수용은 아직 이 source 검증의 증거가 아니다. 기존 전체 회귀 기록을 이 신규
handler의 full-suite 성공으로 소급하지 않는다.

## Typed 명령의 lock 경합 — 2026-10-19 검토 수정

앞선 167개 결과와 source hash는 수정 전 증거다. 독립 검토에서 synchronous typed 요청이
context/config 검증 후 exclusive lock을 오래 기다릴 수 있는 문제를 확인했다. 같은 P02
revision 4의 범위에서 typed CAS와 불확실 결과의 한 번 재조회에 `blocking=False`를 적용했다.
legacy `set_mode`와 CAS의 기본 대기 정책, async 호출의 기존 비차단 정책은 유지했다.

| 검증 | 관측 결과 |
| --- | --- |
| 실제 process RED | shared lock 보유 중 typed 명령, 교체 후 fsync 실패 뒤 exclusive lock 보유 중 recovery read의 두 TC 모두 unlock 전 응답 요구에서 FAIL. 기존 API를 호출한 행동 실패이며 새 인자 부재 오류가 아님 |
| typed 경합 GREEN | 실제 별도 프로세스가 shared holder의 unlock 전에 waiting/busy와 null receipt를 반환하고 exit 0. bytes/revision은 unlock 전후 불변이고 늦은 mutation 없음 |
| 불확실 관측 GREEN | 실제 replace 뒤 fsync 오류와 recovery 직전 barrier를 사용. 다른 exclusive holder의 unlock 전에 unknown·관측 없음·receipt 없음으로 종료하며 revision은 한 번만 증가 |
| 후속 요청·내부 인자 | 별도 명시적 요청은 철회된 grant와 변경된 config를 각각 거절. bool이 아닌 blocking 인자는 store 디렉토리 생성 전에 거절 |
| 회귀 | 신규 handler 28개 PASS. 앞선 인접 suite selector의 현재 후보 173개 PASS, skip 0. 기존 동기 CAS의 실제 process 대기·동시 writer, no-op/stopped/stale/unknown, legacy lock과 MCP stdio 포함 |

같은 지정 storage runner와 Python 3.12 환경에서 아래 RED를 실행한 뒤 앞선 GREEN selector를
다시 실행했다. `git diff --check`도 통과했다.

```sh
python -m unittest discover -s tests -p test_control_commands.py -k returns_busy -k recovery_returns_unknown -v
```

| 수정 후 source artifact | SHA-256 |
| --- | --- |
| `hydra_sdlc/operations.py` | `3dc18f2f6bfa6b330444e2705788e875cdd6d5def8838216a78ed24095fc84f6` |
| `hydra_sdlc/control_commands.py` | `19cb5cce4d6c6489d27c01b3a42119613cada601bd6adc72c31199ee2946a6a7` |
| `tests/test_control_commands.py` | `0853b8a7e7f893826ed018f66bcc6dec41c7fe92221dbc8c97ece2139ab88d94` |

비차단은 lock 경합에서 기다리지 않는다는 의미다. filesystem I/O 전체의 시간 상한이나 외부
grant/config와 local CAS 전체의 원자성을 보장하지 않는다. remote I/O·권한 callback을 lock
안으로 이동하지 않았고 내부 mutation 재시도도 추가하지 않았다. 최종 독립 review·원격 CI·설치와
native transport qualification은 별도 상태로 유지한다.

## 최종 격리 후보와 복합 recovery 오류 — 2026-10-19

수용·검토 기준은 `ad9d6382465023b9aa11e8f662c2d6d906216e10`의 P02 revision 4와 CP revision 7이다.
그 설계 baseline에 P02의 네 source/test 파일과 이 검증 기록만 적용한 후보를 검사했다.
P01 및 후속 source 호환 변경은 이 후보에 포함하지 않았다.

독립 코드 검토에서 설정 교체 뒤 재관측의 읽기와 descriptor 정리가 함께 실패하면 raw
`OSError`가 unknown 결과를 벗어나는 경로를 발견했다. 한 번의 recovery snapshot에서
`OperationDenied`와 `OSError`를 함께 처리하여 관측 없는 unknown을 유지하도록 수정했다.

| 검증 | 결과와 한계 |
| --- | --- |
| 행동 RED | 실제 replace 후 parent fsync 실패, recovery의 실제 read 실패, 실제 lock descriptor 종료 후 오류를 순서대로 주입. 기존 handler에서 raw OSError가 전파되어 1개 TC ERROR |
| 같은 TC GREEN | unknown, receipt/관측/효과 참조 없음, 재관측 1회, revision 증가 1회, 원문 canary 비노출 확인 |
| 격리 전체 Python | `python -m unittest discover -s tests`: 931개 수집, 906개 PASS, 25개 skip, 실패 0; Python 3.12.7, 고정 MCP SDK 포함, 259.816초 |
| 독립 검토 | 최종 후보의 전체 P02 변경을 코드·보안 검토. 복합 recovery 지적 해결 확인, 남은 material finding 없음. 정적 검토와 실행 결과는 별도 증거 |

최종 source artifact의 SHA-256은 다음과 같다. 앞선 930개 전체 검사와 173개 회귀는 각각
수정 전 후보의 증거이며 이 최종 판본으로 소급하지 않는다.

| source artifact | SHA-256 |
| --- | --- |
| `hydra_sdlc/operations.py` | `1254ffaeb179a5c75f5ed6968cca37503073115f3a8703a0488df25a86dbaaab` |
| `hydra_sdlc/control_commands.py` | `19cb5cce4d6c6489d27c01b3a42119613cada601bd6adc72c31199ee2946a6a7` |
| `tests/test_admission_cas.py` | `28b976add64de7df59060aaff36374b1ddd4dad8666e011f041cd48bb67dd3f0` |
| `tests/test_control_commands.py` | `f4615280ba5b34d37ab90aded5faf255e57c0b724e6bc93aacd1e9787e1b8224` |

이 단계는 내부 handler와 저장 경계의 source 검증이다. 후속 transport 인증, 실제 원격
Codex 조작, 설치·운영 수용은 포함하지 않는다. 원격 CI·보호 병합·main 확인도 아직 남아 있다.


## 현재 main 코드와의 통합 재검증 — 2026-10-20

위 931개 결과는 원래 P02 source 후보의 역사적 증거다. 이번 검증은 main 코드
`c198a49b537fbcca5598377d3a5e33f7a64c2c7e`와 승인된 설계 문서 기준을 합친
`a240bc1a86a969b7247b4df2f33ee1641512be35`(tree
`da00be72c05caefcd91f864b878235b8a0d0c544`)에 위 최종 artifact의 네 source/test 파일만
적용한 별도 격리 snapshot을 대상으로 했다. 네 파일의 bytes는 원래 검토 판본
`29db133018dc69f60e97808d2652db8280ab380c`와 동일하다. 기존 931개 결과를 이 통합 판본의
실행 증거로 대신하지 않았다.

P02 revision 4와 CP revision 7은 수용 판본과 bytes가 같다. 현재 main의 `native.py`,
`test_operation_integration.py`, CI workflow는 overlay에서 제외하고 원래 hash를 유지했다.
따라서 native writable/review/stale-review retirement와 실제 concurrent Pause의 순서,
Pause 이후 retirement 거절, ACK/read-back 유실 뒤 exact stopped recovery를 포함한 기존
main의 경계를 함께 검사했다. P01/P03/P05와 후속 MCP source는 이 패킷에 포함하지 않았다.

| 실제 통합 검증 | 결과 |
| --- | --- |
| focused admission·운영 경계·native·checkpoint 회귀 8개 selector | 177개 PASS, skip 0, failure/error 0, 32.292초 |
| 같은 snapshot 전체 `python -m unittest discover -s tests -v` | 947개 수집·실행, **922 PASS, 25 skip, failure/error 0**, 253.734초, exit 0 |
| 실행 환경 | Python 3.12.7, `mcp==2.3.0`, `mcp-types==2.3.0` |
| 보존 검증 | snapshot 187개 파일, 네 overlay 파일, 제품 checkout 파일과 HEAD의 실행 전후 hash/identity 동일 |

25개 skip은 직전 main native retirement 검증의 skip 항목 집합과 동일하며 PASS로 세지 않는다.
focused selector는 `test_admission_cas.py`, `test_control_commands.py`, `test_operations.py`,
`test_operation_boundary.py`, `test_operation_integration.py`, `test_native.py`,
`test_native_wait_identity.py`, `test_checkpoint_continuation.py`다. focused 통과 뒤 전체 suite를
한 번 실행했으며 그 후 source/test 변경은 없다. 이 문단은 관측한 결과만 추가한 검증 문서다.

이 결과는 현재 main 코드와의 source 호환·격리 fixture 검증이다. 실제 배포 시 remote base와
최종 head를 다시 대조하고, 해당 head의 필수 review/CI와 보호 병합 및 실제 merge SHA의 main
검사를 각각 확인해야 한다. transport 인증·원격 Codex 조작·설치 runtime qualification은
이 결과로 통과 처리하지 않는다.


## PR #11 오류 분류·권한 갱신·관측 시각 수정 — 2026-10-20

리뷰 대상 `4e2f55e9c6afdd5acd8a290c5d86026ad3c54a45`(tree
`884c5e971283bcd6bd7daaddc16496130c33af7e`)의 네 지적을 P02 revision 4 안에서 수정했다.
maintained spec §3.2는 아래 경계와 오류 우선순위를 명시한다. 위 947개 결과는 수정 전 증거다.

- 지원하지 않는 schema/action의 object body는 common identity/container 검증 뒤 opaque하게
  분기한다. 지원 admission의 closed fields는 유지한다.
- 실제 replace의 성공과 실패를 구분한다. 좁은 permission 오류와 잠금 안 destination 불변이
  함께 확인될 때만 확정 거절하고, 효과 후 오류·불명확한 오류·확인 실패는 unknown을 유지한다.
- 성공 CAS·no-op·한 번의 unknown 복구 관측에서 snapshot/time을 같은 잠금 안에서 얻는다.
  formatter는 새 clock/read를 호출하지 않는다. legacy dict API와 저장 schema는 유지한다.
- repository 조회 후 current config/runtime을 관측하고 authority를 마지막에 갱신한다.
  config 실패, current authority, repository 결과, 원 expected와 runtime 비교 순서로 판정한다.
  설정 조회 중 철회된 grant로 쓰지 않으며 외부 원본 전체의 원자성을 주장하지 않는다.

| 관측한 검증 | 실제 결과와 oracle |
| --- | --- |
| 수정 전 행동 RED 9개 | assertion 실패 7개, 잘못된 unsupported 분류의 business error 1개, 기존 ambiguous-error 보존 1개 PASS. import/API 부재 오류는 아님 |
| 같은 selector 수정 후 GREEN | 9 PASS, 0 skip, 0.032초 |
| 추가 regression 포함 focused 8개 suite | **189 PASS, 0 skip**, failure/error 0, 32.097초 |
| 같은 최종 source/test/spec의 전체 suite | **959개 수집·실행, 934 PASS, 25 skip**, failure/error 0, 254.857초, exit 0 |
| 독립 코드·보안 리뷰 | 아래 frozen source/test와 spec의 경계 검토 완료, 추가 material finding 없음. 정적 리뷰는 실행 결과와 별도 |
| 실행 전후 보존 | 격리 snapshot·overlay·제품 checkout 파일 hash 및 제품 HEAD 불변 |

RED/GREEN과 focused/full은 Python 3.12.7, `mcp==2.3.0`, `mcp-types==2.3.0`에서
수행했다. 25개 skip은 수정 전 947개 suite의 항목 집합과 정확히 동일하며 PASS로 세지 않는다.
기존 실제 process 경합·retirement 회귀와 함께, 신규 TC는 실제 replace 전후 오류, recovery
실패, intervening writer, 잠금 내 clock, 설정 재조회 중 권한 철회 및 runtime 변경을 검증한다.
focused/full 이후 source/test 변경은 없다. 이 문단은 관측 결과만 추가한 검증 companion이다.

| 최종 source artifact | SHA-256 |
| --- | --- |
| `hydra_sdlc/operations.py` | `ff959755823234b44f6a7e656157ae5d69a03f4b41e7160c1fa0d6712efcc1c1` |
| `hydra_sdlc/control_commands.py` | `b911cd7a1c2a33f93b0d760c4645468aca57247adc9a7c8c96ed49da6afc8bbc` |
| `tests/test_admission_cas.py` | `3c733cc2206ee458c86ad34657237698f1bb33fd36b8fd519db8c00693936fd5` |
| `tests/test_control_commands.py` | `0011630e8ed5ac055b0df6e3c3f5325409888f72652c33f3542e44987d49b41f` |

새 head의 hosted CI·코드/보안 리뷰, 보호 병합 및 실제 main 검증은 별도로 확인한다.
이 결과는 설치된 transport의 권한 활성화·실제 원격 Codex 조작·운영 수용의 증거가 아니다.

## Installation-scoped STDIO admission increment

P02 revision 5 implements the explicit shared-installation project-admission
policy through the protected host loader, semantic identity, a native-only internal
provider and standalone STDIO main. Configuration is absent/default-deny; enabled
numeric scopes permit only project Pause and a separate explicit Resume. No native
human/task identity or additional workflow/termination authority is claimed.

The frozen `test_native_admission_profile.py` contains twelve methods. Actual base
`1aedced3120f3673ff74b1500d9092cc00ed2549` rejects their valid profile inputs,
producing twelve purpose assertions without errors/skips. The unchanged oracles
pass after implementation. Coverage includes schema/type/count/expiry validation,
semantic identity and stale expectations, actual temporary-store Pause/read-back/
Resume, unchanged host/other-project state, absent/disabled/empty/expired/foreign
scope, source-time revocation and expiry, unsafe config replacement, fixed config
locator, actual SDK context routing and real STDIO-main consumption with all six
tools. No installed settings, selected client, native task or production gate is
changed by these fixtures.

Relevant CLI/control/runtime/MCP/STDIO/checkpoint/operations/resource regressions
collect and pass 300 methods without failures, errors or skips. Subprocesses use
the actual candidate source. Six corpus headers are rebound to CP revision 9;
all non-contract case data and behavioral oracles match immutable base data.
CP9 adds the authority-source contract without changing the wire or admitting
future unqualified command sources. Earlier incomplete test observations remain
diagnostics, not final passing evidence.

Exact final-head CI and independent code/security reviews, protected merge and
actual-main checks remain delivery gates. Actual selected-installation operation,
authenticated native Q&A/control/recovery, two-project acceptance and full v1 D/L/O
remain unqualified. Deployment targets and actual activation are separate from
policy adoption and local SDK success.
