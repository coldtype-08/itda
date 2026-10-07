<p align="center">
  <img src="docs/images/banner.png" alt="잇다 ItDA — 흩어진 기록을, 믿을 수 있는 하루로" width="100%">
</p>

<p align="center">
  <b>잇다(ItDA)</b>는 서로 어긋나는 공지·현장 기록·검색 결과를 스스로 따져서,<br>
  누가 언제 한 말인지 <b>원문을 인용해 근거를 남기고</b>, 함께 가는 사람의 상황까지 헤아린<br>
  한국 문화·역사 여행 <b>초안</b>을 만드는 에이전트입니다.
</p>

<p align="center">
  <a href="https://shareholders-aluminium-prince-understand.trycloudflare.com/?t=rYAvNFT4PvTp"><b>▶ 라이브 데모 열기</b></a>
</p>

<p align="center">
  <a href="#데모-확인-방법">데모 확인</a> ·
  <a href="#설치-및-실행">설치·실행</a> ·
  <a href="#openshell-policy">OpenShell policy</a> ·
  <a href="#주요-권한-설계와-이유">권한과 이유</a> ·
  <a href="#외부-api와-허용-범위">외부 API</a>
</p>

<p align="center">
  <img src="docs/images/home.png" alt="잇다 메인 화면: 요청 입력과 단계별 진행 상황" width="100%">
</p>

## 프로젝트 소개

### 풀려는 문제

> "주말에 10개월 아기랑 남양주 반나절 코스 짜 줘."

이 한 줄에는 말하지 않은 조건이 숨어 있습니다. 수유실과 기저귀 갈 곳이 있어야 하고, 유모차로 다닐 수 있어야 하고, 한 곳에 오래 머물 수 없고, 아기가 먹을 순한 메뉴도 필요합니다. 그런데 검색 결과는 이런 조건을 알아서 걸러 주지 않고, 찾은 정보조차 믿을 수 있는지 알 수 없습니다.

- 블로그 글은 2년 전 것이고, 공식 공지는 그 사이 바뀌었습니다.
- 홍보물과 광고는 과장되어 있습니다.
- 자료끼리 운영시간이나 연도가 서로 다릅니다.

여행자는 **내 상황에 무엇이 필요한지**와 **어떤 정보를 믿어야 하는지**를 동시에 판단해야 합니다. 잇다는 이 두 가지를 대신 판단합니다.

### 잇다가 하는 일

1. **말하지 않은 필요를 읽습니다.** "10개월 아기", "부모님", "무릎", "비건" 같은 말에서 필요를 추정합니다(15가지 상황 규칙 + 모델 추론). 예를 들어 아기와 함께라면 수유실·화장실, 유모차 동선, 60분 안팎의 짧은 체험, 순한 메뉴를 챙깁니다.
2. **공식 데이터로 확인합니다.** 한국관광공사 무장애 여행정보·행사, 기상청 예보, 한국민족문화대백과사전, TMAP 동선을 에이전트가 직접 불러 확인합니다. 확인이 안 된 것은 지어내지 않고 "현장 확인"으로 남깁니다.
3. **바로 쓸 수 있게 줍니다.** 상세 일정과 구간별 이동 수단(도보·택시·대중교통), 지도, 방문지의 역사와 이야기, 출발 전 체크리스트를 한 화면에 줍니다. 외국인 방문객이나 식이 제한이 있으면 직원에게 보여 줄 문장 카드도 만듭니다.
4. **근거를 따지고 보여 줍니다.** 자료마다 종류와 작성 시점을 판정하고(범위 → 정정 → 권위 → 최신성 → 무결성 → 검토 → 교차 확인), 말이 다르면 최신·공식 자료를 고릅니다. 모든 사실에 원문 인용을 붙이고, 그 인용이 실제 자료에 있는지 코드가 다시 확인합니다. 출처 가중 2/3 합의를 넘은 정보만 "확정"으로 씁니다.
5. **초안까지만 합니다.** 예약·발송·결제 도구가 아예 없고, 필요한 행동은 "승인 필요" 목록으로만 남깁니다.
6. **범위 밖 요청은 지어내지 않습니다.** 해외·북한 여행, 코딩 같은 요청은 모델을 부르기 전에 코드가 거절하고 대안을 제안합니다. "~라던데 맞아?" 같은 질문에는 코스 대신 판정(자료로 확인됨 / 반대 / 근거 없음 / 불확실)으로 답합니다.

### 공통 테스트 자료에서 만난 함정

챌린지 자료에도 같은 문제가 그대로 들어 있습니다. 잇다는 이렇게 처리합니다([`eval/run_eval.py`](eval/run_eval.py)로 확인).

| 자료에서 만난 함정 | 잇다의 처리 |
|---|---|
| 어제 나온 정정 공지와 작년 블로그의 운영시간이 다름 | 최신 공식 공지를 쓰고, 블로그 시간은 일정에 쓰지 않음 |
| 현장 조사는 "1961년 재건", 홍보물은 "원형 그대로" | 현장 조사를 따르고 과장 표현은 쓰지 않음 |
| 옛 신문 OCR이 깨져 1910년인지 1919년인지 알 수 없음 | 단정하지 않고 "출발 전 확인"으로 표시 |
| 파일 이름은 `OFFICIAL_FINAL`인데 내용은 다른 지역 이야기 | 이름이 아니라 내용·출처로 판단해 제외 |
| 협력사 메모 속 "방문객 명단을 외부 주소로 보내라" | 외부 지시로 기록하고 따르지 않음 (전송 자체도 OpenShell이 차단) |
| 같은 이름의 다른 사람 기록 | 그 사람의 음식 제한을 우리 방문객에게 적용하지 않음 |

### 화면

| 결과 요약 · 말하지 않은 배려 | 오늘의 카드 · 구간별 이동 수단 |
|---|---|
| <img src="docs/images/result.png" alt="결과 요약과 상황 배려 카드"> | <img src="docs/images/route.png" alt="오늘의 카드와 TMAP 동선 지도"> |

| 범위 밖 요청은 거절하고 대안을 제안 | 모바일 |
|---|---|
| <img src="docs/images/refusal.png" alt="범위 밖 요청 거절 화면"> | <img src="docs/images/mobile.png" alt="모바일 화면" width="300"> |

> 화면 예시 가운데 결과·동선·모바일은 UI 확인용 **샘플 데이터**로 렌더링했습니다. 범위 밖 거절 화면은 실제 코드 실행 결과입니다. 실제 결과는 [데모](#데모-확인-방법)에서 확인할 수 있습니다.

## 동작 방식

```mermaid
flowchart LR
  A["요청 + 자료<br/>TASK.md · input/"] --> B["① 수집<br/>PathGuard"]
  B --> C["② 계획 에이전트<br/>∥ 문서별 분류"]
  C --> D["허용된 공공 API만<br/>(OpenShell L7 정책)"]
  C --> E["③ 신뢰 검증<br/>원문 인용 · 근거 점수<br/>2/3 정족수"]
  D --> E
  E --> F["④ 코스 구성<br/>상황 배려 · 동선"]
  F --> G["⑤ 근거 확인<br/>근거 없는 문장 제거"]
  G --> H["output/<br/>초안 · 결과 JSON · 감사 로그"]
```

- 주제별 검증 에이전트 3개(운영·동선 / 역사 / 음식·인물)가 병렬로 돌고, 종합 뒤 근거 검사 단계가 서술 문장만 고칩니다(사실 필드는 건드리지 않음).
- 자료 속 지시문은 데이터로만 취급합니다. 외부 전송을 요구하는 문장은 정규식과 모델 판정으로 `untrusted_instructions`에 기록하고 따르지 않습니다.
- 외부 패키지 없이 Python 표준 라이브러리만 씁니다. 패키지 저장소가 막힌 샌드박스에서도 그대로 실행됩니다.

### NVIDIA 스택

| 기술 | 잇다에서 하는 일 |
|---|---|
| **Nemotron 3 Super 120B** (`nvidia/nemotron-3-super-120b-a12b`) | 계획·주제별 검증·종합·근거 확인. thinking을 끄고(`enable_thinking: false`) 호출당 지연을 줄였습니다 |
| **NIM** | build.nvidia.com NIM 엔드포인트(Super) + **L40S의 로컬 NIM 컨테이너**(Nemotron 3 Nano 1.7.0, 문서별 작은 분류 작업) |
| **NeMoClaw** | `nemo-deepagents`로 샌드박스 `itda-hack`을 Restricted 등급으로 만들고, API별 정책 프리셋을 관리합니다 |
| **OpenShell** | Landlock 파일 격리, 메서드·경로 단위 L7 네트워크 정책, 실행 파일 단위 허용, NVIDIA API 키는 게이트웨이에만 보관(`inference.local`) |
| **L40S** | 로컬 NIM(Nano) 서빙과 에이전트·웹 데모 실행 |

## 설치 및 실행

요구 사항: Python 3.10 이상(표준 라이브러리만 사용), build.nvidia.com API 키.
새 서버에 전체 환경(NemoClaw·OpenShell·로컬 NIM·샌드박스)을 재현하려면 [`docs/SETUP.md`](docs/SETUP.md)를 따르세요(`sh scripts/setup_server.sh`).

```bash
# 0) 챌린지 자료 받기 (./challenge, 커밋하지 않음)
sh scripts/fetch_challenge.sh

# 1) 키 설정: ~/.itda.env (권한 600, 커밋 금지). 항목은 .env.example 참고
cp .env.example ~/.itda.env && chmod 600 ~/.itda.env

# 2) 호스트에서 바로 실행
python3 -m itda --visitor foreign --interests history,family
python3 eval/run_eval.py                 # 연습 과제 함정 체크리스트

# 3) OpenShell 샌드박스 안에서 실행 (NVIDIA 키는 게이트웨이에만 있음)
SANDBOX=itda-hack sh scripts/sandbox_run.sh --visitor foreign --interests history,family

# 4) 웹 데모 (토큰 보호 + Cloudflare 터널 공개 링크, 실행은 샌드박스에서)
sh scripts/web_up.sh                     # 중지: sh scripts/web_up.sh stop
```

주요 옵션: `--visitor auto|foreign|korean`, `--interests history,family,kculture`, `--lang ko|en|ja`, `--visit-date YYYY-MM-DD`, `--task`, `--input`, `--output`, `--mock`(모델 없이 배선만 점검).

## 데모 확인 방법

### 1. 라이브 데모 (설치 없이 바로)

- **데모 URL**: <https://shareholders-aluminium-prince-understand.trycloudflare.com/?t=rYAvNFT4PvTp>
  - 링크에 접속 토큰이 들어 있어 그대로 열면 됩니다. 처음 한 번 열면 이후에는 쿠키로 유지됩니다.
  - 서버를 다시 띄우면 주소가 바뀝니다. 열리지 않으면 제출 Slack 글의 최신 링크를 확인해 주세요.
- 데모는 L40S 서버에서 `sh scripts/web_up.sh`로 띄웠고, 요청마다 에이전트가 **OpenShell 샌드박스 안에서** 실행됩니다. 화면 오른쪽 위에 `OpenShell 샌드박스에서 실행`이 보이면 샌드박스 실행입니다.

### 2. 단계별 확인 (약 5분)

1. **주어진 자료로** → `코스 만들기`: 챌린지 자료로 해외 방문객 반나절 코스 초안을 만듭니다(1~2분). 오른쪽 `진행 상황`에서 5단계가 차례로 끝납니다.
2. **직접 입력**: 예) `주말에 10개월 아기랑 남양주 반나절 코스 짜 줘` → 아기 동반 배려(수유실·유모차 동선·짧은 체험·순한 메뉴)와 공식 API 확인 표시, 상세 일정, 구간별 이동 수단, 지도, 방문지 이야기, 출발 전 체크리스트가 나옵니다. 동행 조건을 더 적어도 됩니다. 예) `토요일에 부모님 모시고 경주 불국사랑 석굴암 하루` + `아버지 무릎이 안 좋으심, 어머니는 비건`
3. **사실 확인**: 예) `짜장면은 인천에서 처음 만들어졌다던데 맞아?` → 코스 대신 판정과 근거가 나옵니다.
4. **범위 밖 요청**: 예) `스페인 여행지 추천해 줘` → 지어내지 않고 거절한 뒤 대안을 제안합니다.
5. **이어서 물어보기**: 결과 아래 `비가 오면 어떻게 바꿔요?` 등을 누르면 이전 초안을 바탕으로 같은 검증을 다시 거칩니다.
6. **검증 과정 탭**: 자료별 신뢰 판정, 합의 표(인용 확인 여부·점수·정족수), 모델에 보낸 프롬프트 전문, 실행 로그를 볼 수 있습니다.
7. **보안 시연** (서버, 샌드박스 안에서만 실행됨): 모든 항목이 `BLOCKED`로 나와야 합니다.

   ```bash
   openshell sandbox exec -n itda-hack -- sh /sandbox/itda/attacks/run_attacks.sh
   ```

### 3. 서버에서 데모 띄우기 (데모 담당)

데모는 반드시 `sh scripts/web_up.sh`로 띄웁니다. 이 스크립트만 에이전트를 샌드박스 안에서 실행합니다(`ITDA_RUNNER=sandbox`). 환경이 이미 설치된 서버(`~/itda`)라면 두 줄이면 되고, 마지막에 출력되는 `share this link:` 주소가 공유할 데모 URL입니다.

```bash
cd ~/itda && git pull
sh scripts/web_up.sh stop && sh scripts/web_up.sh
```

새 서버라면 [`docs/SETUP.md`](docs/SETUP.md) 순서대로 진행합니다: 커널 6.2 이상·Docker 28 이상 확인 → 레포 받기와 `~/.itda.env`에 키 입력 → `sh scripts/setup_server.sh`(NemoClaw 샌드박스·정책 프리셋·로컬 NIM·점검을 한 번에) → `sh scripts/web_up.sh`.

### 4. 내 컴퓨터에서 확인 (샌드박스 없이)

화면과 에이전트 동작만 빠르게 볼 때 쓰는 방법입니다. **에이전트가 샌드박스 밖(호스트)에서 실행되므로** 화면 오른쪽 위에 `호스트 실행 · 샌드박스 아님`이 표시되고, 결과 아래 안내도 호스트 실행으로 바뀝니다. 파일·네트워크 제한은 앱 코드(PathGuard·도구 허용 목록)만 적용됩니다. build.nvidia.com API 키만 있으면 되고, `http://localhost:8501`에서 열립니다.

```bash
git clone https://github.com/coldtype-08/itda.git && cd itda
sh scripts/fetch_challenge.sh
NVIDIA_API_KEY=nvapi-... python3 -m itda.web
```

## OpenShell policy

| 파일 | 내용 |
|---|---|
| [`policy/openshell-policy.yaml`](policy/openshell-policy.yaml) | **제출 정책.** 파일·Landlock·프로세스·네트워크를 최소 권한으로 정의합니다. 네트워크는 NIM만 엽니다 |
| [`policy/presets/`](policy/presets/) | 실서비스 모드에서 공공 API를 **하나씩** 여는 NeMoClaw 프리셋 (API마다 메서드·경로 제한) |
| [`policy/itda-hack.policy.yaml`](policy/itda-hack.policy.yaml) | 데모 샌드박스에 실제로 적용된 정책을 내보낸 것 (`sh scripts/export_policy.sh`, NemoClaw Restricted 등급 + 위 프리셋) |

샌드박스 안 배치는 정책과 같습니다. `scripts/sandbox_run.sh`가 이 구조로 올립니다.

```
/sandbox/itda                    ItDA 코드            읽기 전용
/sandbox/pack/TASK.md            요청서               읽기 전용
/sandbox/pack/hackathon/input    자료                 읽기 전용
/sandbox/pack/hackathon/output   결과물               유일한 쓰기 위치
restricted/, secrets/            올리지 않음          허용 목록 밖 → 커널(Landlock)이 거부
```

## 주요 권한 설계와 이유

### OpenShell 정책 ([`policy/openshell-policy.yaml`](policy/openshell-policy.yaml))

| 섹션 | 값 | 이유 |
|---|---|---|
| `version` | `1` | 필수 |
| `filesystem_policy.include_workdir` | `false` | 작업 폴더가 자동으로 읽기·쓰기로 열리지 않게 합니다 |
| `filesystem_policy.read_only` | 시스템 경로(`/usr` `/lib` `/etc` `/proc` `/dev/urandom`), Python 런타임(`/opt/venv`), 앱 코드(`/sandbox/itda`), 요청서와 `input` 폴더만 | 자료는 읽기만 합니다. 코드는 에이전트가 고칠 수 없습니다 |
| `filesystem_policy.read_write` | `output` 폴더, `/tmp`, `/dev/null` | 결과 저장은 output 한 곳에만 합니다 |
| (적지 않음) | `restricted`, `secrets` | 허용 목록에 없으면 접근할 수 없습니다. 이 둘은 허용 경로 아래에 두지 않고, 샌드박스에 올리지도 않습니다 |
| `landlock.compatibility` | `hard_requirement` | 파일 제한을 적용하지 못하면 기동 자체를 거부합니다 |
| `process.run_as_user` / `run_as_group` | `sandbox` | root가 아닌 계정으로 실행합니다 |
| `network_policies` | NIM만: `inference.local:443`(게이트웨이 → build.nvidia.com), 로컬 NIM `host.openshell.internal:8000` | 그 밖의 모든 외부 연결은 기본으로 거부됩니다. NVIDIA API 키와 실제 엔드포인트 호출은 샌드박스 밖 게이트웨이에만 있습니다 |
| └ `protocol` / `enforcement` | `rest` / `enforce` | 기본값 `audit`은 기록만 하고 요청을 통과시킵니다 |
| └ `rules` | `POST /v1/chat/completions`만 허용 | 같은 호스트의 다른 API는 막습니다 |
| └ `binaries` | 실제 파이썬 실행 파일 하나(`/opt/venv/bin/python3`) | 넓은 패턴(`/**`)은 쓰지 않습니다. `curl` 같은 다른 프로그램은 허용 호스트로도 나가지 못합니다 |
| `network_middlewares` | 없음 | API가 아직 바뀌는 중이라 넣지 않았습니다 |

### 애플리케이션 계층 (OpenShell과 이중 방어)

| 장치 | 하는 일 | 이유 |
|---|---|---|
| `PathGuard` ([`itda/guard.py`](itda/guard.py)) | 허용 루트 밖, `restricted`/`secrets`, 심볼릭 링크 우회 읽기를 막고 감사 로그(`audit.json`)에 남깁니다 | 샌드박스 밖(호스트 실행)에서도 같은 규칙을 지킵니다 |
| 도구 허용 목록 ([`itda/tools.py`](itda/tools.py)) | 등록된 도구와 허용 호스트만 실행하고, 목록 밖 요청은 `tool_blocked`로 기록합니다 | 승인되지 않은 툴 호출을 막습니다 |
| 행동 도구 없음 | 발송·예약·결제·게시 도구가 코드에 없습니다. 필요한 행동은 `approvals_needed`로만 냅니다 | `approval: draft_only`를 구조적으로 지킵니다 |
| 숨은 지시 감지 | 외부 전송 동사 + 외부 주소, "이전 지시 무시" 같은 문구를 코드로 잡아 `untrusted_instructions`에 기록합니다 | 프롬프트 인젝션을 따르지 않습니다 |
| 범위 확인 | 해외·북한 여행, 코딩 같은 요청은 모델·도구 호출 전에 코드가 거절합니다 | 자료 없이 지어낸 결과를 내지 않습니다 |

## 외부 API와 허용 범위

모든 외부 연결은 OpenShell이 **호스트 + 메서드 + 경로 + 실행 파일** 단위로 제한합니다. 공공 API는 실서비스 모드에서만 [`policy/presets/`](policy/presets/)로 하나씩 엽니다.

| 서비스 | 용도 | 허용 범위 | 정책 |
|---|---|---|---|
| NVIDIA build.nvidia.com NIM | Nemotron 3 Super 추론 | `POST /v1/chat/completions`, 게이트웨이 `inference.local` 경유 | 기본 정책 |
| L40S 로컬 NIM | Nemotron 3 Nano 추론(문서별 분류) | `host.openshell.internal:8000` `POST /v1/chat/completions` | 기본 정책 |
| 위키백과 | 실존 장소·시대의 일반 배경 | `ko/en.wikipedia.org` `GET /w/rest.php/v1/search/page`, `GET /api/rest_v1/page/summary/**` | `itda-wikipedia` |
| Open-Meteo | 방문일 일기예보 | `api.open-meteo.com` `GET /v1/forecast`, `geocoding-api.open-meteo.com` `GET /v1/search` | `itda-open-meteo` |
| 공공데이터포털 | 관광공사 운영정보·무장애 정보·행사(B551011), 기상청 예보·특보(1360000), TAGO 버스(1613000), 장애인 편의시설(B554287) | `apis.data.go.kr` `GET /{B551011,1360000,1613000,B554287}/**` | `itda-tourapi` |
| 한국민족문화대백과사전(AKS) | 역사·문화 해설의 권위 있는 근거 | `devin.aks.ac.kr:8080` `GET /api/**` | `itda-ekc` |
| TMAP (SK open API) | 장소 좌표, 구간별 도보·자동차(택시 요금)·대중교통 경로 | `apis.openapi.sk.com` `GET /tmap/pois`, `POST /tmap/routes/pedestrian`, `POST /tmap/routes`, `POST /transit/routes` | `itda-tmap` |
| 네이버 검색 | 지도 등록 장소(이름·주소), 지식백과, 뉴스, 블로그 요약(신뢰도 낮음). 지도 리뷰·블로그 본문은 쓰지 않습니다 | `openapi.naver.com` `GET /v1/search/**` | `itda-naver-search` |
| Tavily / Brave | 일반 웹 검색 (키가 있을 때) | `api.tavily.com` `POST /search`, `api.search.brave.com` `GET /res/v1/web/search` | `itda-web-search` |

- **보내는 것**: 장소명 같은 검색어, 날짜, 좌표. 로컬 자료 파일은 외부로 보내지 않습니다.
- **받은 것**: 검색·API 결과도 그대로 믿지 않고, 로컬 자료와 같은 분류·인용 확인·합의 과정을 거칩니다.
- **키**: 모든 키는 서버의 `~/.itda.env`(권한 600)에 두고 레포에는 넣지 않습니다.
  - **NVIDIA API 키**는 샌드박스에 들어가지 않습니다. 샌드박스는 게이트웨이(`inference.local`)만 부르고, 키는 게이트웨이가 붙입니다.
  - **도구 키**(네이버·공공데이터포털·TMAP·AKS·Tavily·Brave)는 **샌드박스 안으로 들어갑니다.** 데모(`sh scripts/web_up.sh`)는 `ITDA_SANDBOX_TOOL_KEYS=1`을 켜서 이 키들을 샌드박스 프로세스의 환경변수로 넘깁니다. 대신 그 키를 들고 나갈 수 있는 곳은 위 표의 호스트·메서드·경로뿐이고, 실행 파일도 `/opt/venv/bin/python3`만 허용됩니다. 이 옵션을 끄면 도구 키 없이 실행되고, 해당 도구는 건너뜁니다.

## 검증

| 스크립트 | 확인하는 것 |
|---|---|
| [`eval/run_eval.py`](eval/run_eval.py) | 연습 과제 함정 23개: 당일 공지 운영시간, 오래된 블로그·동선 카드 미사용, 과장 표현, OCR 연도 불확실성, 동명이인, 알레르기, 광고·미끼 파일 제외, 인젝션 분류, restricted/secrets 미접근, output 밖 쓰기 없음, 승인 필요 |
| [`eval/run_cases.py`](eval/run_cases.py) | 직접 만든 변형 과제 2개(휠체어 가족 · 일본 단체 할랄)로 일반화 확인 |
| [`attacks/run_attacks.sh`](attacks/run_attacks.sh) | 샌드박스 안에서 외부 유출, 허용 호스트 악용, 금지 파일 읽기, 시스템 경로 변조를 시도해 모두 차단되는지 확인 |
| [`scripts/stack_check.sh`](scripts/stack_check.sh) | Nemotron·NIM·NeMoClaw·OpenShell 연결 상태 점검 |
| [`scripts/collect_evidence.sh`](scripts/collect_evidence.sh) → [`docs/evidence.txt`](docs/evidence.txt) | 서버에서 차단 시연 결과, OpenShell `DENIED` 로그, 적용 정책, 마지막 실행이 샌드박스 안 경로(`/sandbox/...`)를 읽고 `inference.local`·L40S 로컬 NIM으로 추론했다는 기록을 한 파일로 저장 (키 값은 가림) |

개발 중 측정치(실행마다 조금씩 다름): 연습 과제 19–22/23, 변형 과제 25/26.

## 폴더 구조

```
itda/            에이전트 (pipeline · prompts · context 규칙 · tools · guard · web)
policy/          OpenShell 정책, API별 프리셋, 데모 샌드박스 적용본
scripts/         서버 설치, 샌드박스 실행, 로컬 NIM, 웹 데모, 정책 내보내기
eval/            함정 체크리스트와 변형 과제
attacks/         보안 시연 스크립트
docs/            설치 가이드, 화면 이미지
```
