# P11 — Native 관계·선행 산출물·선택적 계획

Revision: 3 · 상태: 설계 후보 · 2026-10-19 · 작업: Issue #3

공통 규칙은 [변경 계약](../README.md), 타입/상태 정본은 [WR §9–10](../../contracts/work-records.md#9-관계-원본입력조건계획을-따로-읽는다)다.
API 권한/도구/현재 한계는 [GitHub 연결 계약](../../contracts/github-integration.md)을 따른다.

## 1. 목적·책임·범위

| 항목 | 계약 |
| --- | --- |
| 목적 | GitHub의 현재 관계를 보면서 실제 필요한 산출물이 준비된 작업부터 진행한다. |
| 책임 | GitHub는 parent/blocked-by/선택적 계획 원본, accepted 계약은 고정 입력조건, Hydra는 대조·증거 판정. |
| 동작 | complete 관계 읽기 → 고정 input_contract 대조 → 실제 산출물 검증 → 유효 후보 정렬/guard. |
| 실패·복구 | partial·drift·증거 철회는 관련 효과만 hold; 원래 pending/위임과 독립 작업은 보존. |
| 완료 | closed-only 오판·이중 관계 정본 없이 정상 재시작/변경 영향과 유효 진행이 검증됨. |
| 범위 | 관계/계획 read adapter와 gate. 관계 편집 UI·동기화 DB·Project 생성·새 자격 없음. |

## 2. 요구와 입력·출력

- **P11-R01**: 선택한 source 하나만 사용한다. native parent는 현재 사실, delegated_goal은 고정 권한 근거다.
- **P11-R02**: RelationRead의 coverage·pagination·identity를 확인하며 없음/partial/unavailable을 구별한다.
- **P11-R03**: native blocked-by와 수용 입력조건을 대조하고 실제 requirement/revision/stage 증거로 충족을 판정한다.
- **P11-R04**: 추가/제거 edge가 accepted 조건을 자동 변경하지 않는다. source 변경과 기존 효과 대사를 분리한다.
- **P11-R05**: Projects는 선택적 단일 계획 원본이다. 값 없음과 접근 실패를 구별하고 silent fallback하지 않는다.
- **P11-R06**: 목표 완료는 요구별 증거로 판정한다. child close/이동/Project Done이 완료나 잔여 책임 소멸을 뜻하지 않는다.

입력은 protected source/planning 선택, WR binding/input_contract, native relations, producer의 실제 전달 증거다.
출력은 메모리 RelationRead/선행 충족 상태/정렬 값/명시적 wait 이유다. 현재 edge/priority의 영속 사본은 없다.
Projects field priority 변경은 source body/digest를 바꾸지 않는다. 반대로 Issue-body priority 변경은
exact source digest를 바꾸므로 WR 원문 변경·새 binding/attempt 계약을 그대로 적용한다.

## 3. 선행과 수정할 접점

선행은 P03 source guard와 [P09](../09-work-binding/spec.md)의 고정 계약 resolver다.
P10 채택된 작업으로 통합 시험하되 read adapter의 fixture 구현은 P10과 독립 진행할 수 있다.
실제 credential/target의 native 조회·가시성·pagination 관측이 활성화 전 필요하다.

| 경로 | 구체 책임 |
| --- | --- |
| `hydra_sdlc/github.py` | parent/children/blocked-by read, bounded pagination/GraphQL 오류·field identity 관측 |
| `hydra_sdlc/work_records.py` | P09 타입 재사용, 입력조건/관계 집합 대조·순수 충족 판정 |
| `hydra_sdlc/project.py` | WR planning mapping과 source별 validator |
| `hydra_sdlc/runner.py:_latest/status` | 새 효과 앞의 관계/증거 guard, 목표 집계와 독립 후보 정렬 |
| `tests/test_work_dependencies.py` | 새 계획 파일: graph·planning·drift·goal evidence fixtures |
| `tests/test_github.py`, `tests/test_runner.py`, `tests/test_status_isolation.py` | 기존 transport/legacy/독립 후보 회귀 |

## 4. 구현 순서와 API 선택

1. WR-D17–21/27–28/33–34/48–69의 native·계획 관련 fixture를 먼저 고정한다.
2. parent/sub_issues/blocked_by의 실제 source identity와 pagination 종료를 관측하는 read adapter를 추가한다.
   REST parent 404만으로 no-parent를 선언하지 않는다. 지원되는 GraphQL Issue.parent의 nullable 결과도
   source identity·field 오류·가시성 근거와 함께 검증한다. 미확인 경로를 임의 성공으로 메우지 않는다.
3. 두 complete 관측의 membership drift와 graph 자원 상한을 WR대로 처리한다. 외부 원자 snapshot을 주장하지 않는다.
4. normalized 입력조건의 producer/requirement/stage를 실제 전달 증거와 대조한다. close-only 분기를 native source에서 사용하지 않는다.
5. optional ProjectV2/field/option ID mapping을 읽는다. item/field의 null과 missing/403/partial을 구별한다.
6. 현재 parent·Project 순위 변경과 accepted scope 변경을 나눠 표시하고 effect 전 gate에 연결한다.
7. 목표의 required output과 기존 progress/미완료 효과를 조회한다. 현재 child 목록만으로 책임을 발견하지 않는다.

관계 source write의 준비 조정은 P10의 native 등록 주체가 소유하고, 실제 효과는 qualified GitHub/native 경로에서 수행한다. read-only adapter 구현이 자동 관계 편집 권한은 아니다.
연결이 필요한데 write 경로가 없으면 그 준비를 미완료로 표시하고 source를 복제하지 않는다.

## 5. 결정적 TC와 oracle

Oracle은 독립 작성한 그래프/수용 조건/실제 merge·CI·운영 증거 fixture 및 effect 호출 기록이다.
정렬 oracle은 보호된 mapping과 고정 created_at/IssueRef다. 대상 graph 함수로 기대 결과를 만들지 않는다.

| ID | 사건 | 기대 결과·금지 효과 |
| --- | --- | --- |
| P11-D01 | 2 page 성공/2번째 실패/중복 page | 각각 complete/partial/invalid; partial을 빈 관계로 판정하지 않음 |
| P11-D02 | parent present/명시적 absent/REST 404·GraphQL field error | qualified present/absent만 채택, 나머지는 unknown |
| P11-D03 | parent 이동, scope/권한 그대로 | 현재 parent만 갱신, delegated_goal·binding 유지, 새 attempt 0회 |
| P11-D04 | blocked-by 추가/제거 또는 두 수집 사이 변경 | 관련 effect hold, accepted 조건 삭제·edge 사본 갱신 없음 |
| P11-D05 | cycle/한도초과/cross-repo 접근 실패/rename | cycle·partial·identity별 구분, 독립 작업의 guard 통과는 유지 |
| P11-D06 | Projects 없음·priority 없음·native empty·수용 clauses=[] | 기본 0으로 독립 작업 진행, 새 Project/문서 생성 0회 |
| P11-D07 | Project field null/missing/type 변경/option 교체/REDACTED item | 검증된 null만 기본값; 나머지 planning_unavailable, issue fallback 0회; REDACTED를 complete/빈 항목으로 합성하지 않음 |
| P11-D08 | Project 순위 변경/Issue body priority 변경 | 전자는 재정렬만; 후자는 source drift→WR 재채택, 무재바인딩 예외 적용 0회 |
| P11-D09 | closed-but-no-output/open-but-required-output | 각각 미충족/충족, auto-close·프로젝트 전용 의미 0회 |
| P11-D10 | observed 요구에 post-merge CI만 있음 | 운영 증거 대기, 만족 판정 0회 |
| P11-D11 | cache 소실 후 같은 anchor/accepted 입력조건 | 같은 의미 복구, 모델 재해석/새 binding 0회 |
| P11-D12 | child가 이동·close됐지만 goal 요구/cleanup 미완료 | achieved/cleanup 완료 오판 없음, 원래 책임 발견 |

## 6. 검증 명령·L/O·독립 review

아래 명령은 구현 시 등록된 자원 환경에서 실행한다. 현재 실행/통과를 주장하지 않는다.

~~~sh
python3 -m unittest discover -s tests -p 'test_work_dependencies.py' -v
python3 -m unittest discover -s tests -p 'test_github.py' -v
python3 -m unittest discover -s tests -p 'test_runner.py' -v
python3 -m unittest discover -s tests -p 'test_status_isolation.py' -v
~~~

첫 파일은 계획 파일, 나머지는 존재한다. 최종 통합은 전체 unittest/required CI를 확인한다.
L 평가는 WR-L01 중 기존 설계의 input 의미·과도한 dependency·목표 acceptance 해석을 사용한다.
graph/identity/정렬 자체는 D 대상이다. reviewer는 closed/UI status를 의미 증거로 쓰지 않는지 확인한다.
O는 WR-O02의 actual native page/권한/변경/rename과 optional Project mapping이다.
사용 가능한 원본 관계를 좁게 변경하는 fixture만 허용하며 별도 credential/조직 정책을 임의 변경하지 않는다.
실제 absent/partial/denied를 구별하지 못한 transport는 해당 capability 미지원으로 남긴다.

## 7. 완료·호환·복구

완료는 accepted revision, 요구별 D/L/O 결과, 독립 code/security review와 final-head CI다.
v1 및 v2+legacy 의미는 유지한다. native source의 원본 지원 부족에 legacy dependencies로 fallback하지 않는다.
새 계약 수용은 원래 pending/owner 대사 뒤 새 binding/attempt로 진행하며 old evidence를 덮지 않는다.
Projects/관계 조회 장애 중 기존 effect reconciliation·보존을 잃지 않는다. 실제 운영 지원은 O 증거 범위로만 선언한다.

## 8. Authenticated graph collection profile

This source-adapter increment implements P11-R02/R04 and P11-D01/D04/D05.
The original functional requirements remain unchanged.

### Interface, source and boundaries

GitHub.native_dependency_read(root, *, repositories) returns DependencyTopology.
The caller supplies a snapshot of current protected registration mapping from safe
positive numeric repository ID to canonical owner/name. Validate before I/O; reject
aliases and malformed/unbounded maps. External graph nodes cannot add registration.
Only reachable blocked_by nodes are queried. Unregistered targets retain unknown
coverage and are never queried. The caller owns the GitHub client exclusively for this synchronous collection;
no concurrent use of its mutable budget stack or credential hook is supported.
The collector composes and restores the prior credential hook in finally,
observing every credential selection including failed and restored transitions.
The reader owns no persistence or external effects.
The existing single-Issue reader retains its API and behavior for other callers.

Two independent breadth-first collections call the existing fixed GraphQL query
reader, with actual API requests per collection. No pool or successful row is
reused. Compare using the existing dependency_topology contract; matching means
membership only. No provider-atomic snapshot or readiness/authority is claimed. This is a real
source adapter, not a new status/continue consumer. Effect-time and user-visible
integration remain separate because their acceptance/authority sources are open.

One aggregate deadline of 45 seconds and 128 HTTP reservations covers both passes,
including nested auth requests, validation and final normalization. Nested 15s /
4-request / 3-page per-Issue bounds remain. Per pass: 256 nodes, 1024 edges, depth32.
Transient provenance retains at most 1024 Issue identities and 1024 repository
identities across both passes; exceeding these caps remains unknown.
Stop before expanding overflow; retain bounded partial prefixes. Comparator also
checks longest acyclic path so shortcut edges cannot evade depth bounds.

A transient provenance observer sees validated source and target repository
ID/name/visibility/role and Issue node-ID to numeric identity mappings for every
accepted page across both passes. Compare known registered names and reject all
cross-node and cross-pass aliases. Pin authenticated credential fingerprint at
first qualified response; missing fingerprint does not qualify this collector.
Actual credential or source identity drift is sticky, overrides cycle precedence,
and invalidates the whole call: unknown
with empty unavailable graphs, never mixed-credential refs. Fingerprints and raw
source metadata never appear in output or logs. Ordinary denial, missing nodes,
partial pages or timeout retain only already-qualified bounded prefixes.

Ordinary failures remain unknown/partial, including a missing entire second pass;
there is no silent empty success. Malformed provider values produce fixed safe
errors or unknown. No raw error, title/body, extra field, native ID or local path
is returned. Finite loops and deadline checks cover graph assembly as well as I/O.
Pause does not prohibit these read-only observations; no coordinator lock, command
route, model call, issue write, assignment, grant, workspace or installation occurs.

## Permanent behavior oracles

Real fixture transport, not supplied precomputed graph DTOs:
- A -> B -> C and empty root: matched complete from two independent collections.
- A changing edge: changed; first and second retain their respective membership.
- Failed later page, hidden node, unregistered producer: never complete-empty.
- Cycles, longest paths, node/edge/depth caps: bounded and distinct outcomes.
- Credential, repository/name/visibility/role and Issue node-ID drift across nodes
  or passes: no matched mixed-scope output.
- Outer request/deadline expiry, normalization overrun and late response: unknown.
- No read of unreachable inaccessible branch; independent root remains usable.
- Public canaries and mutation traps prove sanitized output and zero writes.

Freeze independent expectations before implementation. Purpose fault control must
fail behavior assertions (not imports); preserve original failed evidence. Run
focused tests, per-Issue reader/graph/GitHub regressions; independent immutable
code/security review and required hosted CI before protected delivery. Actual
multi-page/cross-repo operation remains unqualified until separately observed.


Source implementation and tests do not establish installed/native capability,
requirement acceptance, dispatch authority or completion of P11 or Hydra v1.
