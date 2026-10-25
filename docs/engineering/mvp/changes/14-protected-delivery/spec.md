# P14 — 보호 전달과 병합 후 책임

Revision: 5 · Updated: 2026-10-25. The source-context profile below is the current
increment; implementation and operational evidence remain in `verification.md`.

이 명세는 검증된 후보를 보호된 경로로 전달하고, 병합 뒤 성공·실패·미확인을 구분하여 다음
책임까지 연결한다. 대응 범위는 [계획의 W6a](../../plan.md), 상위 요구 R10/R11/R12/R13이다.
현재 구현 계약은 [GitHub workflow](../../../github-workflow/spec.md)이며 이 후보가 자동 대체하지 않는다.
동작 정본은 [EX §8](../../contracts/execution.md#8-검증리뷰전달의-연결), 검증 정본은
[VF](../../verification.md)다. 플랫폼의 권한·source·auto-close 의미는 [GitHub 계약](../../contracts/github-integration.md)을 따른다.
[공통 인계 기준](../README.md)을 따르며 이 파일은 해당 변경 범위를 소유한다.

## 목적과 현재 차이

사람이 같은 전달을 반복 확인하지 않아도 명시한 효과 범위에서 진행하고 남은 책임을 확인해야 한다.
2026-10-19 working source에는 exact check/review·direct squash·post-merge 네 상태가 있지만,
typed publish/deliver 분리와 queue route·repair 완료 보강은 남아 있다. 소스 읽기는 실행 증거가 아니다.
새 배포기·queue/rerun API·tracker·로컬 delivery journal은 추가하지 않는다.

## 요구사항

| ID | 요구와 완료 조건 |
| --- | --- |
| P14-R1 | 최종 head/spec/policy/intake·binding·base·scope·소유와 실제 필수 CI/code/security review를 재검증한 후보만 전달한다. 로컬 review는 remote review의 대체가 아니다. |
| P14-R2 | 실제 보호 정책에서 direct/required queue/unknown을 구분한다. direct 허용일 때만 exact-head squash; queue 필수·관측 불충분이면 direct 요청 0회와 필요한 원본 조작을 표시한다. |
| P14-R3 | 효과마다 기존 intent→요청→원본 read-back→확인 순서를 유지한다. 응답 유실·재시작에서도 같은 결과를 재사용하고 미확정 효과를 새 PR/head로 우회하지 않는다. |
| P14-R4 | 실제 merge SHA의 latest trusted required push checks를 pending/failed/unknown/success로 구별한다. failed는 진단 대상이며 merge·PR head green·과거 run 성공만으로 close하지 않는다. |
| P14-R5 | 범위 내 코드 결함은 EX의 한 repair outcome과 보호 전달로 해결한다. infra 재실행은 지원·위임이 확인된 경로만 사용하며 현재 미지원 자동 rerun을 성공으로 광고하지 않는다. |
| P14-R6 | repair의 유효한 대체 증거로 요구 충족을 계산하되 원래 실패를 보존한다. 최종 PR·commit·squash 문구의 조기 auto-close를 차단하고 필요한 관측 전 완료·무단 배포·rollback·자원 삭제는 하지 않는다. |
| P14-R7 | versioned workflow_step의 publish_candidate와 deliver를 exact candidate/PR pin에 묶인 별도 handler로 제공한다. 같은 effect engine의 닫힌 상한을 집행하고 다른 operation으로 자동 승격하지 않는다. |

## 입력·출력·정본과 의존성

| 경계 | 입력 또는 출력 / 소유 |
| --- | --- |
| 입력 | [CP typed workflow profile](../../contracts/control-plane.md)의 publish_candidate/deliver 입력·pin·receipt. target/현재 attempt·candidate/PR/base·remote expectation을 대조하고 accepted spec/policy/intake/binding과 admission은 원본에서 재검증한다. schema를 여기 복제하지 않는다. |
| GitHub SSOT | owned branch/PR와 immutable commits, rules/ruleset sources, run ID/run attempt/workflow/event/head/job/producer, provider review·native approvals·threads, Issue와 repair 관계. Hydra는 조회 결과를 파생 표시한다. |
| 출력 | 기존 action/reason과 원본 링크, pending intent 또는 확인된 squash receipt, post-merge 상태, 남은 요구/repair/관측/정리 책임. native ID·private review 원문·credential은 공개 출력에 넣지 않는다. |
| 의존 | 전달 경로는 P13의 좁은 검증 실행 단계가 제공하는 실제 candidate 검증·독립 review, P02의 공통 typed handler·admission/effect ceiling와 P05 공통 MCP 배선, P10/WR의 create_key·위임·repair 등록과 P11/W2c 요구 충족 판정을 소비한다. P13 exporter의 병합이나 결과 JSON 존재는 실제 candidate 검증 능력을 대신하지 않는다. 아래 CI 보존 단계는 이 실행 의존성 없이 먼저 개발한다. |
| 변경 소유 | `control.py` typed handler/정규화·`mcp.py` 기존 hydra_command_v1 배선·`native.py` exact 대상 entry·`runner.py` effect filter/전이, `project.py` gate/완료 predicate, `github.py` read-back, 관련 control/native/MCP/delivery tests. 공유 파일은 선행 owner와 순차 통합한다. |
| 범위 제외 | CP schema 정본·화면, native transport, resource 삭제·타 프로젝트 정책. 기존 kernel discovery로 TC를 수집하며 producer/consumer 변경은 같은 후보에서 검증한다. |

순수 guard는 독립 구현 가능하나 실제 효과에는 등록·위임·보호 규칙과 source 자격이 선행한다.

## 구현 단계와 PR 인계

같은 명세를 다음 두 결과로 전달하며 각 PR에 정확한 판본·범위·검증·남은 책임을 연결한다.
main 실행 보존을 먼저 확보하여 이후 PR의 전달 증거를 잃지 않게 한다. 새 명세나 실행 대장은 만들지 않는다.

| 단계 / PR 결과 | 변경·검증 범위 | 선행 조건·완료와 후속 소비자 |
| --- | --- | --- |
| main CI 실행 보존 | 아래 CI 보존 절의 workflow concurrency와 관련 TC. R4의 실행 보존 부분, T12/13의 event·SHA 격리 oracle 및 실제 CI 확인 | 기존 workflow·수용된 R4 계약으로 시작. P13/P14 명령의 완성을 기다리지 않음. final-head CI와 해당 실제 실행 관측을 기록하고, 미실행 연속 push O05는 남은 책임으로 보존. 각 merge SHA의 증거를 전달 단계가 소비 |
| 보호 전달·병합 후 책임 | typed publish/deliver, 정확한 gate/read-back, post-merge 네 상태·repair·완료. R1–R7 및 T01–11, T12/13 회귀와 적용 L/O | 위 보존 계약과 실제 candidate 검증·독립 review 등 해당 능력을 소비. P14 기능 완료는 실제 전달·main·복구의 O05까지 필요하며 early CI PR 병합으로 완료하지 않음 |

두 단계 모두 각자의 TC·독립 리뷰·최종 CI·main 확인을 포함한다. 첫 단계의 workflow와 P13의
CI export 변경은 같은 파일의 현행 판본을 순차 통합하고 두 계약의 회귀를 유지한다. 하나의 PR
병합을 기다리는 것과 전체 native 기능의 운영 완료를 기다리는 것을 구분한다.
Hydra 자체 개발의 두 PR 전달은 현재 Codex·GitHub 경로를 사용한다. 이 명세의 미완성
publish/deliver 구현을 그 개발 절차의 필수 도구로 요구하지 않는다.

## 두 명령의 구현 인계

기존 `hydra_command_v1`의 공통 parser/authority handler에 CP의 두 typed profile을 추가하고
같은 NativeController ownership entry→Runner effect engine으로 보낸다. 별도 실행기·신규 MCP tool을
만들지 않는다. 기존 다섯 MCP의 broad continuation 의미는 유지하며 좁은 명령의 fallback으로 쓰지 않는다.
각 handler는 같은 논리적 효과의 기존 intent/결과를 먼저 대사하고 새 효과 전에 현재 candidate·owned PR·source pins를 대조한다.
미해결 assignment·dirty/stale 후보·검증 근거 소실은 필요한 다음 행동과 hold이며 새 검증/배정/commit을 시작하지 않는다.

| 명령 | 정상 효과와 끝 / 금지 효과 |
| --- | --- |
| publish_candidate | 검증·독립 후보 review가 끝난 정확한 committed head를 expected remote ref로 push→owned PR 확보/read-back→필요한 exact-head remote review 요청까지 진행. PR/ref의 publication receipt와 review 요청의 확인/대기를 구분해 반환한다. commit·통합 수정·새 후보 검증·assignment·merge·close·retire는 0회. |
| deliver | 이미 공개된 exact owned PR/head/base와 현재 위임의 gate를 확인해 direct squash→merge read-back→post-merge→충족된 close까지 진행. gate pending/failure/unknown은 필요한 다음 행동과 hold. push·PR 생성·새 검증/assignment·repair 등록·retire는 0회. |

효과 직전마다 server가 선택한 고정 ceiling을 적용한다. 외부 대기는 무한 호출로 이어가지 않고
현재 원본을 반환한다. receipt는 CP의 실제 관측 stage/refs만 사용하며 request_id를 durable idempotency로
쓰지 않는다. 재요청은 원래 intent를 먼저 대사해 이미 반영된 같은 효과를 재사용한다. 변경된 pin으로
몰래 refresh하지 않으며 pending 결과 unknown은 보존한다. failed 이후 아래 repair 흐름은 별도로 위임된
continue/등록 경로의 책임이고 이 두 명령에서 자동 호출하지 않는다. 두 capability는 각각 검증 후 광고한다.

## 구현 순서와 효과 경계

1. 기존 TC를 요구에 매핑하고 실패 fixture·정상 control을 먼저 고정한다. 기대값은 독립 작성하고 새 차이만 RED로 확인한다.
2. 보호 관측을 `direct_allowed / queue_required / unknown`으로 분류하는 순수 경계를 추가한다.
   적용 branch rules와 active ruleset source·bypass·필수 check/review를 함께 확인한다. 목록 누락을
   direct로 해석하지 않는다. queue_required는 adapter 미지원으로 반환하고 merge PUT을 호출하지 않는다.
3. direct 후보의 최종 read를 하나의 guarded continuation에 연결한다. required check는 이름뿐 아니라
   producer/workflow/event/target revision/job와 latest run을 확인한다. native 승인·CODEOWNER 조건,
   remote code/security 완료·미해결 thread·현재 head를 확인하고 실패/수정 뒤 영향 증거를 다시 얻는다.
   생성 요청뿐 아니라 기존 PR의 최신 title/body, 실제 candidate commit message와 최종 squash
   title/body도 조기 close 검사 대상이다. `Refs`/`Related issue`만으로 연결하고 closing-intent 문구는
   거절한다. `Fixes owner/repo#N`, `Closes: #N`, URL·대소문자·복수 참조를 포함한 보수적인 parser를
   사용한다. 변경된 PR 또는 commit을 자동 rewrite하지 않고 수정 후 final-head 증거를 다시 검증한다.
   `ensure_pr`의 현재 regex와 기존 PR 조기 return만으로 이 보장을 충족했다고 판정하지 않는다.
4. 기존 progress에 `pending_action=merge`, expected head/base를 고정한 뒤 ownership과 admission을
   다시 검사한다. `GitHub.merge`의 exact `sha` squash 요청과 `Hydra-Squash-v1` correlation을 재사용한다.
   최종 PR/head/merge SHA, immutable parent/tree 및 method receipt를 대사한 뒤 observing으로 전진한다.
5. `observe_commit(merge_sha)`와 `post_merge_check_state`를 재사용해 네 상태를 유지한다. close intent
   이후에도 merge 사실·현재 위임/의존/정책과 latest push checks를 다시 읽는다. 성공이면 close/read-back,
   pending은 model-free 관측, unknown은 source 복구, failed는 원래 merge/run/요구를 보존한 진단으로 간다.
6. failed의 코드 결함은 WR guard로 `outcome=repair-<원래 merge SHA>`의 기존 작업을 조회·재사용하거나
   한 번 등록한다. 원래 실패 Issue를 post_merge_verified 선행조건으로 두지 않는다. repair는 자체 accepted
   spec·회귀 TC·독립 review·protected PR·post-merge를 갖고 원래 작업에 결과 참조만 연결한다.
7. 완료 predicate에 EX-D30의 명시적 대체 산출물 경로를 추가한다. 같은 원래 전달 의무·요구에 연결된
   유일한 repair의 증거가 충분할 때만 후속 책임 해소를 파생한다. 원래 SHA 자체 성공을 요구하는 조건은
   남긴다. 다음 미충족 요구 또는 별도 cleanup 책임으로 진행하며 원래 실패 결과를 success로 덮지 않는다.

최종 source read와 원격 writer는 atomic하지 않다. local coordinator 직렬화와 admission barrier를
사용하되 remote CAS를 발명하지 않는다. Pause 적용 뒤 신규 dispatch는 0회이며, 그 전에 전송된
요청의 늦은 commit은 원래 intent로 read-back한다. unknown intent가 있으면 후속 효과는 보류한다.

| 효과·사건 | 대사·허용된 후속 행동 |
| --- | --- |
| publish/PR/review 요청 유실 | exact branch/head, PR ownership marker, provider/kind/head 원본 조회. matching 결과 재사용; complete 0개만으로 미적용 확정 금지. |
| merge 유실·base/head/review 변경 | 먼저 원래 intent의 PR/commit/correlation을 조회한다. observed squash는 재병합 0회; 결과 unknown은 intent 보존. 새 findings로 미확정 merge를 지우지 않는다. |
| close 유실·재시작 | 같은 Issue 상태와 현재 완료 근거 재조회. 이미 닫혀도 main 실패/unknown이면 완료 증거를 만들지 않는다. completion-only 정책 예외는 실제 owned merge의 대사에만 적용한다. |
| 재시도 | EX의 최초+두 번 transient budget 재사용. 미적용 확정과 current gate가 모두 유효할 때만 재요청; 횟수 unknown은 0으로 초기화하지 않는다. |
| infra 실패·rerun | 현재 자동 adapter 미지원이므로 exact run 원본 링크와 이유를 반환한다. 위임된 원본 경로의 newer run을 재관측하면 정상 전진 가능하다. 미래 adapter는 exact run/attempt intent·read-back·budget 검증 후 별도 수용하며 running 중 중복 요청을 금지한다. |
| repair 조회/생성 유실 | WR create_key·actor·coverage로 동일 repair 재발견; partial은 unknown, 복수 후보는 conflict. 새 key·복제 Issue·권한 자동 확대 금지. |
| queue 필수 | 원본 queue 조작 필요와 adapter 미지원 표시. enqueue/entry/integration revision checks/actual merge를 구분할 qualified adapter 전에는 BLOCKED; direct 우회 금지. |

## 검증 사례와 실행 방법

아래는 예정 TC이며 모든 결과는 NOT RUN이다. fake clock/provider와 격리된 Git fixture에서 원본
snapshot·전후 Git 상태·요청 횟수를 독립 oracle로 사용한다. 음성 사례는 해당 guard 외 조건을 유효하게 둔다.

| ID / 연결 | 입력·자극 → 관측할 종점 |
| --- | --- |
| P14-T01 · R1–4 · EX-D16/19/20 | valid direct·최종 review/CI → squash 1회, exact receipt, push success 뒤 close 1회. restart 반복에도 정상 완료·추가 merge/close 0회. |
| P14-T02 · R1/2 · EX-D19, VF-D09 | stale/forged/duplicate check·review, missing source, required queue를 각각 주입 → merge 0회. 유효 direct control은 실제 전진. |
| P14-T03 · R3 · EX-D13/16/17 | merge·close intent 전후 응답 유실/late result/restart/Pause → matching 재사용, unknown 보존, barrier 뒤 새 dispatch 0회, fourth request 0회. |
| P14-T04 · R4 · EX-D20/21 | merge 뒤 pending/failed/unknown/success·newer rerun, main 진전·병합된 policy 변경 → 네 상태와 역사적 receipt 보존; close 직전 실패면 close 0회. |
| P14-T05 · R5 · EX-D28 | infra 실패·미지원/미위임 rerun·이미 running → Hydra rerun 0회와 exact 원본 안내; 외부에서 확인된 newer trusted success이면 완료 경로로 전진. |
| P14-T06 · R5/6 · EX-D29 | code defect·중복 wake·create 유실/restart → 같은 repair 하나. partial/conflict/미위임은 보류하며 original PR 재병합/rollback 0회. |
| P14-T07 · R6 · EX-D30, VF-D09 | 유일 repair 성공/불충분/다른 요구/원 SHA 성공 필수 → 충분한 경우만 후속 책임 해소·다음 요구 진행. original failed 근거는 모두 유지. |
| P14-T08 · R1–6 · EX-D15/24, VF-D24 | verify_only ceiling·위조 권한·private sentinel → 금지 전달/공개 유출 0회; 좁은 명령을 legacy broad continuation으로 대체하지 않음. |
| P14-T09 · R6 · EX-D16/20, VF-D09 | 새/기존 PR body·title, commit/squash message에 closing-intent 형태를 각각 주입 → 영향받는 publish/merge 0회. `Refs #N`, `Related issue: #N` 양성 control은 전달 후 main 성공 뒤에만 close. 외부 조기 close도 완료 증거로 승격하지 않음. |
| P14-T10 · R7 · EX-D15/16, CP-D08/17 | 실제 typed publish handler에 valid exact candidate → push/owned PR/필요 remote review request read-back·published 반환. dirty/stale/missing candidate review와 유실/restart도 주입; commit/배정/merge/close/retire 0회, matching 기존 효과만 재사용. |
| P14-T11 · R7 · EX-D15/16/19/20, CP-D08/17 | 같은 dispatcher의 valid pinned PR deliver → merge·post-merge·close 정상 진전. foreign/wrong PR/head/base·지원 불명·gate 실패는 hold/거절; push/새 PR/배정/repair/retire 0회. 미지원 runtime의 legacy fallback 0회. |

현재 존재하는 좁은 검사: `python3 -m unittest discover -s tests -p 'test_delivery*.py' -v`,
`python3 -m unittest discover -s tests -p 'test_post_merge*.py' -v`, 같은 형식의
`test_squash_completion.py`, `test_final_controls.py`, `test_project.py`, `test_github.py`, `test_mcp.py`, `test_native.py`.
예정 selector: `python3 -m unittest discover -s tests -p 'test_mvp_delivery_contract.py' -v`.
typed consumer 사례는 예정 `test_control_commands.py`와 실제 MCP→controller→runner로 연결한다. 0개 수집은 PASS가 아니다. 최종 Python 회귀는
`python3 -m unittest discover -s tests -v`; 호스트 지정 실행 wrapper와 [VF §3](../../verification.md#3-현재-존재하는-검사와-앞으로-만들-검사)의 CI/hygiene를 적용한다.

## 독립 검토·수용과 복구

### CI 실행 보존의 구현과 검증

현재 ref별 cancel-in-progress 설정은 연속 main push에서 앞선 merge SHA 증거를 취소할 수
있어 R4와 충돌한다. 이 명세의 첫 단계가 `.github/workflows/ci.yml`의 해당 변경을 소유한다. 같은 PR은
workflow+PR number로 묶고, main push는 workflow+run_id별 독립 그룹으로 보존한다. 단순히
cancel=false로 바꾸어 pending 교체를 남기지 않는다. 다른 workflow와도 group이 충돌하지 않는다.
배포 직렬화·ruleset·required checks를 완화하지 않고 현재 v1의 direct-only 전달을 유지한다.

- P14-T12 / R4: 같은 PR의 옛 후보 취소와 최신 head 검증 유지; 서로 다른 세 main merge SHA의
  실행은 각각 보존. YAML 표현 검사와 runtime event fixture를 구분한다.
- P14-T13 / R4: SHA A의 canceled/failed/unknown과 SHA B success를 동시에 관측해 A close 0회.
  A의 정확한 newer trusted run 성공 뒤에만 A의 검증 의무가 해소된다.
- O05: 허용된 검증 범위의 연속 push에서 각 실제 SHA/run/workflow/producer 결과를 관측한다.
  fixture나 expression 정적 검사만으로 GitHub의 실제 실행 보존을 PASS로 표시하지 않는다.

현재는 설계 개정이며 workflow 수정·TC·실제 연속 push 시험은 NOT RUN이다.

D는 위 전이·효과·회귀를, L은 EX-L01/VF L09/L19의 실패 진단·후속 요구 선택을 별도 reviewer로 검증한다.
고정 replay는 L PASS가 아니다. O는 VF O05/EX-O04의 실제 direct 전달·유실 read-back·main·repair다.
queue/rerun 자동 실행은 이 PR의 N/A(미구현 범위)다. 필요한 실제 목표의 BLOCKED와 전체 v1 의무는 남는다.

구현 전 정확한 spec revision을 독립 검토한다. 최종 diff의 요구 충실성·품질/보안 검토와 수정 뒤
final head의 필수 remote CI·code/security review·보호 승인을 확인한다. UI 화면 시험은 무변경 시 N/A,
visually meaningful 변경 시 원래 screen gate를 적용한다.
완료는 P14 요구별 D/L/O와 실제 전달·main 증거가 연결되고 미해결 효과/관측 책임이 정확히 남은 상태다.
후속 cleanup은 별도 인계한다. 실패는 같은 Issue/intent에서 대사하고 구현·oracle을 수정하며 CI/승인/기준·실패 기록을 보존한다.

## Post-merge source-context profile

This profile implements the authenticated investigation handoff for P14-R4/R5.
It adds bounded source context to existing `hydra_status` rows so Codex can locate
the exact required CI failure. Diagnosis, the single repair outcome, repaired
requirement fulfillment and actual native acceptance remain separate obligations.
It grants no repair, rerun, dispatch, merge, close or cleanup authority.

### Origin and observation lifecycle

Only already-discovered registered work with authenticated progress in
`observing`, `closing` or `completed`, or a pending merge whose exact squash can
be proven, is eligible. Preserve pending intents. Cross-host read-only work is
eligible without implying current-host ownership. Existing retained-workspace
closed-work discovery remains bounded; this profile adds no global discovery.

One fresh GitHub read client belongs to each synchronous status enrichment pass.
Authenticate the actual account ID/login and credential fingerprint, canonical
repository name/ID, progress comment and parsed value, and original/current
protected project-policy semantics. Request fields or normalized objects are
not provenance. Use only GET reads. Read the owned PR and immutable commits,
reuse `gate_squash_result` and the authenticated squash checkpoint, and require
the original head/base/tree/sole-parent identity. For a pending merge, reuse
`squash_recovery_checkpoint` correlation without writing a checkpoint or clearing
the intent. Do not call the GraphQL-using `GitHub.observe()` or weaken/reuse final
delivery acceptance to claim this diagnostic origin. `read_delivery` and
`gate_completed_delivery` retain their existing behavior. A legitimate nullable
spec revision remains null.

Phase A qualifies origin and current required checks for all selected rows before
any optional history. Complete eligible-run discovery precedes current selection;
reuse the existing latest run-number/run-attempt and protected workflow, app,
event, repository, SHA, job, check and suite predicates. Foreign-only evidence or
a queued run without required job/check evidence is unknown. Unrelated foreign
noise does not erase qualified required evidence. Reobserve progress, current
policy, credential and the selected latest run/attempt before closing each
current snapshot. Reserve these reads before spending a history budget.

Phase B reads history against each snapshot's immutable merge and captured run
set, including earlier eligible runs and earlier attempts of its current run.
Order ascending by run number, run ID, then attempt number. Read at most eight
runs and eight historical attempts per run; these caps never affect current
selection. Authenticate historical failures using actual run-attempt metadata,
attempt jobs and individual check-run GETs with the same required-source
predicates. Progress wait prose never proves a past CI failure.

Each axis records its own observation time; top-level time is assembly time.
This is not an atomic provider snapshot. Changes after a current snapshot closes
are outside that snapshot; effects always require fresh source observation.
Historical through-scopes do not expand to a later observed attempt.

One pass-wide sticky binding guard spans both phases. Any observed credential,
account or same-binding disclosure change invalidates every context using that
binding, including previously finalized siblings. Remove their origin and detail
references, stop optional history, and do not reset the guard even if credentials
return. Compare each repository's disclosure basis with itself; ordinary distinct
visibility across repositories is not a change. A local progress/policy change
invalidates only its row when the shared binding remains valid. Ordinary history
denial, truncation, timeout or incomplete data cannot erase qualified current CI.

### Additive status data

An eligible row adds `post_merge_context`, through the actual GitHub reader →
`Runner.status` → `NativeController.status` → existing `hydra_status` reply. It is
not a new CP fact or command. Existing progress, waits, hints, admission and app
projection/reducer behavior remain unchanged. Pause permits these observations.

All keys below are required; reject extra keys. IDs are safe positive integers,
hashes and UUIDs canonical, and timestamps UTC. Fixed bounded codes replace raw
provider errors. A valid locator shape alone does not authenticate a source.

```text
PostMergeContext = {
  schema_version: 1, state: failed|pending|success|unknown|changed,
  reason: code|null, source: Origin|null,
  current: {state: failed|pending|success|unknown, checks: [CheckRef],
            coverage: Coverage, observed_at: UTC|null},
  history: {failed_checks: [CheckRef], through: [AttemptScope],
            coverage: Coverage, observed_at: UTC|null}, observed_at: UTC
}
Origin = {repository_id, issue_number, progress_comment_id, attempt_id,
          contract_revision, spec_revision: git_sha|null, source_digest,
          head, pr_number, merge_sha}
CheckRef = {workflow_id, run_id, run_attempt, job_id, check_run_id,
            job_name, state: failed|pending|success|unknown,
            run_url, attempt_url, job_url, check_url}
AttemptScope = {workflow_id, run_id, through_attempt}
Coverage = {state: complete|partial|unavailable, scope, returned_count,
            total_count: nonnegative_integer|null, next_cursor: null,
            reason: code|null}
```

Require `job_id == check_run_id` and the actual matching check URL, SHA, app,
suite and run identities. `job_name` comes from the protected binding. Construct
URLs from the validated canonical repository and source IDs:

- `https://github.com/OWNER/REPO/actions/runs/RUN_ID`
- `https://api.github.com/repos/OWNER/REPO/actions/runs/RUN_ID/attempts/N`
- `https://api.github.com/repos/OWNER/REPO/actions/jobs/JOB_ID`
- `https://api.github.com/repos/OWNER/REPO/check-runs/CHECK_ID`

Current coverage counts configured required-binding slots, uniquely qualified
returned slots and the authenticated declared total when known. Do not create
successful references for unknown or ambiguous slots. History coverage counts
qualified failed required-job/check observations in explicit through-scopes.
It is complete only after every applicable bounded attempt/check is fully
observed and terminal; the total then equals the failed-reference count.
Truncation, access failure, nonterminal or ambiguous evidence makes history
partial/unavailable with a null total. Source-proven empty history can be
complete with zero; unavailable history cannot. Return at most 32 CheckRefs
across both axes. Truncation marks the affected axis incomplete and preserves
already-confirmed failure references.

After stable source qualification, outer state equals current state. Reasons are
`post_merge_failed`, `post_merge_checks`, null and
`post_merge_evidence_unknown` for failed, pending, success and unknown.
Shared binding or local source change yields `changed` with
`post_merge_source_changed`; source unavailability yields `unknown` with
`post_merge_source_unavailable`. Both invalid-source shapes have null source,
unknown current state, empty references/through-scopes, unavailable coverage
and null per-axis times. History failures never downgrade qualified current CI.
No context establishes requirement acceptance, completed delivery or goal success.

### Bounds, effects and permanent verification

One pass has 45 seconds, 128 GETs and four enriched contexts. Before Phase B,
finish Phase A or return an explicit source-unavailable result for each selected
row. Context-cap and budget omissions are explicit unknown/unavailable contexts;
preserve other status data and do not imply global completeness. Keep the
existing 8 MB raw observation cap and limit each normalized context to 32 KiB.
If history cannot fit, omit it with incomplete coverage rather than consuming
current-source checks. No network I/O holds an admission/coordinator lock.

No raw logs, steps, annotations, title/body, provider diagnostic, credential,
private native ID or local path enters the context. Persist no derived provider
state. Add no tool, credential, model, scheduler, tracker or installed activation.
All tests reject non-GET, model, assignment, workspace, rerun, repair, merge,
close and cleanup effects.

- P14-T14 / R4–5: actual observing/closing/completed/pending-merge source plus
  exact squash and trusted failed push job reaches the real in-memory MCP reply;
  include null spec and cross-host sources, with zero writes/new resources.
- P14-T15 / R4: success/pending preserve identity; absent required jobs is unknown.
- P14-T16 / R4: older failed runs/attempts survive newer current pending/success;
  wait prose cannot create historical failures.
- P14-T17 / R4: history denial/partial/budget preserves current failure, Phase A
  precedes sibling history, and timestamps/through-scopes remain exact.
- P14-T18 / R4: foreign IDs/app/workflow/event/SHA, duplicate jobs/checks, partial
  current pages and unproven squash are unknown; unrelated noise is harmless.
- P14-T19 / R4: mutable progress/policy/credential/latest attempt is changed or
  unknown at its owning observation boundary.
- P14-T20 / R4: finalize sibling A, then observe shared credential rotation and
  restoration during B history: remove all A/B detail, remain changed and stop
  history. Cover shared account/disclosure and local-only source changes.
- P14-T21 / R4: unrelated phases do not enrich; retained closed discovery keeps
  its unknown limits; restart reuses actual source references.
- P14-T22 / R4–5: private extra-field/error canaries never escape; enforce time,
  request, context, raw-byte and reference caps, sibling isolation and Pause.

Freeze requirement-derived oracles before code, demonstrate meaningful purpose
RED and unchanged GREEN, then run affected source/delivery/status/MCP/project
regressions and existing app compatibility checks. Exact independent code/security
review, final-head CI, protected merge, actual-main checks and branch retirement
remain required. Fixture output never substitutes for actual-source/native O.
The missing initial progress → `bind_work` → attempt-anchor writer and original
first-dispatch provenance remain explicit, separate work; this handoff cannot
conceal that missing v1 capability.
