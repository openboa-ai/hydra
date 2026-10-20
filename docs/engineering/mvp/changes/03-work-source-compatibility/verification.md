# P03 — 보호된 작업 원본 호환 검증

2026-10-19 · source candidate · 작업: Issue #3

구현 기준은 `ad9d6382465023b9aa11e8f662c2d6d906216e10`의 P03 revision 1과 WR §10이다.
P02 parent `29db133018dc69f60e97808d2652db8280ab380c` 위에서 아래 범위만 변경했다.
P03 spec §3.1은 같은 책임 안에서 호출 context, effect guard, partial native ticket과 완료 예외의
구현 경계를 구체화한다. source 선택권·사용자 권한·공개 transport는 추가하지 않았다.

## 변경과 요구별 증거

| 요구 | 구현·관측 |
| --- | --- |
| P03-D01 | v1 closed fields와 기본값 불변. 고정 Issue의 intake 결과를 literal expected와 비교. UTF-8 title/body의 고정 SHA-256으로 기존 digest를 검증하고 label 제외·본문 변경을 확인 |
| P03-D02 | 실제 TOML reader를 거친 v2+legacy로 CLI implementation과 기존 native task 진행. native executor를 native work source로 해석하지 않음 |
| P03-D03 | v2+github_native는 config와 issue/Projects planning을 읽지만 legacy intake·step·cycle·native begin은 실행하지 않음. 모델·workspace·GitHub writes 0회 |
| P03-D04 | source 누락/unknown/type, version bool/unknown, planning unknown/extra/missing keys, legacy+Projects, opaque ASCII ID/길이와 option map 개수·정수 범위를 검증. 실제 TOML의 200자 ID·100개 map·±1000 양성 fixture 포함 |
| P03-D05 | prepare 뒤·CLI intent write 뒤·모델 반환 뒤·native ticket/intent/최종 grant 사이 source/Pause 변경을 주입. 다음 신규 효과를 보류하며 미답변 product decision을 보존 |
| P03-D06 | local candidate `.hydra.toml`의 native source 변경은 무시. fake transport의 실제 reader가 exact protected revision만 읽는 것을 확인 |
| P03-D07 | foreign owner와 unknown publish intent, partial native ticket은 source 변경 뒤에도 그대로 유지. coordinator lock의 실제 파일 ticket이 남고 임의 새 호출은 HostBusy. exact stop만 원래 조건으로 정리 |
| P03-D08 | current v2+native 정책에서도 정확한 이미 병합된 작업의 pinned completion 가능. unmerged/foreign/wrong head는 거절하고 active native 결과 채택에는 completion-only 예외를 쓰지 않음 |

`tests/test_operation_integration.py`의 기존 경쟁 Pause 테스트 이름을 실제 보장에 맞춰
바꿨고, 미답변 decision·dirty checkpoint·resume 금지 assertion은 그대로 유지했다.
remote policy read마다 별도 file description의 `LOCK_EX | LOCK_NB`를 실제로 획득하는
oracle은 조회가 admission lock 밖에서 이루어짐을 확인한다. missing/wrong repository의
내부 context는 callback 호출 없이 거절하고 호출 종료 후 scope가 복원됨을 검사한다.

## 초기 세 source 후보의 RED → GREEN — 역사적 기록

| 단계 | 실제 결과 |
| --- | --- |
| reader RED | 유효 v2+legacy fixture가 구버전 reader에서 `Unknown project configuration fields`로 거절되어 실패. import/API 부재 오류가 아님 |
| execution RED | reader만 추가한 후보에서 v2+github_native가 capabilities/spec_review/capabilities/implementation을 호출하여 금지 호출 0회 assertion FAIL |
| final grant RED | intent 뒤 최종 admission 직전에 실제 Pause를 적용하자 waiting 응답의 exact step identity가 누락되어 assertion FAIL. ticket을 유지하는 recovery reply로 수정 |
| completion RED | 실제 native implementation assignment와 merged PR fixture에서 completion-only 정책이 active candidate 결과를 채택하여 거절 assertion FAIL. active checkpoint에는 그 예외를 사용하지 않도록 수정 |
| 핵심 중간 GREEN | reader·completion·work source 세 suite의 당시 52개 PASS |
| 인접 GREEN | 아래 8개 selector를 같은 후보에서 실행: 214개 PASS, skip 0, 30.000초. 실제 Git native checkpoint/재시작과 기존 admission·dispatch 복구 회귀 포함 |
| 마지막 추가 oracle | CLI intent write callback의 source 변경 테스트 1개 PASS. 기존 post-write `_latest`가 차단하므로 추가 source 수정 없이 TC만 보강 |
| 정적 검사 | `git diff --check` PASS. 고정 source diff의 별도 정적 검토에서 추가 P1/P2 없음; 실행 검사와 구별 |

개발 중 기존 direct `_publish` 호출의 scope 누락과 admission 미설치 stopped recovery의
policy guard 충돌도 인접 회귀에서 발견하고 해당 기존 경로를 보존하도록 수정했다.
위 214개 결과는 이 수정과 final grant/completion 수정 이후의 세 source 파일을 검사한 결과다.
마지막 추가 TC를 포함한 최종 전체 suite·독립 최종 review·CI는 별도 exact candidate에서 기록한다.

## 초기 후보 실행 명령과 판본 — 역사적 기록

Python 3.12와 repository pin의 dependencies를 사용했다. 모든 검증은 등록된 storage
lifecycle wrapper 안에서 수행했으며 아래는 repository root 기준 내부 명령이다.

```sh
python -m unittest discover -s tests -p test_project.py -k v2_legacy -v
python -m unittest discover -s tests -p test_work_source_compatibility.py -k native_source_never -v
python -m unittest discover -s tests -p test_work_source_compatibility.py -k native_grant -v
python -m unittest discover -s tests -p test_work_source_compatibility.py -k merged_completion_exception -v
python -c 'import unittest; patterns=("test_project.py","test_policy_completion.py","test_work_source_compatibility.py","test_runner.py","test_native.py","test_native_wait_identity.py","test_operation_integration.py","test_dispatch_reconciliation.py"); suite=unittest.TestSuite(unittest.defaultTestLoader.discover("tests",pattern=p) for p in patterns); result=unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())'
python -m unittest discover -s tests -p test_work_source_compatibility.py -k after_cli_intent -v
```

| 검증 후 파일 | SHA-256 |
| --- | --- |
| `hydra_sdlc/project.py` | `e23f7cd236312498dba2228ed1c12478fbf802ad962574ba35042c89f74dda26` |
| `hydra_sdlc/runner.py` | `cf5fc780a9f077b463c13eed0e607ac7c7af6d8373ed5d9c7879060738274f51` |
| `hydra_sdlc/native.py` | `9d87320f245ba6d5b747e39a25bc0aa8c4b862f4da333be7161bdcf9b7c5f670` |
| `tests/test_project.py` | `6cc7121562367af4ce55f40bad2276a618a9af8b4e447a28cb85ed49949e8a3b` |
| `tests/test_policy_completion.py` | `a5d2778772c2b47301b5e4b18aa7eaec6b14ee0d01fd48a80e853cf8fb544f4a` |
| `tests/test_work_source_compatibility.py` | `d0453e95b3b373bdc82d1767213653500bc79b6d9dd9cba398ba807629a81957` |
| `tests/test_operation_integration.py` | `82d0574191e45ed8f44d2943fbb0d2c8866f730cd10edcbeefe6fb2ad77b1e6c` |

## 명시적 한계

P03는 v2 reader와 legacy 실행 보호 경계다. WorkBinding·native 관계·Projects adapter,
native 질문 API·원격 사용자 인증·MCP command 노출·새 worker는 구현하지 않았다.
P01의 미반영 MCP source나 native-context module을 import하지 않는다. 기존 executor는
유효 legacy source에서만 사용하며 현재 v2+github_native는 실행 unsupported 상태다.

remote 보호 정책과 local admission은 같은 원자적 저장소가 아니다. 효과 직전 재관측을
수행하되 마지막 remote 관측과 실제 효과 사이의 외부 정책 변경을 원자적으로 막는다는
주장은 하지 않는다. 실행 중 끝나지 않은 worker를 source 변경만으로 종료 확인하지 않고,
미확인 intent·owner를 삭제하거나 migration/downgrade하지 않는다.

fixture 실행은 실제 프로젝트의 v2 전환·설치·원격 Codex 종단 동작·production 운영 증거가 아니다.
원격 CI·최종 review·protected merge와 post-merge 확인도 아직 이 문서의 PASS가 아니다.

## 독립 검토 수정 — 실제 command와 thread/turn grant 경계

앞선 214개 PASS와 세 source hash는 초기 후보의 증거이며 아래 수정 판본으로 소급하지 않는다.
독립 code/security 검토에서 네 가지 부족한 경계를 확인했다. 같은 P03-R03 범위 안에서
`workspace.py`, `execution_boundary.py`, `codex.py`와 해당 TC로 효과 직전 검사를 연결했다.
두 optional callback은 신뢰된 parent에서만 사용하며, worker protocol이나 Issue schema를 바꾸지 않는다.

| 검토 수정 | RED 및 GREEN의 실제 oracle |
| --- | --- |
| native 최종 조회 | ticket+intent 뒤 Issue read가 RuntimeError/OSError/ValueError이면 exact recovery 응답을 잃음. 오류를 주입한 RED 후 waiting/고정 reason/동일 tuple을 반환하며 그 tuple로 exact stop 성공 |
| CLI 마지막 read | intent의 마지막 Issue read 중 source를 바꾸면 기존 후보는 spec_review를 실행하여 호출 0회 assertion FAIL. executor 호출 바로 앞의 policy 검사 후 capabilities 외 모델 호출 0회, pinned intent 보존 |
| 검증 command 경계 | signature forwarding만 연결하고 callback을 적용하지 않은 baseline에서 실제 command 1이 수정한 뒤 command 2까지 실행되어 FAIL. parent preflight를 실제 spawn/Linux launch grant에 적용한 뒤 command 2 차단 |
| SDK grant 경계 | 같은 callback 미적용 baseline의 실제 worker가 thread identity 뒤에도 turn/start grant를 받아 FAIL. parent는 policy 거절을 latch하고 deny ACK; 정확한 thread만 관측되고 turn grant 없음, cleanup 확인된 interrupted 유지 |
| 통합 보존 | 실제 Git checkout에서 command 1의 수정이 HEAD에 checkpoint되고 clean 상태가 되며 command 2·review·publish 없음. 실제 worker의 known-clean policy hold는 Runner에서 policy_changed와 pinned checkpoint로 이어짐 |
| 불확실·권한·노출 | cleanup 미확인이 known policy denial보다 우선하여 transport_unknown 유지. thread/resume의 조회 오류는 원문 없이 bounded reason. callback은 별도 exclusive admission lock을 얻을 수 있고 cleanup/poll에서 호출되지 않음 |
| wrapper 경합 | 순수 storage argv 구성 중 policy가 바뀌면 실제 command spawn 전 callback이 거절. 원본 command 실행 0회; callback의 admission lock 비점유 확인 |

초기 두 수정의 2개 TC와 실제 command/worker의 2개 TC가 각각 GREEN이다. 통합 actual Git/worker,
cleanup unknown, resume 실패, codex callback 전달 5개 TC도 PASS(5.160초)했다.
실제 SDK 서버나 원격 GitHub를 연결한 결과가 아니라 로컬 Git·프로세스·fake provider fixture다.

아래 15개 selector의 최종 여섯 source 판본에서는 **418개 수집, 410개 PASS, 7개 skip,
기존 fake verifier signature 오류 1개**를 관측했다(113.526초). named `stopped` fixture에
optional `before_command` 인자를 추가하고 assertion을 유지한 뒤 `test_operation_integration.py`
전체 **31개 PASS, skip 0**를 확인했다(2.343초). 이 수정은 test-only이며 여섯 source hash는 불변이다.
7개 skip은 이 환경의 optional pinned Codex SDK shape 검사 및 non-UTF-8 파일명 지원 조건에
해당하며 설치된 SDK/타 filesystem에서의 성공으로 간주하지 않는다. 최종 격리 전체 suite는
이 인접 검증과 별도로 수행한다.

```sh
python -c 'import unittest; patterns=("test_project.py","test_policy_completion.py","test_work_source_compatibility.py","test_runner.py","test_native.py","test_native_wait_identity.py","test_operation_integration.py","test_dispatch_reconciliation.py","test_workspace.py","test_execution_boundary.py","test_operation_boundary.py","test_codex.py","test_spec_reacceptance.py","test_verification_output_budget.py","test_progress_hints.py"); suite=unittest.TestSuite(unittest.defaultTestLoader.discover("tests",pattern=p) for p in patterns); result=unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())'
python -m unittest discover -s tests -p test_operation_integration.py -v
```

최종 source 판본의 별도 code/security 정적 재검토에서 원 지적 해결 및 추가 material finding 없음이
확인되었다. `git diff --check` PASS. 이 검토가 전체 suite·원격 CI·merge·설치의 대체 증거는 아니다.

| 검토 수정 후 파일 | SHA-256 |
| --- | --- |
| `hydra_sdlc/project.py` | `e23f7cd236312498dba2228ed1c12478fbf802ad962574ba35042c89f74dda26` |
| `hydra_sdlc/runner.py` | `564bee9d84d7f554aebc0ecfbbf8b7017ae8a3642766e68326f4df70dc3e7c62` |
| `hydra_sdlc/native.py` | `e5226a6472b4c69ebc07de46b91b93f1198626e7952fe09058a360997464e7a3` |
| `hydra_sdlc/workspace.py` | `418477e6832a64312b1f4ea63e0b30cd75e6c3cf2cfa6ccac018dd1ab6dbaad7` |
| `hydra_sdlc/execution_boundary.py` | `fb36d7d6395836107f0e1ebcf27b3cc7eb8255a51602ef3b0df2fdbddc6c7e16` |
| `hydra_sdlc/codex.py` | `1bc47324e17f9146007394cf50c1e14f4b2a96a6a8e3aa4e73d8480ed5fbf7b6` |
| `tests/test_project.py` | `6cc7121562367af4ce55f40bad2276a618a9af8b4e447a28cb85ed49949e8a3b` |
| `tests/test_policy_completion.py` | `a5d2778772c2b47301b5e4b18aa7eaec6b14ee0d01fd48a80e853cf8fb544f4a` |
| `tests/test_work_source_compatibility.py` | `358c1eb903a4b1e7faa3da70ff414dd5c914febb2a3aa4812457fc021ee199f7` |
| `tests/test_operation_integration.py` | `1c5ab5281689167d403515af61ab44bfbef616f10a99c4973c4e3b2b179ed46a` |
| `tests/test_execution_boundary.py` | `3290bbd4eebe490ffbb0923eae439eff6dd370e01da91cccdde56c4262114002` |
| `tests/test_workspace.py` | `84ddbeef284cecab4c992a1a73a3db68fb949d962b5356a41f8b795eeb84c786` |
| `tests/test_runner.py` | `b99c68067777890df1df3395fcff4cd26b814cb98a090c92f8a538807da2c280` |
| `tests/test_spec_reacceptance.py` | `2bb42e6eccd4d2d84be730f57957146128dd3ea7020f257bc4670d08a68f22f5` |
| `tests/test_verification_output_budget.py` | `848aee7e1fbc5ce39c9b7ab9d2bd2887647969ca6e51a1d8b4ce2c771a0fb466` |
| `tests/test_progress_hints.py` | `5d08b91663d3540c391b66f504c160a82d135dcfde8f68627160fcb58112e441` |

기존 fake verifier의 인자 추가는 optional callback 계약에 맞추기 위한 것이며 판단·예상 결과·
실패 assertion을 제거하지 않았다. 실제 command/SDK grant에 대한 검증은 위 실제 프로세스
oracle로 별도 수행했다. P01/MCP 노출과 P09 native 작업 원본 구현은 포함하지 않는다.

## 최종 격리 전체 회귀 — 2026-10-19

P02 commit `29db133018dc69f60e97808d2652db8280ab380c`의 전체 Git archive에 위 P03의
명시한 18개 파일만 적용한 후보를 검사했다. 별도로 남아 있던 P01/MCP와 P14 CI 후보는
포함하지 않았다. Python 3.12.7과 고정 MCP dependencies에서
`python -m unittest discover -s tests`를 실행한 결과 **962개 수집, 937개 PASS,
25개 skip, failure/error 0개**, 실행 시간 266.701초, exit code 0이다.

검사한 187개 파일은 실행 전후 SHA-256이 모두 같았다. 여섯 source와 열 개 test의 bytes는
위 독립 검토 판본과 일치한다. 실행 뒤 이 검증 결과 문단만 추가했다. 앞선 인접 selector의
fixture 오류 및 수정 기록은 그대로 보존한다. 이번 전체 실행에는 수정된 fixture도 포함된다.

이 결과는 최종 로컬 source 후보의 D 증거다. 원격 CI, 보호된 사람의 승인, merge/main 확인,
실제 v2 전환·설치·원격 Codex 흐름의 O 증거는 아직 없으며 별도로 이어간다.

## 현재 main/P02 후보와 retirement 통합 검증 — 2026-10-20

이번 단계는 문서화된 main과 P02 후보 tree
`884c5e971283bcd6bd7daaddc16496130c33af7e` 위에서 P03을 검증했다.
같은 base tree는 PR #11 head `4e2f55e9c6afdd5acd8a290c5d86026ad3c54a45`와 일치한다.
이 기록은 P02/P03의 protected merge, hosted CI, 설치 또는 실제 운영 성공을 선언하지 않는다.

P03의 current policy 검사를 그대로 PR #8의 세 retirement barrier에 추가하면 보호된
policy의 remote read가 admission lock 안에서 실행됐다. 독립 owner의 실제 OS exclusive-lock
probe를 각 경로에 연결해 세 assertion failure를 재현했다. 수정은 고정된 동기 retirement의
policy preflight를 잠금 밖에서 수행한다. 원 배정의 native_head/attempt/step/contract와 현재
coordinator owner를 확인하고, record → exact read-back → ticket release → consumed 순서를
기존 guard 안에 유지한다. 후속 효과는 policy를 새로 확인한다. 일반 bypass flag나 callback
권한을 만들지 않았으며 원격 정책과 local admission의 원자적 transaction을 주장하지 않는다.

| 검증 | 결과 |
| --- | --- |
| 세 policy-lock oracle | RED: 3 assertion failures / 0.091s → GREEN: 3 passed / 0.115s |
| P03·parser·policy·native·admission·workspace 관련 suite | 299 collected / 297 passed / 2 explicit skips / 108.340s |
| 최종 격리 Python 회귀 | 985 collected / 960 passed / 25 explicit skips / 263.496s / failures 0 / errors 0 |
| skip set | 직전 main/P02 후보의 25건과 동일. 미실행을 PASS로 바꾸지 않음 |
| 독립 code·security 통합 리뷰 | 고정된 18-file overlay에 중대한 미해결 finding 없음 |

실제 concurrent Pause에 대한 기존 세 barrier 사례와 ACK/read-back 실패 복구를 유지했다.
새 사례는 policy read의 잠금 분리, preflight 중 Pause, retirement 중 policy 변경 후 후속 효과
보류, release 실패 복구, 완료 필드로 assignment identity를 바꾸는 시도의 거절을 검사한다.
CLI와 native는 순수한 review 완료 계산 및 record 정규화만 공유한다. 검증 중 후보의
source/test/spec, 기존 product checkout, HEAD와 무관한 변경은 불변이었다.

Python 3.12.7 / mcp 2.3.0 / mcp-types 2.3.0의 source/fixture 결과다.
실제 native v2 migration, 원격 질문·제어·재개와 installed runtime은 이 검증의 범위가 아니다.

| 고정한 구현 | SHA256 |
| --- | --- |
| `hydra_sdlc/native.py` | `e7afd50472432dc9d25940b8357257e514ae9a82fc27e0317e18093cf746076e` |
| `hydra_sdlc/runner.py` | `08fa83cd801a2b7108b70fec6709e08549aca3e502c8f4f33c126872b3372257` |
| `tests/test_operation_integration.py` | `803cf6c2ff2e7794a0dd732ac35a96b3812444c4570bab3332736c0ec1d36f6e` |
| P03 `spec.md` | `cfee0e7ed6342b154ac80423e657d0babd0c42fd6ffdc9714a50a3c119076f87` |

## 수정된 P02 main과의 최종 조합 검증 — 2026-10-20

PR #11의 실제 main `973892add0d68c658f7137046899eab17d2df5bc`는 tree
`b52cd9b7fec1948b9eafcfaad147eab3abfa23bb`이며, 최종 reviewed head와 같은 tree다.
해당 main의 CI 4개와 전체 workflow가 성공한 뒤 이 조합을 검증했다. 위 985개 결과는
이전 P02 후보 위의 역사적 증거이며 이번 결과로 소급하지 않는다.

검토된 P03 18개 파일을 byte 변경 없이 수정 P02 tree 위에 적용했다. P02의 수정된 여섯
파일과 CI는 overlay와 겹치지 않으며, 18개 대상의 원래 base bytes도 기존 검토 기준과 같다.
P03은 legacy dict API와 기존 admission guard를 사용한다. 새 observed API를 우회하거나
원격 정책 조회를 retirement lock 안으로 다시 이동하지 않았다. 정적 호환성 독립 검토도 clear다.

| 실제 최종 조합 검증 | 결과 |
| --- | --- |
| P02의 8개 suite와 P03 suite의 중복을 제거한 13개 모듈 | **348 collected, 346 PASS, 2 explicit skip**, failure/error 0, 111.141초 |
| 같은 snapshot 전체 suite 1회 | **997 collected, 972 PASS, 25 explicit skip**, failure/error 0, 269.904초 |
| skip 대조 | 전체 25개는 수정된 P02 최종 suite의 항목 집합과 정확히 동일. 필수 interaction 23개는 실제 수집되고 skip되지 않음 |
| 실행 환경 | Python 3.12.7, mcp 2.3.0, mcp-types 2.3.0 |
| 보존 | 격리 snapshot 189개 파일, overlay, 제품 파일·HEAD·기존 미커밋 상태가 실행 전후 동일 |

필수 interaction은 관측 시각·권한 철회·replace 전후 오류와 source/Pause 변경, 원 배정
identity, retirement 순서, read-back/ACK 유실 복구를 함께 포함한다. 독립 검토된 P03
source/test/spec의 bytes는 위에 기록한 판본 그대로다. 이 검증 뒤 source/test 변경은 없으며
이 문단만 실제 관측 결과를 추가했다. 최종 head의 hosted CI·코드/보안 리뷰, 보호 병합과
실제 merge-SHA main 검증은 따로 확인한다. 실제 v2 정책 전환, 설치·원격 Codex 운용,
원격 질문·Pause·재시작·Resume 전체 흐름은 이 source 검증으로 통과 처리하지 않는다.
