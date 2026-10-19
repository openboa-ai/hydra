# GitHub 기능 연결 계약

Revision: 2 · 상태: 설계 후보 · 2026-10-19 · 관련 작업: Issue #3

GitHub의 업무·코드·검증 기능을 Hydra가 어디까지 읽고 사용하는지 정의한다.
공식 문서는 아래 확인일에 읽었지만 실제 계정·대상 repository 호출은 NOT RUN이다.
데이터형·상태 schema는 [WR](work-records.md), [EX](execution.md),
[CP](control-plane.md)를 참조하며 이 문서에서 다시 정의하지 않는다.
PR 단위 구현은 [변경 목록](../changes/README.md)을 따른다. 기능 존재는 실행 권한이 아니다.

## 1. 목적과 책임

| 항목 | 계약 |
| --- | --- |
| 목적 | 기존 Issues·설계·PR·Actions·보호 규칙으로 SDLC를 운영하고 별도 tracker/CI를 만들지 않는다. |
| 책임 | GitHub는 원본 사실과 보호된 전달, Codex는 해석·구현·검토, Hydra는 identity·scope·revision·증거·응답 유실 대사를 맡는다. |
| 동작 | 보호된 정책/원본 조회 → 해당 단계의 guard → 허용된 한 효과 → 원본 read-back → 다음 의무 판정. |
| 실패·복구 | 권한·coverage·결과가 불명확하면 해당 효과만 보류하고 원래 intent/attempt를 보존한다. |
| 완료 | PR merge, 요구 충족, post-merge 검증, 운영 관측, 자원 정리를 각 원본 증거로 확인한다. |
| 범위 | 현재 connector 및 허용된 runtime gh transport를 사용한다. 새 App·credential·webhook 서버·DB·ruleset 변경을 기본 설치 조건으로 만들지 않는다. |

## 2. 기능별 정본과 최소 사용 범위

| 기능 | 쓰는 목적·identity | 읽기/효과와 경계 |
| --- | --- | --- |
| Issues·comments | 요청/목표/작업과 고정 채택 근거. repo numeric ID + Issue number, 실제 comment ID/author | WR의 자유 형식 해석·binding·draft·attempt anchor. Issues read; 위임된 생성/기록/closure만 write. 원문을 양식으로 덮지 않음 |
| Markdown 설계·Git | accepted 목적/요구/범위/TC. repo ID + path + commit SHA + selector | 정확한 revision의 regular file을 읽음. 기존 architecture/ADR/TC를 참조하고 필요할 때만 허용된 얇은 adapter. Contents read; 변경은 owned branch의 PR |
| Native hierarchy | 현재 parent/sub-issues. 실제 Issue identity | WR의 관계 projection. 고정 delegated_goal과 별개. read와 실제 source 편집 권한 분리; 자동 동기화/재부모화 없음 |
| Native dependencies | 현재 blocked-by 관계와 source/destination identity | WR input_contract의 필요한 산출물 조건과 대조. closed 여부나 edge 존재가 만족 증거는 아님 |
| Projects | 선택한 Project/field/option ID의 계획 순위 | WR planning 한 원본만 사용. 현재 값은 projection; Done은 완료/위임이 아님. 자체 backlog·field 복제·자동 Project 생성 없음 |
| Issue type/추가 field | 기존 조직 분류와 사용자 표시 | 양식·type 누락으로 거절하지 않음. v1은 새 field를 자동 실행 정책/priority source로 채택하지 않음; 추가 mapping은 명시적 후속 계약 |
| Milestone | 이미 정한 release/기획 묶음. repo + milestone ID/number | 선택적 링크/조회. due date·closed count로 deadline 권한이나 목표 완료를 만들지 않음; 자동 생성·닫기 없음 |
| PR·branch·diff | 하나의 독립 검토 가능한 결과. repo/PR + source head + base + owned branch | 현행 owned branch/PR marker 사용. 파일·commit pagination 포함 실제 diff 검토. head 변경 시 review/check 재판정 |
| Reviews·threads | 검토 판단/미해결 지적. 실제 reviewer/provider·review ID·commit·thread ID | exact head에 대응하는 code/security/native human review를 구별. comment prose·요청됨·bot 이름만으로 완료 인정하지 않음 |
| Check runs·Actions | deterministic TC/CI. repo/workflow/path/event/run/attempt/job/app/target SHA | 원본 producer와 revision을 EX gate로 대조. 새 초록 check를 Hydra가 만들어 통과시키지 않음 |
| Actions artifacts/logs | 특정 run의 시험·스크린·진단 산출물. artifact ID/run/head/가능한 digest | 필요한 것만 bounded read. 내용은 비신뢰 데이터. 만료·미조회는 unavailable; artifact 이름·압축파일 존재로 TC 성공 선언 금지 |
| Rulesets·CODEOWNERS | 현재 base에 적용되는 보호와 승인 책임 | 유효한 여러 규칙과 실제 human approval을 확인. read 불가를 보호 없음으로 변환하거나 자동 완화하지 않음 |
| Merge queue | 보호된 repository의 순서/통합 검증 | EX queue 계약이 qualified인 경우만 enqueue/통합 SHA/merge 대사. direct 우회 없음 |
| Environments·deployments | 배포 승인·실제 deploy 상태/대상 SHA | 기존 환경의 보호를 관측하고 허용된 전달만 진행. 환경 승인·secret 읽기·보호 변경 권한을 코드 위임에서 추론하지 않음 |
| Releases·tags/assets | 별도로 승인된 배포/사용자 공개 결과 | 선택적 원본 참조. tag/release 존재는 실행 관측이 아님. release 생성/asset upload는 해당 제품 release 권한과 spec이 있을 때만 별도 효과 |

Native sub-issue API는 조회에 Issues read, 수정에 Issues write를 문서화한다.
추가 요청의 `sub_issue_id`는 Issue number가 아닌 실제 Issue ID이며 같은 repository owner 제약이 있다.
교차 repository라는 말만으로 교차 owner 연결을 보장하지 않는다.
[공식 sub-issues REST](https://docs.github.com/en/rest/issues/sub-issues)

Dependencies 역시 조회/수정 권한을 나눈다. 현재 경로는
`GET /repos/{owner}/{repo}/issues/{number}/dependencies/blocked_by`이고,
수정 API의 `issue_id`를 `issue_number`와 혼동하지 않는다.
[공식 dependencies REST](https://docs.github.com/en/rest/issues/issue-dependencies)

Projects는 GraphQL ProjectV2/field/option identity를 제공한다. 필요한 query 접근을 실제 연결에서
확인하며 조회만을 위해 mutation 권한을 요구하지 않는다. 문서의 token scope 예시는 신규 token 발급 지시가 아니다.
[Projects API](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects)
기존 Issue fields도 원본 표시 대상으로 읽을 수 있으나 v1의 계획 source를 암묵적으로 늘리지 않는다.
[Issue fields](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-and-managing-issue-fields)

## 3. Transport·권한·조회 완전성

지원 판정은 transport의 실제 REST version/header·호출 주체·endpoint 접근을 포함한다. 최신
문서의 예제 version과 현재 transport 기본값을 같다고 추정하지 않는다. 새 version 채택은
관련 fixture/응답 호환 검증을 거치며 무조건적인 최신화는 하지 않는다. repository metadata의
admin 표시는 모든 보호/조직 endpoint에 대한 접근 증거가 아니다. 일부 ruleset 조회 성공과
적용되는 모든 ruleset/branch protection coverage를 구분한다. denied/allowlist 차단은 미확인이다.

관계 준비는 P10의 native 등록 주체가 기존 허용 경로를 통해 조정한다. 전용 connector writer가
없으면 generic read/fetch를 write로 해석하지 않는다. 기존 runtime transport도 caller·효과 guard·
intent 복원·read-back을 시험하기 전에는 관계 쓰기를 지원한다고 표시하지 않는다. 정확한 추가
대상과 근거는 WR의 원본 계약을 따르며 sub-issue replace_parent는 false다. P11은 읽기/gate를
유지하고 자동 reparent·관계 삭제·동기화를 만들지 않는다.

Interactive 작업은 연결된 GitHub connector, runtime은 현행 명시적 service identity/gh 경로를 사용한다.
사람의 승인 계정으로 전환하지 않고 token을 worker·문서·오류·artifact에 전달하지 않는다.
일반 업무에는 Issues/Contents/Pull requests의 해당 read/write, 검증에는 Checks/Actions read가 필요하다.
rerun은 별도 Actions write 효과다. admin·secret·환경 승인 권한을 묶어서 요구하지 않는다.
정확한 현재 token/App permission은 endpoint와 실제 연결에서 검증하며 부족한 범위만 unavailable로 표시한다.
[Check runs 권한](https://docs.github.com/en/rest/checks/runs)

2026-10-19 connector metadata 확인 범위에서 `fetch_commit_workflow_runs`는 PR-triggered 첫 page,
run jobs는 latest attempt 첫 page, artifacts도 첫 page다. generic fetch는 허용된 GET만 제공하며
organization/secret 계열을 제외하고 managed App의 administration 접근을 제공하지 않는다.
따라서 wrapper 하나의 결과만으로 push/merge_group·전체 job·org ruleset/protection coverage를 선언하지 않는다.
API 문서 존재, 도구 노출, 실제 설치 권한, 대상에서의 정상 호출은 각각 별도다.

| 읽을 원본 | 최소 실제 조회 | unknown 처리 |
| --- | --- | --- |
| Issue/comments/PR files/reviews/jobs | endpoint별 모든 필요한 page와 author/repo/head 확인 | 첫 page·검색 상한·중복/누락 page는 partial |
| Parent | REST parent 또는 qualified GraphQL Issue.parent와 source identity | REST 404 단독은 없음 증거가 아님. 오류 없는 nullable 조회도 권한/가시성 범위를 검증한 뒤 사용 |
| Blocked-by/children | 각각의 native collection과 terminal pagination | 한쪽 API 실패를 []로 바꾸지 않음 |
| Projects | ProjectV2 item/field lookup과 cursor 종료 | 없는 item·삭제 field·미등록 option·partial은 planning_unavailable |
| Protection | 현재 base에 적용되는 rules와 각 실제 source | 불완전하면 해당 자동 전달 hold; 다른 계정/새 자격으로 자동 우회 없음 |

GraphQL 문서의 Issue.parent는 nullable 관계다. 이 schema만으로 실제 connection의 가시성/권한을
입증하지 않으며 정상 absent와 denied를 실제 대상에서 구분해야 한다.
[Issue GraphQL](https://docs.github.com/en/graphql/reference/issues)

REST pagination은 endpoint의 next link/종료 규칙을 확인하고 GraphQL은 pageInfo/오류를 함께 검사한다.
현행 `_pages`의 count 방식은 새 endpoint에 대한 qualification을 대신하지 않는다.
[Pagination](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api)
rate limit은 Retry-After/reset 근거로 bounded 재관측하며 403/429를 부재로 변환하지 않는다.
단순 주기 재호출·새 credential·별도 webhook 서버로 제한을 우회하지 않는다.
[Rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)

## 4. Issue·PR 작성 기본값

Issue 양식/labels와 branch/identity는 WR 및 현행 GitHub workflow 계약을 재사용한다.
가령 `example/alpha#11`은 `[Work] 빈 입력 처리`라는 제목이나 기존 자유 형식 제목을 사용할 수 있다.
Goal은 요구·완료 기준의 묶음이며 직접 worker를 배정하지 않는다. type·prefix·milestone은 권한이 아니다.
PR 하나는 독립 review/검증/전달 가능한 결과다. 함수·테스트마다 PR을 만들지 않고 unrelated 결과를 묶지 않는다.

공개 가능한 PR 본문 기본 예시는 다음과 같다. 실제 SHA·결과는 원본을 확인해 기입한다.

~~~markdown
빈 입력에서 예외가 발생하던 경로가 정의된 빈 결과를 반환한다.

Related issue: https://github.com/example/alpha/issues/11
Accepted design: docs/engineering/empty-input/spec.md @ <verified commit SHA>
Requirements: R-EMPTY-1, R-EMPTY-2

Verification: exact head의 요구별 TC·필수 CI·리뷰 링크와 아직 확인하지 않은 동작.
Remaining: post-merge 검증과 해당 owned resource 정리.
~~~

자동 closing keyword와 closing Development linkage를 생성 기본값으로 쓰지 않는다.
본문·생성 commit/squash message에 `Fixes owner/repo#N`, `Closes: #N`, 대소문자 변형도 포함해 검사한다.
GitHub는 default branch로 합쳐진 연결/commit에서 Issue를 닫을 수 있으므로 `Related issue`와
기존 identity marker로 연결하고 전체 acceptance·post-merge·잔여 cleanup을 별도로 확인한다.
사람이 직접 조기 close해도 EX/WR의 미완료 책임 발견을 유지한다.
[PR–Issue 연결과 자동 close](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)

## 5. 검증·전달·응답 유실

CI 실행 보존은 전달 계약의 일부다. PR은 같은 workflow/PR의 최신 후보 중심으로 취소할 수
있지만 main push는 각 run을 독립 concurrency group으로 분리해 다른 merge SHA의 실행이
취소/대체되지 않게 한다. 권장 구분은 workflow+PR number와 workflow+push run_id다.
cancel-in-progress=false만으로 같은 그룹의 pending 교체를 해결했다고 보지 않는다.
검증 대상은 여전히 정확한 repository/merge SHA/workflow/producer/jobs/run attempt다.
run_id별 그룹은 전달 증거 보존을 위한 것이며 배포 환경의 별도 직렬화 정책을 바꾸지 않는다.
P14가 workflow 변경·연속 push TC·실제 관측을 소유한다. 나중 main green으로 이전 SHA를 대체하지 않는다.

[공식 concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)의
2026-10-19 동작 기준이다. 지원되는 queue 옵션이 있어도 용량·overflow·순서 조건이 별도이므로
v1 direct 전달에 queue를 새 필수 조건으로 추가하지 않는다.

Review/check는 원본 source head와 실제 producer를 검증한 뒤 사용한다. green 이름, model summary,
다른 run attempt, stale approval, PR에서 만든 자체 성공 artifact를 통과로 인정하지 않는다.
Actions rerun은 원래 SHA/ref와 최초 actor 권한으로 실행되므로 새 코드 검증이나 승인 획득으로 취급하지 않는다.
허용된 실패 원인·횟수 안에서만 요청하고 run/attempt read-back 전 중복 요청하지 않는다.
[Rerun 동작](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)

Rulesets는 함께 적용되고 base CODEOWNERS가 리뷰 요청에 쓰인다. 후보 branch에서 보호 파일을
바꿨다는 이유로 현재 required review가 사라지지 않는다. 필요한 human approval을 service review로 대체하지 않는다.
[Ruleset layering](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets),
[CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)

Queue에는 PR head와 다른 통합 SHA 및 `merge_group` 검증이 필요하다. 지원 plan/설정·enqueue 도구·
실제 target 증거가 없으면 queue-required 전달만 보류한다. Environment 승인/secret availability는
merge 완료와 별도이며 해당 protection을 우회하지 않는다.
[Merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue),
[Environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

Artifacts는 run/head/ID와 가능한 digest·만료 여부를 확인한다. 만료된 증거를 로컬 성공 표로 대체하지
않으며 진단 archive는 기존 자원 lifecycle 안에서 bounded로 취급한다. secret/raw private log를 공개하지 않는다.
[Actions artifacts](https://docs.github.com/en/rest/actions/artifacts)

모든 write는 원래 WR/EX intent와 효과 key를 사용한다. 응답 유실 후 complete 0건도 POST 미실행 증거가
아니다. 늦은 양성 결과는 원래 intent에 붙이고 Pause 동안 새 dispatch하지 않는다. 실효과가 있었는지
모른 채 다른 payload/key로 바꾸지 않는다. webhook/event를 쓰는 후속 경로도 재조회 힌트일 뿐 권한·정본이 아니다.

## 6. 완료 증거와 구현 연결

P03은 source 호환, P09는 기계 binding, P10은 해석·채택·등록, P11은 관계/계획 adapter를 소유한다.
전달·CI 보강 PR은 EX 및 아래 추가 transport 사례를 검증한다. 이 문서 작성은 TC 실행이 아니다.

| 검사 | 요구되는 결과 | 기존/계획 TC 연결 |
| --- | --- | --- |
| 첫 page·누락 permission·REST parent 404 | complete/없음/성공으로 바꾸지 않음 | WR-D51/60/66, P11-D01–05 |
| forged/stale green 또는 다른 workflow/run/head | effect 0회, 정확한 source 요구 | 기존 test_delivery_evidence.py·test_required_job_ambiguity.py와 EX |
| GI-D01: PR/commit의 colon·cross-repo closing keyword | 자동 조기 close 생성 0회, Related 링크 유지 | test_github.py·test_squash_completion.py에 계획 |
| GI-D02: wrapper first page로 push/queue 전체성 주장 | partial, 해당 전달 0회 | test_github.py·test_delivery_evidence.py에 계획 |
| response lost→complete 0→Pause→late success | 동일 intent 복구, 중복 POST/dispatch 0회 | WR-D56·EX 응답 유실 시험 |
| optional Projects/Release/Milestone 미사용 | 기본 SDLC의 불필요한 설치/승인 0회 | WR-D57/69·P11-D06 |

실제 source read/write 권한·전체 pagination·head/run/artifact·보호 경로는 허용된 fixture에서만 관측한다.
현재 metadata inspection은 실제 계정 권한이나 native 관계 수정 성공 증거가 아니며 모두 구별해 보고한다.
