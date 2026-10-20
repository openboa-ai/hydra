# P05 내부 checkpoint-only core 검증

이 기록은 P05 revision 2 / CP revision 7 / EX revision 7의 **첫 내부 구현 단계**다.
수용 설계 기준은 `ad9d6382465023b9aa11e8f662c2d6d906216e10`, 구현 시작 기준은
`3e53b30472d4ba5120f3207025d05c29530fb6c7`이다. 아래 결과는 source와 격리 fixture 증거이며
공개 MCP 도구, 설치 runtime, 원격 native 종료, production 운영, CI/merge 증거가 아니다.

## 의미 있는 RED와 수정

| 사건 | 관측한 실패 | 수정 후 oracle |
| --- | --- | --- |
| legacy retirement 순서 | ticket release 시 `checkpoint != implementation_done`; 기존 native 34개는 PASS | 원 phase/head/pending_action 전체 확인 후 retirement와 ticket release |
| policy 관측 중 grant 철회 | 이전 grant로 progress가 `checkpoint`로 변경됨 | policy 다음 현재 grant/runtime 재검사; 새 효과 0 |
| spec-only correction + 코드 변경 | 진단 next_action이 reconcile로 남음 | scoped spec 이외 변경을 진단하고 다음 단계 실행 0 |
| 과거 accepted-spec 사유가 남은 완료 ACK 유실 | 재시도가 checkpoint_head_unknown으로 막힘 | 현재 exact phase/next/resume 의미로 완료를 확인하고 재커밋 0 |
| accepted-spec 중간 ACK 유실 + 범위 밖 파일 | 재시도에서 scope 진단 없이 retire | 중간 spec record를 완료로 추정하지 않고 scope/budget 재검사 |
| accepted anchor의 spec-only decision | spec_scope_unknown이 accepted_spec_changed로 덮임 | product_decision과 scope 진단/attempt 3을 함께 보존; 중간 ACK 유실 재시도도 동일 |
| accepted anchor의 빈/삭제된 spec | revised 분기가 원 artifact 검사를 생략 | 공유 effect-free 원 design validation으로 diagnose_spec_artifact 보존 |

최초 순서 oracle은 import/tool 미등록 오류가 아니라 실제 legacy checkpoint 경로의 assertion FAIL이다.
후속 검토 finding도 각각 현재 구현에서 assertion FAIL을 먼저 관측한 뒤 수정했다.
fixture 기대값 두 건(기존 correction reason, restart 후 spec 재검토)과 accepted-anchor를 빠뜨린
초기 decision fixture는 실제 기존 의미에 맞게 고쳤으며 구현 RED로 세지 않는다.

## 검증한 효과와 복구

- design/implementation/correction, spec-only correction 우선순위, product_decision 보존,
  scope/spec 진단, 원래 correction attempt/expected head/resume 의미.
- private summary canary가 reply/progress/public effect에 없고, broad candidate callback·correction·
  verification·다음 assignment·delivery를 호출하지 않음. 하위 workspace 효과도 고정 ceiling으로 거절.
- 현재 operation grant, numeric target, exact spec revision, runtime/config/controller binding,
  admission revision을 검증. Pause→Resume ABA와 효과 사이 grant/config 변경도 소유권을 보존하며 중단.
- bridge/native binding 구분, parser의 bool ID·비정규 UUID·Unicode surrogate·summary 한도·
  caller authority/effect_limit·effect key 오류, failed/review phase 거절.
- 독립 종료 증거가 없거나 stale/partial/다른 target/다른 control인 stopped 요청은 효과 0.
  종료 관측 중 grant/config 변경도 다시 검증. 정상 stopped fixture는 독립 synthetic proof이며
  실제 Codex turn/descendant 종료 adapter qualification을 뜻하지 않는다.
- 실제 owned Git에서 final record ACK 유실 후 새 controller가 원본을 대사하고 checkpoint/helper 0,
  Git commit 1개를 유지. 별도 명시적 advance는 새 검토 assignment를 선택할 수 있음.
- 실제 Git commit 직후 ACK가 유실된 경우 candidate 재시도는 소유권·동일 HEAD·동일 bytes를 보존한
  reconcile 대기. 독립 종료 proof를 받은 stopped recovery만 동일 commit과 product_decision 맥락을
  보존해 정리하며 추가 commit은 없음.
- final write/readback·retirement ACK·ticket release 실패는 receipt를 만들지 않음. retirement로
  attribution이 사라진 old request는 unknown이며 process-local consumed가 영속 성공 증거가 아님.
- GitHub progress_source는 인증된 실제 comment ID와 기존 metadata validation을 사용.
  다른 author/metadata/잘못된 locator와 stale final readback은 성공으로 채택하지 않음.

## 실행 기록

Python 3.12의 격리 storage wrapper에서 다음 selector를 실행했다. 외부 provider는 제어된 fixture이며,
실제 local file lock, coordinator ticket, Git repository/commit은 임시 owned 경로를 사용했다.

```sh
python -m unittest discover -s tests -p 'test_checkpoint_only.py' -v
```

관련 회귀 selector는 `test_checkpoint_only.py`, `test_native*.py`,
`test_checkpoint_continuation.py`, `test_control_commands.py`, `test_github.py`,
`test_admission_cas.py`, `test_operation*.py`를 합친다.

| 판본 시점 | 결과 |
| --- | --- |
| 초기 core + 기존 회귀 | 240개 PASS / skip 0 / 40.459s — 후속 review 수정 전 역사적 증거 |
| 4개 review 수정 + 실제 Git recovery | 251개 PASS / skip 0 / 47.407s — decision scope debt 마지막 수정 전 역사적 증거 |
| decision scope debt 수정 | 해당 2개 oracle PASS / skip 0 / 0.121s |
| decision scope debt 수정 뒤 관련 회귀 | 253개 PASS / skip 0 / 47.297s — 공유 artifact validation 추출 전 역사적 증거 |
| 빈/삭제 spec 검증 수정 | 해당 2개 oracle PASS / skip 0 / 0.110s |
| 최종 관련 회귀 | 256개 PASS / skip 0 / 47.549s |

최종 selector에는 새 checkpoint-only 35개, 기존 native/continuation/admission/GitHub/operation 회귀가 포함된다.
`git diff --check`도 PASS다. 마지막 상태는 코드/테스트 8개 파일과 이 spec/evidence 2개 파일이며
관련 없는 작업 중 변경은 포함하지 않는다. 전체 suite는 통합자가 이 정확한 overlay를 시작 기준에
적용한 격리 snapshot에서 한 번 실행했다. 최종 결과는 아래에 기록한다.

## 최종 통합 검증

시작 기준 `3e53b30472d4ba5120f3207025d05c29530fb6c7`의 Git archive에 검토한 10개 파일만
적용한 격리 snapshot에서 `python -m unittest discover -s tests`를 실행했다.
Python 3.12.7과 실제 설치된 `mcp==2.3.0`, `mcp-types==2.3.0`을 확인했다.

- 전체 1,024개 수집·실행: 999개 PASS, 25개 skip, failure/error 0; 278.030s, exit 0.
- 실행 전후 snapshot 199개 파일의 bytes가 동일했다. 관련 없는 skill 변경은 포함하지 않았다.
- 최종 5개 production source의 정확한 SHA-256을 대조한 독립 코드·보안 검토에 남은 material
  finding이 없었다. spec §7의 내부 단계 한계도 검토했다.
- 이후 수정은 이 검증 결과를 기록하는 문서 변경뿐이며 source/test bytes는 유지했다.

이 결과는 전체 suite의 skip을 통과로 세지 않으며, public MCP 등록·실제 native 연동·원격 CI·
protected merge 또는 main의 성공 증거로 사용하지 않는다.

## 남은 통합 경계

공개 `hydra_command_v1` MCP 등록과 실제 transport authority/종료 증거 adapter, MCP SDK 왕복,
원격 Codex에서의 질문→응답→checkpoint 수용은 이 내부 단계에서 NOT RUN이다.
P05 전체 완료를 주장하지 않는다. 최종 독립 review, exact isolated 전체 회귀, CI/merge는
각기 다른 증거다. 위 독립 review와 전체 회귀는 이 내부 source 단계에 한정하며 CI/merge는
아직 NOT RUN이다. 기존 다섯 MCP 도구의 입력/동작은 수정하지 않았다.

## 현재 admission·work-source 기준의 첫 단계 통합 준비

위 실행 결과는 각각 명시한 이전 구현 기준의 역사적 증거다. P02의 수정된 admission
관측·CAS와 P03의 현재 정책·배정 종료 경계에 첫 checkpoint-only 단계를 다시 연결하는
후보는 **정적 준비 상태이며 실행 NOT RUN**이다. 기존 결과를 새 조합의 통과로 세지 않는다.

- 미래 command version/action/operation의 본문은 해석하지 않는다. 현재 admission의
  실제 locked 관측 시각, 불확실한 replace 결과, config 뒤 마지막 권한 갱신을 보존한다.
- 원 단계 완료 후 기존 고정 retirement helper를 좁은 내부 checkpoint mode로 재사용한다.
  현재 정책과 권한은 admission guard 전에 읽고, exact 원 배정 확인·최종 progress-only
  기록·원본 read-back·ticket release·consumed 순서는 같은 guard 안에서 유지한다.
- 기존 세 retirement 호출의 기본 동작, 현재 work-source 정책과 완료 후처리의 보호 경계를
  유지한다. checkpoint mode에서 generic retirement callback이나 legacy fallback은 허용하지 않는다.
- 미래 opaque 본문, config 관측 중 권한 철회/조회 실패, 원 ticket 변경, retirement 직전
  철회와 동일 marker 재발견 후 진전의 추가 oracle을 준비했다. 실제 수집·실행 결과는 아직 없다.

이 준비에는 MCP 여섯 번째 도구, raw stdio, 증거 export, 결정 적용, continuation,
native 종료 adapter 또는 권한 활성화가 포함되지 않는다. 통합 기준의 최종 판본을 다시
확인하고 독립 검토와 허용된 격리 검증을 마친 뒤 실제 결과를 별도로 기록한다.


## Verified-main integration — 2026-10-20

P01/P02/P03의 protected delivery와 모든 main CI가 통과한
`822d86c3197a5b6278d3496f4b5cf69ed41c8d67` (tree `1e3a168d17cb3130b28e46fb02fbc9faf291f81d`)에서 P05 revision 2 / CP revision 7 /
EX revision 7의 내부 core를 통합했다. 기존 수용 명세의 SHA-256을 고정했고, 원 구현을
재작성하지 않고 준비한 변경을 현재 main에 병합했다. 현재 P03의 독립 read client,
절대 deadline·관측 supervisor·Stop 보존과 P02의 parser/CAS/현재 권한 재검사를 유지한다.

내부 checkpoint는 original phase의 완료/대기를 원본 progress에서 확인한 뒤 matching
assignment를 회수한다. 고정된 효과 제한은 progress 기록과 owned checkpoint만 허용하며
검증·새 배정·전달로 이어지지 않는다. 기존 retirement helper를 재사용하고 remote policy
관측은 admission guard 밖에, 원 ticket 검사·진짜 comment read-back·회수는 같은 guard 안에 둔다.

Python 3.12.7 / mcp 2.3.0 / mcp-types 2.3.0에서 변경 동작과 영향 회귀
**424개 실행, 424 PASS, 0 skip, failure/error 0**,
76.221초, exit 0이다. checkpoint-only 42개를 실제 수집했으며 중복 수집은 없다.
현재 config 관측 중 철회·unknown body 불투명성·ticket 변경·회수 직전 철회와 재시도·
generic retirement 우회 금지를 포함한다. 실제 임시 Git의 ACK 유실/재시작과 독립 명시적
continue 양성 사례, 기존 native/operation/source-policy/MCP 진단 회귀를 함께 실행했다.

격리 후보와 기존 checkout·HEAD·index·별도 skill 변경은 보존했다. 전체 후보 검사는
현재 PR의 hosted CI에서 실행하고 독립 code/security review와 protected merge/main 확인은
별도 전달 조건이다. 이 내부 단계는 새 MCP 도구를 등록하거나 transport 권한을 부여하지
않는다. 실제 원격 Pause/Resume·종료 증거 adapter·질문/답변 수용은 여전히 미검증이다.


## Hosted review corrections — 2026-10-20

PR #14의 최초 head `316eac5603d4165a02a2caf8dd888ab6b8c170f3`는 전체 hosted CI 네 항목과
security review를 통과했다. 이어진 code review의 세 P2 finding을 실제 동작으로 재현했다.
수용 P05 revision 2의 입력/실패/현재 intake 경계 내 수정이며 권한·제품 범위는 바꾸지 않는다.

| 사건 | 기존 head의 RED | 수정한 결과 |
| --- | --- | --- |
| 미지원 version/action/operation의 미래 body | 정상 공통 identity가 있어도 null/list/string body를 현재 schema 오류로 처리 | 안전한 공통 target/identity를 유지하고 미지원 body의 구조 검사·복사를 생략; rejected/unsupported_operation, 효과 0 |
| review phase에 checkpoint 요청 | unsupported_phase를 waiting/reconcile로 반환 | rejected/open_source로 종료; receipt·회수·후속 실행 0 |
| scoped spec 확인 뒤 Issue 수정 | 변경된 새 Issue를 재검증하지 않고 design_done/회수 성공 | 사용 직전 같은 intake digest를 확인하고 변경되면 intake_changed; owned spec/head/ticket 보존 |

네 회귀 selector에서 **9개 assertion 실패, error/skip 0**를 원래 source 그대로 관측했다.
수정 후 같은 사례를 포함한 변경 영향 회귀는 **427 PASS, failure/error/skip 0**다.
checkpoint-only 실제 수집은 44개이며 기존 정상 design 완료, future body 불투명성,
권한 철회·ACK 유실·재시작·legacy/MCP 동작도 유지했다.

격리 source bytes와 기존 checkout·HEAD·index·별도 skill 변경을 보존했다. 이 문단만 검증 뒤
추가했다. 새 head의 hosted CI·code/security review와 protected merge/main 확인은 별도 조건이다.
실제 원격 질문/답변·Pause/Resume 및 설치 native 권한 수용을 완료로 세지 않는다.
