# P09 — 수용된 작업 연결의 결정적 검증

Revision: 1 · 상태: 설계 후보 · 2026-10-19 · 작업: Issue #3

공통 규칙은 [변경 계약](../README.md), 정확한 schema/digest는 [WR](../../contracts/work-records.md)가 소유한다.
이 PR은 원문을 실행 가능한 계약으로 검증하는 기계 경계이며 LLM 해석·Issue 생성은 P10이다.

## 1. 목적·책임·범위

| 항목 | 계약 |
| --- | --- |
| 목적 | 원문 형식이 달라도 동일한 identity·범위·revision·위임 검증을 적용한다. |
| 책임 | Codex는 후보를 제안하고 validator는 구조와 원본 근거를 검사한다. parser 성공은 승인 아님. |
| 동작 | exact 원문/선택 comment → WorkBinding/InputContract → 근거 대조 → 준비/실행 적격 결과. |
| 실패·복구 | invalid·unsupported·conflict를 구분하고 기존 원문/attempt를 보존한다. |
| 완료 | legacy bytes 호환, 정확한 채택 선택, cache 없는 같은 계약 복구가 TC로 확인됨. |
| 범위 | 순수 validator와 bounded read resolver. 새 Issue/comment 쓰기·native 배정·관계 편집 없음. |

## 2. 요구와 데이터 경계

- **P09-R01**: WR의 IssueRef/RequirementRef/GoalRef, WorkBinding v2, InputContract를 exact closed schema로 검증한다.
  unknown key/version, 중복 JSON key, boolean ID, 잘못된 path/SHA·배열/byte 한도를 거절한다.
- **P09-R02**: 원문 source_digest는 현행 title/body 직렬화와 byte 단위로 같다. binding digest와 혼용하지 않는다.
- **P09-R03**: 현재 native parent/priority를 binding에 복제하지 않는다. delegated_goal과 수용 입력조건만 고정한다.
- **P09-R04**: 실제 author·comment identity·선택한 ID/digest·review/위임 원천을 확인한다. 최신 comment 자동 선택 금지.
- **P09-R05**: progress → exact attempt anchor → binding → accepted spec/조건을 복구한다. 기존 anchor 의미는 유지한다.
- **P09-R06**: 충분한 기존 설계는 reference 또는 최소 adopted payload로 연결한다. 필수 새 설계 양식을 만들지 않는다.

입력은 immutable한 읽기 결과와 명시적 선택 ref, 보호된 config, 실제 authority/acceptance observation이다.
출력은 검증한 WR 타입과 부족한 근거/거절 이유다. local tracker·raw Issue 사본·secret을 반환값에 추가하지 않는다.
`kind=goal`은 실행 대상이 아니며 spec revision/null·input 계약 누락은 준비와 실행 가능성을 구분한다.
본문 오타/priority 변경도 source digest 변경이다. Projects field 변경과 같은 외부 fact 변화와 혼동하지 않는다.

## 3. 선행과 수정할 접점

선행은 [P03](../03-work-source-compatibility/spec.md)의 v2 source 경계다.
P10/P11이 완성되기 전 parser가 성공해도 전체 native 작업 dispatch를 활성화하지 않는다.

| 경로 | 구체 책임 |
| --- | --- |
| `hydra_sdlc/work_records.py` | 새 계획 모듈: WR 타입 validation/canonical digest/선택·복구 순수 규칙 |
| `hydra_sdlc/github.py` | 실제 author/edited 여부와 bounded comment 조회를 제공하는 read resolver |
| `hydra_sdlc/project.py` | source별 parser 접점. 현행 parse_intake는 보존 |
| `hydra_sdlc/runner.py`, `hydra_sdlc/native.py` | 검증 결과를 기존 guard에 전달; 아직 unsupported인 실행은 차단 |
| `tests/test_work_records.py` | 새 계획 파일: canonical fixture와 positive/negative boundary |
| `tests/test_project.py`, `tests/test_github.py` | 기존 parser/progress/실제 author 처리 회귀 |

## 4. 구현 순서

1. WR의 완전한 synthetic fixture를 고정하고 기존 intake_digest의 null/공백/Unicode 벡터를 독립 계산한다.
2. 순수 schema validator와 두 digest 함수를 구현한다. model/tool/network 호출은 validator 밖에 둔다.
3. explicit reviewed binding ref와 historical anchor 선택을 구현한다. 다른 과거 binding은 보존한다.
4. reference 입력조건의 exact revision/selector를 읽고 구조화 payload 하나를 확인한다.
   prose 원문에는 명시적으로 선택한 adopted 방식만 허용하고 자동 재해석하지 않는다.
5. 실제 author·edit·삭제·partial 관측을 전달하는 read resolver를 연결한다.
6. 실행 side effect spy로 goal/invalid/unknown/unsupported에서는 호출이 전혀 없음을 검증한다.

## 5. 결정적 TC와 oracle

WR-D01/06–10/15–16/22/25–26/29–31/36–40/45/53–55/64를 해당 순수/read 경계에서 재사용한다.
Oracle은 hand-authored 기대 digest/typed values와 source observation fixture다. 대상 serializer로 기대값을 계산하지 않는다.

| ID | 사건 | 기대 결과·금지 효과 |
| --- | --- | --- |
| P09-D01 | valid v2 work, exact accepted refs/authority | 같은 typed 계약과 digest; 모델 호출 0회 |
| P09-D02 | null/empty body, 공백·한글·개행 차이 | 현행 intake bytes와 같고 서로 다른 원문은 다른 source digest |
| P09-D03 | unknown field/version·중복 key·boolean ID·한도 초과 | 구분된 오류, 원문 보존, effect 0회 |
| P09-D04 | 외부 author가 동일 marker 복사 | 정본/권한으로 채택하지 않음 |
| P09-D05 | historical binding 여러 개 + exact anchor | 지정한 판본만 복원, 최신 자동 선택·삭제 0회 |
| P09-D06 | 같은 attempt의 anchor 중복/편집/삭제·digest mismatch | conflict/invalid/unknown, 새 anchor 생성 0회 |
| P09-D07 | goal 또는 준비 spec(null revision) | 허용된 준비만, worker 배정 0회 |
| P09-D08 | accepted prose 설계와 adopted 최소 조건 | 원본 재작성 없이 동일 의미 연결, reference와 이중 저장 없음 |
| P09-D09 | reference selector 모호/과거 의미 미복원 | accepted_meaning_unavailable/invalid, 모델 재해석으로 계속하지 않음 |
| P09-D10 | v1 candidate marker를 v2 source에 전달 | 의미 재해석·자동 migration 0회 |

## 6. 검증 절차와 독립 검토

구현 시 등록된 workspace 자원 경로에서 아래를 실행한다. 지금은 NOT RUN이다.

~~~sh
python3 -m unittest discover -s tests -p 'test_work_records.py' -v
python3 -m unittest discover -s tests -p 'test_project.py' -v
python3 -m unittest discover -s tests -p 'test_github.py' -v
~~~

첫 파일은 계획 파일이며 나머지 둘은 존재한다. 최종 후보에는 전체 unittest/required CI를 적용한다.
L 평가: P09 자체는 N/A. 구조·digest·identity가 oracle인 parser이고 의미 해석 품질은 P10의 WR-L01이 소유한다.
독립 review는 parser 출력이 authority로 승격되는지, digest 알고리즘 변경·mutable source 오인·경로 우회를 검토한다.
O 관측: 기존 허용 fixture의 실제 comments/file read로 author·edit·exact revision·pagination을 확인한다.
이 PR의 관측은 read-only이며 comment 발행/응답 유실은 P10 및 WR-O01에서 검증한다.

## 7. 완료·호환·복구

완료는 accepted spec revision, 요구별 D 결과, 실제 read fixture 또는 명시적 미지원 범위,
독립 code/security review, final-head CI다. parser 구현을 자율 SDLC 운영 성공으로 보고하지 않는다.
progress v1 allowlist/intake digest·legacy work source는 바꾸지 않는다.
source drift는 원래 anchor/pending effect를 보존한다. 동등성 검토 후에도 새 binding/attempt를 사용한다.
롤백은 기존 기록을 지우지 않고 해당 capability를 unsupported로 표시한다. old reader로 새 의미를 실행하지 않는다.
