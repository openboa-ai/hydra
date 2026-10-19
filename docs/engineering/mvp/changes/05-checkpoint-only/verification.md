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
