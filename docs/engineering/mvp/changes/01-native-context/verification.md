# P01 호출 문맥 진단 — 소스 검증

2026-10-19 · source candidate · 관련 작업: Issue #3 · 설치 수용 미완료

[spec revision 1](spec.md)의 reader 범위를 구현했다. `native_context`는 허용한 protocol,
request channel, form 선언, SDK profile만 표시한다. client 입력 경로와 caller task binding은
항상 unverified다. 실제 질문·답변·사람 identity·실행 권한을 인증하지 않는다.

## 증거와 한계

| 검증 | 관측 결과 |
| --- | --- |
| 의미 있는 RED | 기존 status에 native_context가 없어 새 요구 assertion이 실패함 |
| pure/실제 SDK profile | `test_native_capabilities.py` 10개 PASS; 6개 독립 JSON expected 포함 |
| SDK 통합 | `test_mcp.py` 10개 PASS; 모델 입력 schema, structured/text 결과와 실제 stdio 왕복 포함 |
| 인접 회귀 | 위 두 suite와 operations/operation boundary/integration/control을 합쳐 127개 PASS |
| 독립 검토 | SDK Context export가 없을 때 기존 서버까지 실패하는 문제 수정; 회귀 PASS; 최종 scoped 검토에서 추가 P1/P2 없음 |
| 기존 설치본 read | 기존 status 도달만 관측. 새 native_context가 없어 candidate 진단의 실제 관측으로 세지 않음 |
| candidate 설치 read | NOT RUN; 검토 코드에 대응되는 설치 runtime에서 별도 확인 필요 |


검증 환경은 Python 3.12와 repository pin의 `mcp==2.3.0`, `mcp-types==2.3.0`이다.
기존 변경을 보존한 격리 검증 checkout에서 실행했다. CI의 Python 3.11/3.14.2 결과를
대체하지 않는다. 원격 CI, merge, 설치·재시작 및 원격 Codex 종단 수용은 이 기록의 PASS가 아니다.

진단 실패는 원래 projects/runtime/controls와 controller 오류 의미를 유지한다. SDK 타입·판본
불일치나 지원하지 않는 protocol은 unknown이다. request 원본, headers, metadata, credential을
출력·해시·저장하지 않는다. 합성 canary와 무관한 대형 metadata 교체는 결과를 바꾸지 않았다.

## 검증한 내용의 식별

커밋되지 않은 candidate이므로 아래 source/test bytes를 명시한다. 전체 baseline의 CI나
다른 dirty 변경을 이번 구현의 독립 전달 증거로 올리지 않는다.

| 파일 | SHA-256 |
| --- | --- |
| `hydra_sdlc/mcp.py` | `060632e33eec4e936e97395fbdfe5bb0083f2733f41624c5ec3f7b7037242476` |
| `hydra_sdlc/native_context.py` | `05bc16495471f88a2d5f8fba68894f4b75e99e78b5cb5fd52fb4dfd1958ec22c` |
| `tests/test_mcp.py` | `a9ca77e757022b6990565d768ac31070128b8338bdf485b10d219b25db6e497c` |
| `tests/test_native_capabilities.py` | `4d2d03611a000395a79cedb544d2e072d5dc9fd329530adc2d8da632758c7119` |

## 다음 경계

현재 다섯 MCP 도구를 유지한다. 새 command surface나 자동 질문 복원을 노출하지 않는다.
기존 책임·설치 identity를 대조한 뒤 candidate status를 실제 native caller에서 읽어야 P01의
설치 read 수용을 끝낼 수 있다. 그 결과도 P04의 답변 원본/응답자, P06 결정 적용, P07 중단·
재개 지원의 대체 증거가 아니다.

## 전체 회귀 실행 — 2026-10-19

같은 source/test bytes로 전체 Python suite 903개를 실행했다. assertion failure는 없었고,
검증 checkout에서 기존 폰트 라이선스 파일 두 개를 빠뜨려 한 테스트의 두 subtest가 오류였다.
원본의 asset·license를 복원한 뒤 해당 `test_ci_whitespace.py` 13개를 다시 실행해 모두 PASS했다.
제품 코드나 검사 기준은 이 환경 보완 과정에서 변경하지 않았다. 전체 실행 중 source/test가
변하지 않았고 검증한 79개 파일의 hash가 작업본과 같음을 확인했다.

최종 집계는 878개 성공, 25개 조건부 미실행이다. 미실행 이유는 optional Codex SDK 미설치 5개,
Linux subreaper·`/proc` 전용 18개, 현재 filesystem이 non-UTF-8 이름을 거절하는 2개다.
이는 단일 전체 실행의 무오류 결과가 아니라 전체 실행과 해당 오류 suite 재실행을 합친 기록이다.
실제 GitHub CI·플랫폼 matrix·설치·원격 운영의 통과로 대체하지 않는다.

## P03 이후 후보 재대사 — 2026-10-19

기존 네 source/test 파일의 위 SHA-256은 그대로 일치한다. P03/P14를 포함한
base commit `7edc1085bb77fb0dc26b152d911966d9d74ef89b`의 Git archive에 P01의 명시한
source/test 네 개, JSON fixture 여섯 개, 이 검증 기록만 적용한 격리 후보를 검사했다.
별도로 남아 있는 SDLC skill 개정은 이번 P01 범위에서 제외했다.

Python 3.12.7, `mcp==2.3.0`, `mcp-types==2.3.0`을 실제 확인하고 다음 세 suite를 함께
실행했다. **30개 PASS, failure/error/skip 0개**, 0.938초, exit code 0이다.
SDK integration을 skip한 결과가 아니며 실제 stdio와 typed SDK Context, 다섯 도구의
schema/status 회귀, runtime identity 검증을 포함한다.

```sh
python -c 'import unittest; patterns=("test_native_capabilities.py","test_mcp.py","test_runtime_identity.py"); suite=unittest.TestSuite(unittest.defaultTestLoader.discover("tests",pattern=p) for p in patterns); result=unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(not result.wasSuccessful() or bool(result.skipped))'
```

검사한 197개 후보 파일은 실행 전후 hash가 모두 같았다. 실행 뒤에는 이 검증 문단만
추가했다. 기존 전체 회귀 및 환경 복구 기록은 위의 역사적 결과로 유지하며, 이번 30개
검사를 새 전체 회귀라고 표현하지 않는다. 다음 여섯 fixture bytes를 함께 고정한다.

| `tests/fixtures/mvp/native-context-v1/` 파일 | SHA-256 |
| --- | --- |
| `ambiguous.json` | `1025377814b8b4416fc8f5582909a9f4fbcb4477e0f9726ec89bf80585a7fee8` |
| `legacy-form.json` | `666f48be5d4e3460b8a4273d039aa47dc575a94c90002e7add1afdf2ca2c3b58` |
| `modern-input.json` | `b7dd089edece240c393f192eea217e3a5af625b5e8ba3da8d2bdf34ee9dc18dd` |
| `no-context.json` | `77168e045c118238ce641e8d2d80ce0485a015a7663362d9d15764e7a7613861` |
| `no-declaration.json` | `0930f4279a9e62932cf44c9f55575430b434e269323a817f2b53dc8a7dba48fc` |
| `url-only.json` | `92b0f12ba7bf4b267a95dc2da917b23c37ab0c7a1e30894aff9c67d45611d0b2` |

현재 source와 fixture의 독립 검토는 진단의 권한 비승격·optional SDK 호환·공개 경계를
확인한다. 원격 CI·보호 전달·candidate 설치 read·원격 Codex 관측은 아직 NOT RUN이다.
로컬 SDK stdio 성공으로 실제 설치된 reader capability나 native 제어를 완료 처리하지 않는다.


## Protected-main candidate — 2026-10-20

P03의 protected merge와 main CI가 통과한 `63b62ebe7c0ed2c7f4a70e1839a179bebe36cbf9`
(tree `1c052675fe4520c6e0b586169b5564e8446e7a4a`)에서 기존 P01 source/test 네 파일과
JSON fixture 여섯 파일을 그대로 재사용했다. 기존 구현을 새로 작성하거나 schema·허용 범위를
넓히지 않았다. 해당 target의 main bytes가 기존 구현 전 base와 같고, 수용 spec revision 1과
NC 계약의 hash가 유지되는지 확인했다. P03/P02 및 CI·제어·실행 감독 파일은 현재 main 그대로다.

Python 3.12.7 / mcp 2.3.0 / mcp-types 2.3.0의 실제 SDK로 같은 세 suite를 실행했다.
**30 PASS, failure/error/skip 0**, 0.985초, exit 0이다. 후보·기존 제품 checkout·
Git HEAD/index·별도 skill 변경은 실행 전후 불변이다. 이 문단은 검증 뒤 관측 결과만 추가했다.

기존 source bytes의 독립 검토를 재사용하며 현재 PR의 exact-head hosted code/security review와
전체 CI는 별도 전달 조건이다. 이 실행은 local SDK/stdio 통합이며 설치 후보의 실제 원격
Codex read, caller 인증, 질문/답변·Pause/Resume·재시작 수용을 완료 처리하지 않는다.


## Actual installed native read — 2026-10-20

검토·merge·네 main CI를 통과한 `822d86c3197a5b6278d3496f4b5cf69ed41c8d67`의
비편집 설치본을 실제 native Codex 연결에서 읽었다. `hydra_status`의 package code 지문과
현재 설정/control binding 지문이 독립 설치 관측과 일치했다. 원본 경로·host 값·native ID는
공개 기록에 포함하지 않는다.

관측된 protocol은 `2025-06-18`, request channel은 available, form elicitation은 declared,
SDK InputRequired는 present다. client InputRequired와 caller task binding은 unverified다.
P01의 최소 실제 설치 read를 검증한 것이며 새 command 권한·답변 origin/귀속·native 실행 종료·
질문→Pause→답변→재시작→명시적 Resume 전체 흐름의 성공 증거로 확장하지 않는다.
