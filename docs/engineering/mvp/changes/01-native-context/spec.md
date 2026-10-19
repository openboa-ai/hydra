# P01 — 기존 MCP의 호출 문맥을 정확히 읽기

Revision: 1 · 상태: 설계 후보 · 2026-10-19 · 번호는 계획 ID이며 실제 PR 번호가 아니다.
공통 시작·리뷰·전달 기준은 [PR 규약](../README.md)을 따른다. 소스 구현·검증과 설치 미확인 범위는 [검증 기록](verification.md)에 구분한다.

## 1. 목적과 범위

실행 중인 Hydra의 판본과 native caller가 실제로 제공한 transport 문맥을 분리해 확인한다.
status 도달을 task owner·질문 지원·사람 승인으로 오해하지 않게 한다. R01/R06/R14/R16,
[NC §2.4](../../contracts/native-capability.md#24-다음-qualification-단위-설치본과-호출-문맥-읽기)가 정본이다.
첫 결과는 기존 status에 붙는 진단이다. native task 생성·history 조회·질문·wake·mutation은 제외한다.

| 여섯 설계 항목 | 이 PR의 결과 |
| --- | --- |
| 목적 | 다음 native 입력 경로의 실제 qualification에 필요한 최소 사실 제공 |
| 책임 | MCP wrapper가 주입 Context 추출, pure projection이 진단 생성, 기존 controller가 status 유지 |
| 동작 | status 요청 → 현재 SDK 문맥 읽기 → NC의 닫힌 진단 → SDK serialization/consumer |
| 실패·복구 | 진단 필드만 unknown, 기존 status 오류는 보존; 다음 status에서 fresh 재조회 |
| 완료 | NC의 독립 fixture·실제 SDK 통합·설치 read 증거를 종류별 기록 |
| 범위 | 기존 다섯 도구와 CLI·CP wire 의미 유지, 새 원본/서명/저장소 없음 |

## 2. 입력·출력·선행

입출력 schema/default/enum/secret 경계는 [NC §2.4.1–4](../../contracts/native-capability.md#241-출력과-source별-의미)를
참조하며 이 파일에 복제하지 않는다. 입력은 SDK 주입 Context와 startup profile이고 모델 JSON이 아니다.
출력은 `NativeContextProbeV1`이며 caller/client binding의 unverified는 정상 결과다.

- 구현 전 source/head/spec revision과 설치 후보 identity를 고정한다. SDK profile은 repository pin과 대조한다.
- 정적 source/설치 대조는 필요하지만 P04 Q/A 지원 또는 P07 lifecycle PASS를 선행으로 요구하지 않는다.
- optional SDK 없는 CLI 사용을 보존한다. 실제 native client 없이 D fixture 구현·검증은 가능하다.
- 설치 후보 read는 검토한 코드와 실제 runtime이 대응할 때만 O 근거다. 설치/재시작은 공통 규약의 별도 단계다.

## 3. 변경 source와 순서

| 위치 | 변경 책임 |
| --- | --- |
| `hydra_sdlc/mcp.py` | 실제 Context annotation 주입, request 범위 추출, status additive 결과 |
| `hydra_sdlc/runtime_identity.py` | 기존 startup 관측 재사용; dependency attestation으로 의미 변경 금지 |
| `tests/test_mcp.py` | 실제 SDK schema/serialization/stdio fixture와 legacy status 회귀 |
| `tests/test_runtime_identity.py` | startup snapshot·재hash 없음·기존 identity 일치 회귀 |
| `tests/test_native_capabilities.py`·NC fixture 경로 | pure projection과 비간섭의 독립 expected |

1. NC fixture의 정상/유사 실패 입력과 expected를 먼저 작성한다. 전부 unknown 반환도 실패하는 양성 oracle을 둔다.
2. 실제 SDK가 Context를 모델 schema에서 제외하는지 등록 TC로 확인한다. annotation 해석 실패를 문자열 인자로 우회하지 않는다.
3. NC 알고리즘의 bounded extractor와 pure projection을 구현한다. 내부 함수/파일 분리는 구현 재량이다.
4. status를 조립하면서 projects/runtime/controls와 기존 오류를 보존한다. 진단의 예외 경계만 좁게 적용한다.
5. SDK 응답의 실제 structured/text 경로까지 연결하고 consumer가 같은 진단을 읽는지 검사한다.
6. 기존 CLI/control identity 및 다섯 도구 회귀 뒤 독립 리뷰한다. 그 뒤 exact 설치 read를 수행할 준비를 갖춘다.

## 4. 정상·장애 TC와 oracle

정본은 [NC §5.1–2](../../contracts/native-capability.md#51-nativecontextprobev1의-구체-fixture와-oracle)다.
새 이름으로 동일 schema/expected를 중복 관리하지 않는다.

| 연결 ID | 사건 | PASS oracle / 금지 효과 |
| --- | --- | --- |
| NC-D03 | legacy form·modern input의 정상 typed 문맥 | 독립 expected의 known/declared 값이 출력됨; 실제 client/owner 지원으로 승격 없음 |
| NC-D04 | Context 없음, channel만 실패, capabilities 모호 | NC default와 필드별 실패 격리; controller 실패를 빈 projects 성공으로 바꾸지 않음 |
| NC-D06 | 모델 args/metadata에 위조 task·승인 | schema에 Context 없음, caller unverified 유지 |
| NC-D09 | SDK/runtime mismatch·새 protocol·동시 요청·잘못된 bool | 요청 격리와 알려짐의 범위 보존; 자동 downgrade/설치 없음 |
| NC-D10 | 무관 secret·대형 metadata 교체 | 동일 허용 필드의 byte-equivalent 결과, 무관 접근/로그/해시 유출 0 |
| NC-D09/10 | 실제 SDK serialization→consumer | 기존 status 보존과 strict probe 판정; 질문·GitHub write·ticket 변경·native 호출 0 |

## 5. 검증 명령과 증거

아래 명령은 공통 규약의 지정 runner 안에서 실행할 내부 명령이다. 실제 실행 범위는 [검증 기록](verification.md)을 따른다.

| 상태 | 명령/실제 검증 |
| --- | --- |
| 기존 suite, 신규 사례 추가 | `python3 -m unittest discover -s tests -p 'test_mcp.py' -v` |
| 기존 suite | `python3 -m unittest discover -s tests -p 'test_runtime_identity.py' -v` |
| 신규 suite | `python3 -m unittest discover -s tests -p 'test_native_capabilities.py' -v` |
| O 예정 | exact installed 후보의 status 한 번; 실제 runtime과 protocol/capability 진단만 관측 |

D는 필수다. SDK integration skip은 PASS가 아니다. L은 N/A: 의미 해석·taste 판단을 하지 않는
typed extractor이며 정상/거절은 결정적이다. 원본 trace 기반 독립 코드/security 리뷰는 여전히 필요하다.
O는 질문·실행이 아닌 진단 read의 증거다. O가 없으면 source-only 결과를 기록할 수 있으나
installed reader capability를 완료 처리하지 않는다. 전체 native 지원/v1 완료의 증거도 아니다.

## 6. 호환·회복·리뷰·끝조건

이 PR은 A reader의 기존 다섯 도구를 유지한다. 후속 P06의 versioned command 추가를 금지하는
전역 tool-count 규칙은 아니다. CP v2/v3와 CLI에 probe를 몰래 덧붙이지 않는다.
probe가 없는 이전 설치본은 unavailable로 표시하고 새 진단을 합성하지 않는다.
runtime/profile 불일치는 현재 source로 다시 판정하며 상태/설정 DB를 추가하지 않는다.

독립 reviewer는 source별 필드 추출, `Exception` 범위, 실제 SDK type 주입, optional import,
정상 status의 보존, secret noninterference를 확인한다. 최종 head의 요구/fixture/CI와 리뷰를 연결한다.
끝조건은 NC 계약의 D 통과·회귀·필수 리뷰 및 O의 별도 상태 기록이다. 실제 진단 양성 O가 없으면
packet의 운영 자격은 남는다. 다음 선택은 NC §2.4.5로만 판단하며 질문을 자동 생성하지 않는다.
