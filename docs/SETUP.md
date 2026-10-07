# ItDA 환경 재현 가이드 (팀원용)

이 레포만 받으면 같은 환경(NemoClaw + OpenShell 샌드박스, 정책, L40S 로컬 Nemotron Nano, 데모 UI)을 그대로 다시 만들 수 있다.

## 0. 준비물

| 항목 | 조건 | 확인 명령 |
|---|---|---|
| Linux GPU 서버 | Ubuntu 22.04/24.04, NVIDIA GPU (L40S 기준 46GB) | `nvidia-smi` |
| 커널 | **6.2 이상** (OpenShell Landlock ABI 3+) | `uname -r` |
| Docker | **28 이상** | `docker version` |
| sudo 권한 | 커널·Docker 업그레이드, linger 설정용 | `sudo -n true` |
| build.nvidia.com API 키 | `nvapi-...` | https://build.nvidia.com/settings/api-keys |

커널이 5.x면 먼저 올리고 재부팅한다(Ubuntu 22.04):

```bash
sudo apt-get update && sudo apt-get install -y linux-generic-hwe-22.04 docker-ce docker-ce-cli containerd.io && sudo reboot
```

## 1. 레포와 키

```bash
git clone https://github.com/coldtype-08/itda.git ~/itda && cd ~/itda
cp .env.example ~/.itda.env && chmod 600 ~/.itda.env && nano ~/.itda.env   # NVIDIA_API_KEY 필수, 나머지 선택
```

키는 **레포가 아니라 `~/.itda.env`** 에만 둔다. 샌드박스에는 올라가지 않는다.

## 2. 한 번에 설치 + 검증

```bash
sh scripts/setup_server.sh          # 로컬 모델을 건너뛰려면 SKIP_NIM=1 sh scripts/setup_server.sh
```

스크립트가 하는 일 (다시 실행해도 안전):

1. 사전 점검: 커널 Landlock, Docker 버전, GPU
2. NemoClaw 비대화형 설치/온보딩: 샌드박스 `itda-hack`, **Restricted 단계, 선택 프리셋 없음**, Nemotron 3 Super
3. ItDA 전용 egress 프리셋 적용(`policy/presets/`), 넓은 기본 프리셋(local-inference, github, pypi 등) 제거
4. L40S에 Nemotron 3 Nano NIM 실행 (드라이버 < 580이면 `1.7.0` 이미지 자동 선택)
5. 챌린지 자료 받기 (`challenge/`)
6. 샌드박스 점검 + 공격 시연 실행

## 3. 실행

```bash
# 샌드박스 안에서 실제 실행 (외부 도구 + L40S Nano 사용)
ITDA_SANDBOX_TOOL_KEYS=1 ITDA_MODEL_SMALL=nvidia/nemotron-3-nano \
ITDA_SANDBOX_SMALL_BASE_URL=http://host.openshell.internal:8000/v1 sh scripts/sandbox_run.sh
python3 eval/run_eval.py out        # 연습 과제 채점
python3 eval/run_cases.py           # 변형 과제 채점 (호스트 실행)

# 데모 웹 UI + 공개 링크 (토큰 포함 링크가 출력됨)
sh scripts/web_up.sh                # 중지: sh scripts/web_up.sh stop
```

## 4. 정책 구성 (OpenShell)

| 파일 | 내용 |
|---|---|
| `policy/presets/itda-*.yaml` | 서비스별 최소 허용(호스트·메서드·경로·실행 파일 `/opt/venv/bin/python3`) |
| `policy/itda-hack.policy.yaml` | 실제 적용된 전체 정책 (`sh scripts/export_policy.sh`로 갱신) |

정책을 바꾼 뒤 적용:

```bash
nemo-deepagents itda-hack policy add --from-dir policy/presets/ --dry-run   # 미리보기
nemo-deepagents itda-hack policy add --from-dir policy/presets/ --yes
nemo-deepagents itda-hack policy list | grep "●"
```

## 5. 우리가 겪은 문제와 해결 (같은 증상이 나오면)

| 증상 | 원인 | 해결 |
|---|---|---|
| `landlock ABI: 1` | 커널 5.15 | HWE 커널 6.8로 업그레이드 + 재부팅 |
| 샌드박스에서 모든 외부 호출 403, 로그에 `binary '/opt/venv/bin/python3' not allowed` | 프리셋의 실행 파일 경로가 다름 | 프리셋 `binaries`를 `/opt/venv/bin/python3`로 (이미 반영됨) |
| NIM 컨테이너가 계속 재시작, `driver too old (12070)` | NIM 2.x는 CUDA 13(드라이버 580+) 필요 | `nemotron-3-nano:1.7.0` 사용 (스크립트가 자동 선택) |
| 호출이 40~70초씩 걸림 | Nemotron 3의 thinking 기본 활성 | 코드에서 `enable_thinking: false` 전송 (이미 반영됨, `ITDA_THINKING=1`로 복원) |
| `401 Unauthorized` | 새 터미널에 키 없음 | `~/.itda.env` 확인 (자동 로드됨) |
| `gh auth login -p` 오류 | Ubuntu 22.04의 gh가 2.4로 오래됨 | `gh auth login -h github.com -w` 후 `gh auth setup-git` |
| 온보딩에서 Space 대신 Enter를 눌러 인터넷 전체 허용(`personal_open_internet`)이 켜짐 | TUI 선택 실수, 실행 중에는 제거 불가 | `nemo-deepagents <이름> destroy --yes` 후 `setup_server.sh`(비대화형)로 재생성 |
