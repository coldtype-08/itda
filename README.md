# ItDA (잇다) — 흩어진 기록을 내 여행으로 잇는 에이전트

서로 다른 시점·관점의 자료(공지, 현장조사, 홍보물, 블로그, 광고, 외부 메모)를 스스로 분류·검증해
방문객 유형(외국인/한국인)과 관심사(가족/역사/K-컬처)에 맞는 문화 코스 **초안**을 만드는 에이전트.
NVIDIA Nemotron(NIM 엔드포인트) + NemoClaw + OpenShell 위에서 동작한다.

## 구조

```
TASK + 렌즈 ──▶ ① 수집(PathGuard: input/만) ──▶ ② 분류(문서별, 병렬)
              ──▶ ③ 검증(최신성·출처 신뢰도·동명이인·불확실성) ──▶ ④ 종합(렌즈별 초안)
              ──▶ output/ (course_draft.md · itda_result.json · audit.json)
```

- 에이전트에는 **행동 도구가 없다.** 예약·발송·결제·게시는 구조적으로 불가능하며 `approvals_needed`로만 출력한다.
- 문서 안의 지시문은 데이터로 취급하고 따르지 않는다(`untrusted_instructions`로 보고).
- 외부 패키지 없이 Python 표준 라이브러리만 사용 → 패키지 저장소가 막힌 샌드박스에서도 실행된다.

## 설치 및 실행

```bash
# 0) 챌린지 자료 받기 (./challenge, 커밋하지 않음)
sh scripts/fetch_challenge.sh

# 1) 호스트에서 바로 (build.nvidia.com 키 필요)
export NVIDIA_API_KEY=...            # 커밋 금지
python3 -m itda --visitor foreign --interests history,family
python3 eval/run_eval.py              # 연습 과제 함정 체크리스트
python3 -m itda.web                   # 데모 UI (http://<host>:8501)

# 2) OpenShell 샌드박스 안에서 (키는 게이트웨이에만 존재)
SANDBOX=itda-hack sh scripts/sandbox_run.sh --visitor foreign --interests history,family

# 3) 보안 시연 (샌드박스 안에서만 실행됨)
openshell sandbox exec -n itda-hack -- sh /sandbox/itda/attacks/run_attacks.sh
```

옵션: `--visitor foreign|korean`, `--interests history,family,kculture`, `--lang en|ko`, `--visit-date`, `--mock`(LLM 없이 배선 점검).
환경변수: `ITDA_LLM_BASE_URL`, `ITDA_MODEL`, `ITDA_MODEL_FAST`, `ITDA_CONCURRENCY`.

## 데모 확인 방법

TODO(데모 담당): 데모 URL 또는 단계별 확인 방법

## OpenShell policy

- 정책 파일: [`policy/itda-hack.policy.yaml`](policy/itda-hack.policy.yaml) (`openshell policy get itda-hack --full`로 추출한 실제 적용본)
- 샌드박스 생성: NemoClaw `onboard`, 정책 단계 **Restricted**, 프리셋 전부 제거(github·pypi 포함)

### 주요 권한 설계와 이유

| 권한 | 설정 | 이유 |
|---|---|---|
| 네트워크 egress | 허용 목록 없음 (기본 거부) | 자료 속 "외부 업로드" 지시(prompt injection)가 실행돼도 나갈 곳이 없게 |
| 모델 추론 | `inference.local` 라우팅만 | API 키는 호스트 게이트웨이에만 보관, 샌드박스에는 키가 없음 |
| 파일 읽기 | 업로드한 `TASK.md`, `input/`만 존재 | `restricted/`, `secrets/`는 샌드박스에 올리지 않음 (데이터 최소화) |
| 시스템 경로 | `/usr`, `/etc` 등 읽기 전용, 그 외 Landlock으로 차단 | 변조·권한 상승 방지 |
| 프로세스 | `sandbox` 사용자, root 불가 | 권한 상승 방지 |
| 애플리케이션 계층 | `PathGuard`: 허용 루트 밖, `restricted`/`secrets`/심볼릭 링크 우회 차단 + 감사 로그 | OpenShell과 이중 방어 |
| 행동 | 발송·예약·결제 도구 없음 | `approval: draft_only` 준수 |

## 외부 API / 서비스

| 서비스 | 용도 | 허용 범위 |
|---|---|---|
| NVIDIA build.nvidia.com (NIM 엔드포인트) | Nemotron 3 Super/Ultra 추론 | `POST /v1/chat/completions`, OpenShell 게이트웨이 경유 |
| (선택) L40S 로컬 NIM | 개인정보가 포함된 단계의 로컬 추론 | `host.openshell.internal:8000` 한정 |
