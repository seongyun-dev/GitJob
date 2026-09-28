# 노트북 로컬 LLM GPU 런북

> 대상: WSL2 + Docker Desktop + NVIDIA GPU 노트북
>
> 현재 검증 환경: Ubuntu 24.04 WSL2, Docker Desktop Linux engine, RTX 4050 Laptop GPU 6GiB

## 1. 목적과 격리 원칙

이 런북은 GitJob 서비스 스택과 별도로 노트북에서 로컬 LLM 추론 서버를
실행하기 위한 문서다. LLM은 `gitjob-llm`이라는 독립 Compose project로
실행하며, 기존 `gitjob`의 PostgreSQL·Redis·Kafka·HDFS·Spark Compose를
자동으로 시작하거나 변경하지 않는다.

- LLM host port: `127.0.0.1:11434`
- Ollama model cache: `gitjob-ollama-models` named volume
- GPU allocation: Ollama service에만 `gpus: all`
- 외부 공개: 없음. LAN에 열기 위해 `0.0.0.0` binding으로 바꾸지 않는다.
- 기본 이미지: 이 노트북에서 검증한 Ollama 0.33.2 digest로 고정

`AI/llm`에는 기술 요약 생성기가 구현돼 있다(`S15P21E102-256`). 호출기·프롬프트
·검증·폴백은 `AI/README.md`의 "Technology summary generation"을 본다. 이 문서는
그 아래에서 모델을 어떻게 띄우는지만 다룬다.

## 2. 사전 검증

WSL 터미널에서 다음 명령이 통과해야 한다.

```bash
nvidia-smi
docker version
docker compose version
docker info
```

GPU 컨테이너 경로는 다음 일회성 smoke test로 확인한다.

```bash
docker run --rm --gpus all \
  nvidia/cuda:12.4.1-base-ubuntu22.04 \
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
```

## 3. Ollama 기동

저장소 루트에서 실행한다. 현재 WSL 파일시스템에서는 실행 비트가 자동으로
보존되지 않을 수 있으므로 `bash`로 호출한다.

```bash
bash Infra/scripts/llm-up.sh
```

스크립트는 `compose.llm.yaml`을 `gitjob-llm` project로 기동하고,
`GET http://127.0.0.1:11434/api/version` 응답까지 확인한다.

직접 실행해야 할 경우:

```bash
docker volume create gitjob-ollama-models >/dev/null
docker compose \
  --project-name gitjob-llm \
  --project-directory . \
  -f Infra/compose/compose.llm.yaml \
  up -d
```

모델 서버를 중지할 때는 volume을 보존한다.

```bash
docker compose \
  --project-name gitjob-llm \
  --project-directory . \
  -f Infra/compose/compose.llm.yaml \
  down
```

`down --volumes` 또는 `docker volume rm gitjob-ollama-models`는 모델 캐시를
삭제하므로 명시적인 정리 작업에서만 사용한다.

## 3.1 WSL 네이티브 실행 (AI 서버 호스트 기본 경로)

> 추가일: 2026-09-14 / `S15P21E102-256`

이 저장소가 놓인 WSL 배포판이 곧 AI 서버 환경이 됐다. 이 호스트에는 Docker
Desktop 데몬이 떠 있지 않고 WSL integration 도 꺼져 있으며 `sudo` 에 암호가
걸려 있어, 3장의 컨테이너 경로가 그대로 동작하지 않는다. 그래서 Ollama 를
사용자 홈에 직접 설치해 쓴다. root 가 필요한 단계는 없다.

3장의 Docker 경로를 폐기하는 것이 아니다. Docker Desktop 이 떠 있는 노트북에서는
그쪽이 여전히 유효하고, 두 경로는 **같은 Ollama 0.33.2** 를 실행한다 —
`compose.llm.yaml` 이 이미지 digest 로 고정한 것과 설치 스크립트가 받는 릴리스
태그가 같은 버전이다.

```bash
bash Infra/scripts/llm-install-wsl.sh   # 최초 1회. 약 1.4GiB 내려받아 ~/.local/ollama 에 푼다
bash Infra/scripts/llm-serve-wsl.sh     # 기동 + 모델 확인. 이미 떠 있으면 확인만 한다
```

`llm-serve-wsl.sh` 는 멱등이다. 이미 서빙 중이면 모델 존재만 다시 확인하고
끝나므로, 모델이 필요한 작업 앞에 무조건 한 번 부르면 된다.

| 환경변수 | 기본값 | |
|---|---|---|
| `OLLAMA_HOME` | `~/.local/ollama` | 바이너리·번들 CUDA 라이브러리 |
| `OLLAMA_HOST` | `127.0.0.1:11434` | loopback 고정. LAN 에 열지 않는다 |
| `OLLAMA_KEEP_ALIVE` | `-1` | 가중치 상주 |
| `LLM_MODEL` | `qwen3.5:4b` | |
| `OLLAMA_LOG_FILE` | `~/.ollama/serve.log` | |

모델 캐시는 `~/.ollama/models` 다. 컨테이너 경로의 `gitjob-ollama-models`
볼륨과 별개이므로, 두 경로를 오가면 3.4GB 를 각각 한 번씩 받는다.

### 왜 릴리스 자산을 직접 푸는가

공식 `install.sh` 는 `/usr/local` 에 쓰기 위해 root 를 요구한다. 이 호스트에서는
쓸 수 없다. 릴리스 자산은 `.tar.zst` 인데 `zstd` 바이너리도 설치돼 있지 않고
(설치에 다시 root 가 필요하다) GNU tar 의 `--zstd` 는 그 바이너리를 호출한다.
설치 스크립트는 `zstd` 가 있으면 쓰고, 없으면 임시 디렉터리에 Python
`zstandard` 를 받아 푼다. 저장소나 `.venv` 에는 아무것도 남기지 않는다.

### 이 호스트에서 실측한 값

```text
GPU        NVIDIA GeForce RTX 4050 Laptop GPU, 6.0 GiB (가용 5.0 GiB)
추론       CUDA0, libdirs=ollama,cuda_v13, driver 13.1
cold       첫 요약 요청 56초 (모델 적재 포함)
warm       기술 1개당 3~8초 (num_ctx 8192, num_predict 300)
```

`inference compute ... library=CUDA` 줄이 로그에 없으면 CPU 로 떨어진 것이다.
오류로 뜨지는 않고 몇 배 느려지기만 하므로, `llm-serve-wsl.sh` 가 그 줄을
마지막에 출력한다.

Ollama 가 VRAM 기준으로 잡는 기본 `num_ctx` 는 4096 이다. 기술 요약 경로는
계약대로 8192 를 명시적으로 넘긴다.

## 3.2 EC2 서비스에서 노트북 모델을 부르는 경로

> 추가일: 2026-09-14 / `S15P21E102-256`

### 왜 이 모양인가

추론은 노트북에 남는다. `j15e102`(EC2)에는 **GPU 가 없고** 가용 메모리도
8GiB 남짓이라 4B 모델을 옮길 수 없다. 그래서 호출 방향이 EC2 → 노트북이다.

노트북은 NAT 뒤라 EC2 가 직접 못 들어온다. 두 대는 이미 Tailscale 로 묶여
있고 tailnet ACL 이 전 대역·전 포트를 허용하므로(`tailscale debug netmap` 의
PacketFilter 확인) 그 위로 부르면 된다. **역방향 SSH 터널도 sshd 설정 변경도
필요 없다.**

```text
gitjob-service-backend-1 (EC2, 172.18.0.5)
        │  http://100.90.250.31:18080
        ▼
Tailscale  (j15e102 100.71.215.74 → desktop-ub20p0o-2 100.90.250.31)
        │
Windows bridge  llm-tailscale-bridge.ps1   100.90.250.31:18080
        │
        ▼
WSL  python -m llm  0.0.0.0:18080  →  Ollama 127.0.0.1:11434  →  GPU
```

### 왜 브리지가 따로 필요한가

Tailscale 은 **Windows** 에 붙어 있고 요약 서버는 **WSL** 안에 있다. Windows
의 Tailscale 주소는 WSL NAT 안으로 들어가지 않으므로, 그 주소에서 듣는 무언가가
있어야 한다.

원래 의도된 장치는 `netsh interface portproxy` 이고 규칙도 이미 있다.

```text
100.90.250.31   18080   →   172.27.30.232   18080
127.0.0.1       18080   →   172.27.30.232   18080
```

그런데 **Tailscale 주소 쪽 규칙은 바인딩되지 않는다.** `netstat -ano` 에
`127.0.0.1:18080` 만 LISTENING 으로 보인다. `iphlpsvc` 가 시작할 때 Tailscale
어댑터가 아직 그 주소를 갖고 있지 않으면 그 규칙만 조용히 비어 있게 되고,
다시 붙이려면 관리자 셸에서 `Restart-Service iphlpsvc` 를 해야 한다. 부팅할
때마다 같은 순서 문제가 재현된다.

브리지 스크립트는 관리자 권한이 필요 없다. 높은 포트를 특정 주소에 바인딩하는
것은 특권 동작이 아니고, 인바운드 방화벽 규칙
(`GitJob LLM test FastAPI (Tailscale)`, TCP 18080, LocalIP `100.90.250.31/32`,
RemoteIP `100.64.0.0/10`)은 이미 있다.

### 상주 구성 (최초 1회)

이 노트북은 AI 연산 전용 GPU 서버로 상주한다. 손으로 띄우는 프로세스로 두면
재부팅 한 번에 EC2 쪽 호출이 조용히 타임아웃나기 시작하고, 서버 로그에는 왜
그런지 설명할 것이 남지 않는다. 그래서 세 조각 모두 서비스로 등록한다.

WSL 에서 — Ollama 와 요약 FastAPI 를 systemd **사용자** 유닛으로 등록한다.
root 가 필요 없다.

```bash
bash Infra/scripts/llm-install-wsl.sh          # Ollama 최초 설치
bash Infra/scripts/llm-install-services-wsl.sh # 두 서비스 등록·기동
```

| 유닛 | 하는 일 |
|---|---|
| `gitjob-ollama.service` | `127.0.0.1:11434` 추론 런타임 |
| `gitjob-llm-summary.service` | `0.0.0.0:18080` 요약 FastAPI |

요약 서버는 Ollama 를 `Wants` 로만 건다. 모델이 없으면 `FALLBACK` 요약을
돌려주면 되고, 그걸 `Requires` 로 막으면 degraded 기능이 죽은 엔드포인트가
된다.

Windows 에서 — 브리지를 로그온 작업으로 등록한다. 현재 사용자 작업이라
관리자 권한이 필요 없다.

```powershell
powershell -ExecutionPolicy Bypass -File `
  \\wsl.localhost\Ubuntu-24.04\home\ssafy\workspace\S15P21E102\Infra\scripts\llm-bridge-install-task.ps1
```

작업 이름은 `GitJob LLM Tailscale Bridge`. 같은 실행기를 사용자 Startup 폴더에도
숨김 VBS로 등록한다. 일부 Windows 환경에서는 유효한 장기 PowerShell 작업도
Task Scheduler가 `0xFFFD0000`으로 실행 전에 종료하기 때문에 두 개의 독립적인
로그온 진입점을 둔다. 단일 인스턴스 mutex가 있어 둘 다 성공해도 브리지는 하나만
실행된다. 설치 성공 여부는 예약 작업 상태가 아니라 Tailscale 주소의 실제 리스너로
판정한다.

브리지는 로그온 시점에 Tailscale 또는 WSL이 아직 없을 것을 전제하고 직접 깨워
기다리며, WSL/Tailscale 주소가 바뀌거나 일시 장애가 발생해도 supervisor가 종료하지
않고 다시 연결한다.
설치기는 브리지 스크립트를 `%LOCALAPPDATA%\GitJob`으로 복사하고 그 Windows
경로를 예약 작업에 등록한다. 예약 작업이 `\\wsl.localhost`의 원본을 직접 실행하면
로그온 직후 WSL 파일시스템이 준비되기 전에 PowerShell 자체가 종료될 수 있기
때문이다. 실행 중 의존성이 늦게 준비되거나 일시적으로 사라져도 supervisor는
종료하지 않고 재시도한다.

브리지 진단 로그:

```text
%LOCALAPPDATA%\GitJob\logs\llm-tailscale-bridge.log
%LOCALAPPDATA%\GitJob\logs\llm-tailscale-bridge-bootstrap.log
```

### 남은 수동 작업 하나 — lingering

```bash
sudo loginctl enable-linger ssafy
```

이것만 root 가 필요해서 자동화하지 못했다. **켜지 않으면 마지막 WSL 세션이
닫힐 때 두 서비스가 함께 내려간다.** 로그온 작업이 WSL 을 깨우기는 하지만,
lingering 없이는 그 세션이 끝나는 순간 사용자 systemd 관리자가 같이 종료된다.

현재 상태 확인:

```bash
loginctl show-user ssafy --property=Linger
```

### 손으로 띄울 때

```bash
bash Infra/scripts/llm-summary-serve-wsl.sh   # 서비스를 안 쓸 때만
```

```powershell
powershell -ExecutionPolicy Bypass -File `
  \\wsl.localhost\Ubuntu-24.04\home\ssafy\workspace\S15P21E102\Infra\scripts\llm-tailscale-bridge.ps1
```

### 확인

```bash
ssh J15E102T 'curl -s http://100.90.250.31:18080/health'
ssh J15E102T 'docker exec gitjob-service-backend-1 \
    curl -s http://100.90.250.31:18080/health'
```

상태 확인:

```bash
systemctl --user status gitjob-ollama gitjob-llm-summary
journalctl --user -u gitjob-llm-summary -n 50
```

2026-09-14 실측: 서비스 호스트와 `gitjob-service-backend-1` 컨테이너 양쪽에서
`/health` 200, 컨테이너에서 보낸 `POST /technology-summary` 가 `llm_status: OK`
와 요약 한 건을 받아 왔다. systemd 유닛과 로그온 작업으로 바꾼 뒤에도 같은
경로로 다시 확인했다.

2026-09-15 재검증: `gitjob-ollama.service`와
`gitjob-llm-summary.service`는 user unit으로 `enabled/active`, Windows의
`GitJob LLM Tailscale Bridge` 로그온 작업은 `Running`이었다. 서비스 재시작 후
`127.0.0.1:18080`과 `100.90.250.31:18080` 모두 `/health` 200 및
`prompt_version=tech-summary/2026-09-15.1`을 반환했다. 이 WSL 사용자는
`Linger=no`이므로 로그인 전 상주를 보장하지 않으며, Windows 로그인 시 예약
작업이 WSL을 기동하는 현재 경로를 사용한다. 실제 노트북 재부팅 시험은 수행하지
않았다.

2026-09-16 장애 재현 및 수정: `Fix/S15P21E102-279-be-result-contract-compatibility`
기준 BE 호출에서 Tailscale ping은 성공했지만 TCP 18080은 timeout이었다. 노트북에서
확인한 결과 WSL FastAPI와 방화벽은 정상이었고 Tailscale 주소의 Windows 리스너만
없었다. 기존 예약 작업은 WSL UNC 경로를 직접 실행하다 `Last Result=1`로 종료되어
있었다. Windows 로컬 설치본, supervisor 재시도, Startup fallback, 단일 인스턴스
mutex를 적용했다. 이후 브리지와 WSL을 모두 완전히 종료한 상태에서 Startup 진입점만
실행해 첫 health probe 200으로 자동 복구되는 것을 확인했다. EC2에서도
`100.90.250.31:18080/health`가 200, 실제 `POST /technology-summary`가
`llm_status=OK`를 반환했다.

`tailscale ping` 이 되는데 TCP 가 안 되면 ACL 을 의심하지 말 것 —
`tailscale ping` 은 ACL 을 거치지 않는다. 리스너가 있는지부터 본다.

### BE 가 쓸 환경변수

`.env.example` 에 자리를 만들어 뒀다. 호출부는 아직 없다.

```dotenv
LLM_SUMMARY_BASE_URL=http://100.90.250.31:18080
LLM_SUMMARY_TIMEOUT_SECONDS=120
```

비워 두면 호출하지 않는 쪽이 기본이어야 한다. 요약은 이미 완성된 카드 위에
얹는 것이라 없을 때 화면이 깨지면 안 된다.

## 4. 모델 도입 순서

RTX 4050 Laptop GPU의 VRAM은 6GiB이고 WSL 메모리는 15GiB이므로, 처음에는
3B~4B급 양자화 모델 하나만 받아 GPU 사용량·응답시간·한국어 품질을 측정한다.
동시에 여러 모델을 상주시켜 VRAM을 나누지 않는다.

초기 검증 모델은 공식 tag `qwen3.5:4b`로 고정했다. 모델 표기 다운로드 크기는
약 3.4GB이며, 현재 노트북에서는 `qwen3.5:latest`(9B, 약 6.6GB)를 사용하지
않는다. 더 큰 모델을 추가하기 전에 VRAM·응답시간을 측정한다. 모델 tag를
변경할 때는 공식 Ollama library의 현재 tag와 용량을 확인한다.

모델을 받은 뒤 다음으로 확인한다. 컨테이너 이름 대신 Compose service를
사용하므로 project/container 이름 변경에도 동작한다.

```bash
docker compose \
  --project-name gitjob-llm \
  --project-directory . \
  -f Infra/compose/compose.llm.yaml \
  exec -T ollama ollama list
docker compose \
  --project-name gitjob-llm \
  --project-directory . \
  -f Infra/compose/compose.llm.yaml \
  exec -T ollama ollama run qwen3.5:4b "한국어로 한 문장만 답해줘."
```

정확한 서비스 상태는 다음으로 확인한다.

```bash
docker compose \
  --project-name gitjob-llm \
  --project-directory . \
  -f Infra/compose/compose.llm.yaml ps
```

## 5. GitJob Worker 연동 전 계약

Worker 구현 시에는 다음 환경변수 계약을 사용한다.

```dotenv
LLM_PROVIDER=ollama
LLM_BASE_URL=http://host.docker.internal:11434
LLM_MODEL=qwen3.5:4b
LLM_TIMEOUT_SECONDS=300
LLM_MAX_OUTPUT_TOKENS=5500
LLM_MAX_RETRIES=2
```

이 노트북에서 `qwen3.5:4b`의 첫 cold start는 약 87초로 측정됐고, 모델이
적재된 뒤의 warm 호출은 약 2초였다. Worker는 시작 시 warm-up을 수행하거나
최소 300초 timeout을 사용하며, 같은 분석 작업의 연속 chunk 호출은 warm 모델을
재사용한다. 출력 토큰 상한을 두고 스트리밍 응답을 사용하면 긴 분석도 첫 결과를
먼저 전달할 수 있다.

Worker 컨테이너 안에서 `localhost:11434`를 사용하지 않는다. 이후 Worker와
Ollama가 같은 external Docker network를 공유하도록 결정하면
`LLM_BASE_URL=http://ollama:11434`로 바꿀 수 있지만, 현재는 Worker 코드와
Fact Pack/결과 계약이 미완성이므로 host gateway 방식을 기본값으로 둔다.

AI는 Registry/Evidence가 확정한 Fact Pack만 설명하며, 기술 레벨·Skill Gap·추천
순위를 모델에게 위임하지 않는다. 근거 검증 실패 시 Rule Template 또는
`INSUFFICIENT_EVIDENCE`로 종료한다.

## 6. 점검 항목

WSL 네이티브 경로(3.1장):

```bash
bash Infra/scripts/llm-serve-wsl.sh
nvidia-smi
tail -n 20 ~/.ollama/serve.log
```

기술 요약 경로까지 한 번에 확인하려면 `AI/`에서:

```bash
../.venv/bin/python -m llm.smoke
```

컨테이너 경로(3장):

```bash
curl --fail http://127.0.0.1:11434/api/version
docker compose \
  --project-name gitjob-llm \
  --project-directory . \
  -f Infra/compose/compose.llm.yaml ps
nvidia-smi
OLLAMA_CONTAINER="$(docker compose \
  --project-name gitjob-llm \
  --project-directory . \
  -f Infra/compose/compose.llm.yaml ps -q ollama)"
docker stats --no-stream "$OLLAMA_CONTAINER"
```

장시간 실행 전에는 기존 GitJob core/data profile을 함께 켰을 때의 CPU·RAM·디스크
사용량을 따로 기록한다. LLM 추론 중 GPU VRAM이 부족하면 모델 수·context 길이·
동시성을 먼저 줄이고, 모델을 무리하게 크게 올리지 않는다.
