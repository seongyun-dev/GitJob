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

현재 `AI/llm`은 인터페이스 표지만 있고 실제 모델 호출기는 아직 구현되지
않았다. Worker 연동 전까지는 Ollama API를 독립적으로 검증한다.

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
