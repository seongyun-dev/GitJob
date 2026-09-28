# JobKorea PaddleOCR CPU 운영 계약

## 배경

2026-09-15 데이터 서버에서 최근 1일 JobKorea 공고를 수집했다. 166건의
상세 요청은 모두 성공했지만 Collector 이미지에 PaddleOCR가 없어 이미지가 있는
64개 공고의 223개 이미지를 처리하지 못했다. 결과 중 26건은 원본 본문이
`IMAGE_ONLY`였다.

## 이미지와 자원 경계

`Infra/docker/worker/Dockerfile`은 Worker와 Collector가 공유하지만 OCR 의존성은
`JOBKOREA_OCR_ENABLED=true`인 빌드에만 설치한다. EC2 배포는 Worker와 Collector
태그를 별도로 빌드하며 서비스 서버의 Worker 및 데이터 서버의 Worker에는 OCR을
설치하지 않는다.

Collector는 CPU 2코어와 메모리 4 GiB를 상한으로 사용한다. JobKorea 수집은 한
번에 하나만 실행하고 대규모 Spark 잡과 실행 시간을 겹치지 않는다. 데이터 서버는
스왑이 없으므로 메모리 제한을 제거하지 않는다.

PaddleOCR 3.x의 기본 탐지 모델은 `PP-OCRv5_server_det`이어서 4 GiB cgroup에서
실제 이미지 추론 중 OOM이 재현됐다. 운영 설정은 `PP-OCRv5_mobile_det`과
`korean_PP-OCRv5_mobile_rec`을 사용하고, 인식 batch는 1, 입력 최대 변은 2048로
제한한다. 다운로드한 임시 이미지는 추론 후 삭제하고, 원본 URL과 OCR 텍스트·상태를
남긴다. 원본 이미지 자체를 별도 저장하지 않으므로 정확도 재검증은 제공처 URL이 계속
유효할 때만 가능하다.

PaddleOCR 3.x는 PaddlePaddle 3.2.0 CPU wheel, OpenMP 런타임 `libgomp1`,
OpenCV 런타임 `libgl1` 및 `libglib2.0-0`을 사용한다. 자동 다운로드되는 한국어 모델은
`PADDLE_PDX_CACHE_HOME=/data/.paddlex`에 저장한다. CPU 추론 스레드는
`PADDLE_PDX_CPU_NUM_THREADS=2`로 제한한다. `/data`는 기존
`collector-state` named volume이므로 컨테이너 재생성 후에도 모델과 cursor가
보존된다.

## 배포 후 검증

Collector 이미지를 다시 빌드하고 데이터 서비스를 재생성한 후 다음을 확인한다.

1. 컨테이너에서 `paddle`과 `paddleocr` import가 성공한다.
2. 최초 OCR 실행 후 `/data/.paddlex/official_models`에 모델이 남는다.
3. JobKorea 최근 1일 수집을 한 번 실행한다.
4. manifest의 `engine_loaded`가 1이고 `engine_load_failures`가 0이다.
5. `images_processed`가 0보다 크고 OCR 텍스트와 confidence가 기록된다.
6. `detail_failures`, `invalid_records`, `stopped_reason`이 비어 있다.
7. HDFS Raw 및 Analysis Input에 JSON, CSV, manifest가 발행되고 read-back이
   성공한다.
8. 실행 중 NameNode, DataNode, Spark Worker 재시작과 OOM이 없어야 한다.

## 2026-09-15 서버 카나리

운영 컨테이너를 교체하지 않고 별도 이미지·볼륨에서 최근 목록 1페이지를 실행했다.

- Collector 제한: CPU 2코어, 메모리 4 GiB
- 실행 시간: 약 5분
- 수집: 40건, 상세 실패 0건
- 이미지 공고: 12건
- OCR 성공 이미지: 10개
- OCR 실패 이미지: 2개(원본 이미지 오류 1개, 제공처 HTTP 403 1개)
- OCR 성공 공고 예시 인식 문자 수: 1,470자
- 관측 메모리: 약 535~871 MiB
- 영속 모델 캐시: 19 MiB
- 모델: `PP-OCRv5_mobile_det`, `korean_PP-OCRv5_mobile_rec`

동일한 4 GiB 제한에서 기본 `PP-OCRv5_server_det`은 약 4.18 GiB RSS에 도달해
cgroup OOM으로 종료됐고, 모바일 모델 적용 후에는 같은 제한에서 정상 종료됐다.
카나리는 `--no-upload-raw`와 전용 볼륨을 사용했으므로 운영 cursor와 HDFS에는
영향을 주지 않았다.

## 남은 운영 인수

JobKorea 오전·저녁 schedule은 `S15P21E102-272`에서 활성화한다. OS crontab 등록,
OCR 포함 Collector 이미지의 실제 배포, 첫 OCR 성공 회차 검증과 과거 OCR 미적용
데이터의 재수집은 별도 운영 인수로 관리한다.
