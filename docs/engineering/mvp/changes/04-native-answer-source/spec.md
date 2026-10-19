# P04 — 실제 질문·답변·선택 근거를 재발견하는 source

Revision: 3 · 상태: 설계 후보 · 2026-10-19 · 번호는 계획 ID이며 실제 PR 번호가 아니다.
공통 시작·리뷰·전달 기준은 [PR 규약](../README.md)을 따른다. 실제 source qualification: NOT RUN.
이 명세를 유지·개정하며 아래 구현 단계를 여러 PR로 전달할 수 있다. PR마다 해당 단계·요구와 정확한 명세 판본을 고정한다.

## 1. 목적과 범위

한 질문의 답변을 native 원본에서 정확히 읽고, controller restart 뒤 같은 선택과 미전송 의도를
다시 찾는다. R01/R06/R08/R10/R12/R16, [NC §2.1–3](../../contracts/native-capability.md#21-질문과-재개를-위한-원본-연결),
[EX §7](../../contracts/execution.md#7-질문결정다음-wake)이 요구·identity·선택 의미의 정본이다.
대화 요약·`resolved` 알림·auto-accept를 사람의 답변이나 적용 사실로 바꾸지 않는다.

| 여섯 설계 항목 | 이 명세의 결과 |
| --- | --- |
| 목적 | 질문/답변/선택의 출처·현재 판본·귀속을 잃지 않고 후속 P06에 전달 |
| 책임 | provider가 실제 원본, adapter가 bounded normalized source, Codex가 의미 해석 제안 |
| 동작 | 같은 책임의 원본 질문/답변 읽기 → exact 선택 근거 확인 → 지원 native source에서 미전송 의도 재발견 |
| 실패·복구 | 삭제·부분 조회·수정·권한 철회·유실을 구분. 원본 재조회 없이 새 답/질문으로 덮지 않음 |
| 완료 | 정상 원격 답변과 native 의도 write/read/restart의 실제 양성 증거 + 변경/유실 D |
| 범위 | source qualification과 최소 adapter. GitHub 적용 게시·fresh assignment·전달 효과는 P06 이후 |

질문 전달은 CS §3.1에 따라 native 질문을 기본으로 하고 선택지와 추가 설명·주관식 응답을
보존한다. MCP elicitation 성공은 native Q/A의 출처 증거가 아니다. 준비 질문은 fake attempt를
만들지 않는다. 부분 응답·명시적 수정·충돌은 EX §7의 영향 범위대로 처리하고 VF L07 변형으로
평가한다. 실제 원격 UI·응답 귀속·restart는 동일한 source profile에서 검증한다.

## 2. 선행과 provider mapping

P01은 입력 경로 선택에 참고할 진단이며 P04의 지원 증명이 아니다. 기존 허용 task와 유효 work를
재사용할 수 있다. P07의 신규 task 생성이나 P09의 전체 native intake 전환을 먼저 요구하지 않는다.
질문 시험은 별도 범위의 실제 mutation이며 read 시험에 숨기지 않는다. 지원 source가 없으면
해당 capability는 BLOCKED이고 미실행 시험은 NOT RUN으로 남긴다. P06 pure guard·다른 독립 작업은 계속한다.

구현자는 아래 mapping의 빈 부분을 **사실 확인**으로 닫고 해당 source/version을 fixture에 고정한다.
API 이름을 이 표의 제품 의미에서 역으로 만들어내지 않는다.

| 의미 | 구현 전 특정할 source·접근 | 부족하면 |
| --- | --- | --- |
| work↔owning task↔원 질문 | 지원 reader, caller/host, 실제 locator·조회 coverage | 제목·마지막 메시지로 연결하지 않음 |
| answer·응답 권한·수정 관계 | 원격 입력의 실제 항목과 provider가 보장하는 출처/판본 | role=user·clientId·resolved만으로 대체하지 않음 |
| 선택된 답·안전한 의도·대상 공개 참조 | 지원 native source의 읽기/쓰기·변경 검출·재시작 보존 | private DB/blob/journal 또는 일반 `_meta`로 발명하지 않음 |
| normalized source→Hydra | 모델 재서술과 구별되는 지원 transport/caller 경계 | read 가능성만으로 trusted adapter를 켜지 않음 |

스키마는 NC/EX의 원본 의미와 [CP의 DecisionView](../../contracts/control-plane.md)를 참조한다.
P04는 GitHub의 exact intent/result를 native에 복제하지 않는다. P06이 소비할 유효 선택과
native의 미전송 의도 연결까지만 제공한다. **P06 실제 효과 게시를 P04 완료 조건으로 요구하지 않는다.**

### 구현 단계와 후속 인계

| 단계 | 시작 조건·구현 범위 | 완료 증거와 후속 소비 |
| --- | --- | --- |
| 연결 사실 확인 | 이미 허용된 기존 task와 읽기 범위에서 위 mapping을 특정한다. NC §2.2/3에 따라 caller·surface·설치/version·owner·권한·원본 coverage·transport를 대조한다. | 기존 검증 기록에 확인한 필드와 미확인 의미, 한 실제 시험 경로와 허용 효과를 남긴다. 정적 지원·도구 노출만으로 질문 기능을 활성화하지 않는다. |
| 최소 양성 실증 | 특정한 경로에서 실제 원격 응답을 받을 수 있는 범위와 대상이 위임돼 있어야 한다. 필요한 최소 reader/transport adapter만 먼저 구현할 수 있다. | 아래 절차의 원본 read-back·복원·비공개 경계 증거를 같은 profile에 연결한다. 선택 원본을 P06에 제공할 수 있는지 판정하며 P06 업무 효과는 만들지 않는다. |
| adapter와 소비자 연결 | 실증에서 확인한 의미·제약을 고정한 공개-safe fixture와 §4의 독립 oracle을 사용한다. | reader→normalized source→DecisionView와 P06 입력 연결을 검증한다. fixture 통과와 실제 연결 통과를 구별하고, 필요한 양쪽 증거가 있을 때만 해당 profile을 활성화한다. |

이 순서는 실제 활성화의 근거 순서다. 독립 fixture·guard·비활성 adapter 구현은 실증과 병행할 수
있으며, 실증에 필요한 최소 adapter도 관련 D를 통과한 판본만 사용한다.

최소 실증 입력은 **기존 work/owning task 하나, 그 범위의 실제 미결 질문 하나, 원격 응답자,
현재 권한·설계 판본, 미전송 의도를 둘 수 있는 지원 원본**이다. 시험만을 위해 제품 질문을
꾸며내지 않는다. 실제 질문이 없으면 실증은 NOT RUN으로 두거나 별도로 위임된 시험 대상에서
수행한다. 이미 있는 질문을 재사용하며 새 질문이 필요하면 그 생성·전달이 위임된 경우에만 한다.
대기 timeout·호출 한도·취소 후 읽을 원본을 실행 전에 기존 검증 기록에 고정한다.

1. 원격 응답의 정확한 질문 귀속·판본·응답 출처와 선택을 원본에서 읽고, 지원 경로로 미전송 의도를 보존·read-back한다.
2. Hydra controller를 재시작해 memory/cache 없이 같은 질문·선택·미전송 의도를 복원한다. native app/host는 이 시험에서 재시작한 것으로 간주하지 않는다.
3. §4의 수정·삭제·부분 조회·응답 유실 변형은 고정 fixture로 검증한다. 실제 원본 장애 유발은 별도 위임 없이 수행하지 않는다.
4. 실제 원본→Hydra 전달 결과와 P06 입력을 대조한다. 질문 중복 생성·GitHub 결정 게시·후속 실행은 이 실증의 허용 효과가 아니다.

원본과 전달·복원이 모두 기대대로 연결되면 해당 시험은 PASS다. 실행했지만 잘못된 귀속·선택
복원이나 금지 효과를 관측하면 FAIL이다. 접근/권한 부족은 BLOCKED, 지원 명세·실제 응답으로
확인한 미지원은 그 profile의 capability 한계로 기록하고 해당 시험을 BLOCKED로 남긴다.
미실행은 NOT RUN이며 모두를 `unsupported`로 반환하는 구현은 양성 통과가 아니다.
기록은 NC §3/VF의 기존 양식으로 정확한 소스·명세 판본, 실제 입력 범위·관측·판정·남은
책임을 연결한다. 공개 문서에는 private locator·대화·인증 값을 복제하지 않는다.

연결을 못 닫으면 P06의 실제 결정 적용과 원격 질문 통합만 보류한다. pure guard와 독립 TC는
계속한다. 새로운 저장소·credential·runtime이 필요하다는 발견은 이 범위의 불충족과 필요한
결정으로 보고하며 임의 도입하지 않는다. 같은 명세를 개정하고 실증 범위 변경을 기록한다.

## 3. source와 구체 구현 순서

| source 후보 | 책임 |
| --- | --- |
| `hydra_sdlc/native.py`의 provider 경계 | 원본 adapter의 dependency injection·scope 검증; 업무 mutation 호출 금지 |
| `hydra_sdlc/control.py` | 지원된 source의 상태·coverage만 CP projection으로 전달 |
| `hydra_sdlc/mcp.py` | 선택된 경로가 실제 MCP인 경우에만 source transport 연결; generic model JSON 승인 API 금지 |
| `plugins/hydra/skills/sdlc/SKILL.md` | 원본 질문·선택의 역할과 기존 도구 권한을 분명히 함 |
| 예정 `tests/test_native_answer_source.py` | 고정 source fixture와 read/restart/수정 oracle; 내부 adapter 모듈 분리는 구현 재량 |

1. 설치/호출 주체별 source mapping과 미확인 필드를 기록하고 NC 결정표로 실제 시험 경로를 하나 고른다.
2. 요구의 의미와 실제 필드를 대조한다. 접근 제한은 사람에게 필요한 정확한 권한만 남기며 새 계정/서명 체계를 기본으로 추가하지 않는다.
3. 정상 질문·답변·선택·미전송 의도와 변형 fixture를 공개-safe 형태로 작성한다. 원문/ID를 public fixture에 복사하지 않는다.
4. reader와 pure normalized selection을 분리하고 bounded pagination, 현재 revision, source 불일치 거절을 구현한다.
5. 같은 native source의 선택/의도 write-read-restart를 qualified 경로에서 시험한다. 전송 유실은 해당 원본부터 확인한다.
6. 정상 normalized 입력을 P06 guard fixture에 전달할 수 있음을 확인하되 GitHub decision 게시나 실제 다음 배정은 수행하지 않는다.

## 4. 결정적 사례와 판단 평가

| 연결 ID | 정상/장애 자극 | 독립 oracle |
| --- | --- | --- |
| NC-D03/06, EX-D12 | 같은 질문의 실제 답변/선택 source | exact source refs·채택 판본·허용 출처가 normalized 결과에 연결; 정상 답을 영구 unknown으로 두면 실패 |
| NC-D03, VF-D05 | turn 종료·중단·자동 해결로 resolved만 발생 | received/accepted/applied 생성 0; native 원본과 수명 알림 분리 |
| NC-D04/09 | partial page·삭제·403·timeout·새 schema | source별 unknown/conflict; 원문 부재를 답변 없음/완료로 바꾸지 않음 |
| EX-D12, VF-D06 | 의도 쓰기 전/후 ACK 유실·controller restart | 같은 source에서 선택/미전송 의도 복원; 중복 질문·새 선택·public write 0 |
| EX-D12, VF-D08 | 답변 수정·선택 교체·work/spec/head/권한 변경 | EX의 수정 시점 계약으로 유효 선택 또는 재평가, 옛 선택의 자동 적용 0 |
| NC-D10, VF-D12 | private 원문·식별자·credential canary | 공개 DTO/log/fixture에는 0; 허용된 의미와 연결은 유지 |

L은 필요한 평가다. Codex가 실제 질문의 답을 현재 요구에 맞게 해석하고 안전한 공개 의도를
제안하는지를 VF L07의 독립 rubric으로 본다. 기술 선택과 사람 판단, 답과 새 목표, 명시적 수정과
모호함을 구분한다. D가 응답 권한을 검증하고 LLM은 권한/허용 효과를 새로 만들지 않는다.

## 5. 검증 명령·실제 시험

| 상태 | 명령/관측 |
| --- | --- |
| 기존 회귀 | `python3 -m unittest discover -s tests -p 'test_native*.py' -v` |
| 기존 회귀 | `python3 -m unittest discover -s tests -p 'test_mcp.py' -v` |
| 예정; 생성·수집 확인 후 | `python3 -m unittest discover -s tests -p 'test_native_answer_source.py' -v` |
| O 예정 | 한 허용 task의 실제 질문→원격 답변→선택/미전송 의도 source read→controller restart→같은 source 재발견 |

명령은 공통 규약의 지정 runner에서 실행한다. 이번 설계에서는 실행하지 않았다. O는 provider
원본과 actual response를 관측하며 모델 요약이나 mocked remote 화면으로 대체하지 않는다.
답변 이후 native turn이 시작됐는지는 따로 기록하고 Hydra 효과의 승인을 뜻하지 않는다.
native app/host restart는 controller restart와 별도 관측으로 남긴다. 지원되지 않으면 그 범위만 명시한다.

## 6. 리뷰·호환·회복·끝조건

reviewer는 source mapping·권한·부분 조회·수정 순서·유실 재조회·private 공개 경계를 검토한다.
기존 legacy progress/decision 의미를 조용히 바꾸지 않는다. 새로운 결정 적용 guard는 P06의
보호된 project version 경로로 전달한다. 지원 부족에서 legacy marker 소비로 fallback하지 않는다.
source-only PR은 mock/adapter 검증 상태로 전달할 수 있지만 실제 Q/A·의도 복원이 없으면
P04 capability는 완료가 아니다. fail-closed만 구현한 것을 정상 질문 흐름의 구현으로 세지 않는다.
실제 양성 source qualification 뒤 P06이 normalized 입력을 사용해 효과 처리하고, 전체 Pause→Resume
왕복은 후속 통합에서 시험한다. 이 순서로 P04↔P06의 완료 의존 순환을 만들지 않는다.
