# JobKorea Collector V1

JobKorea `백엔드개발자` 채용 공고를 수집하고, 상세 본문과 이미지형 공고의
OCR 결과에서 기술 스택 및 요구 수준을 추출하는 임시 V1 구현입니다.

## 실행

저장소 루트에서 실행합니다.

```powershell
$python = ".\.venv\Scripts\python.exe"
$env:PYTHONPATH = "AI"
& $python -m JobKorea_Collector_V1 `
  --start-date 2026-08-01 `
  --end-date 2026-08-31 `
  --output-dir data\jobkorea
Remove-Item Env:PYTHONPATH
```

GUI는 아래 명령으로 실행합니다.

```powershell
$python = ".\.venv\Scripts\python.exe"
$env:PYTHONPATH = "AI"
& $python -m streamlit run AI\JobKorea_Collector_V1\gui.py
Remove-Item Env:PYTHONPATH
```

이미지 OCR을 사용하려면 PaddlePaddle GPU/CPU 패키지를 먼저 설치한 뒤
`AI\requirements-ocr.txt`를 설치합니다. GUI 전용 의존성은
`AI\requirements-gui.txt`에 있습니다.

## 출력

각 실행은 `data/jobkorea/<pipeline-run-id>/` 아래에 JSON 계약 출력, CSV 요약,
`manifest.json`, OCR 처리 상태와 오류 정보를 남깁니다. 원본 수집 스냅샷은
저장소에 커밋하지 않습니다.

## V1 인수인계 참고

- 목록·상세 HTML 구조가 변경될 수 있으므로 파서 선택자와 응답 필드를 우선 점검합니다.
- 이미지 공고는 OCR 성공 여부와 관계없이 원본 `IMAGE_ONLY` 상태를 보존합니다.
- 요청 제한, 재시도, 중복, 마감 공고 정책은 운영 수집기로 전환할 때 보완해야 합니다.
- 기술 추출은 현재 규칙 기반 V1이며, Registry 연계와 의미 중복 판정은 후속 작업입니다.
