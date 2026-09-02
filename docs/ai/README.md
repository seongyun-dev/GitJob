# AI·분석 설계 문서

> 상태: AI 적용 범위와 데이터 경계 정의
>
> 기준일: 2026-08-28
>
> 현재 레포의 `AI/`에는 소스가 없으므로, 아래 내용은 Notion의 요구사항·C조 기능명세·API 명세를 구현 계약으로 정리한 것이다.

## 관련 문서

- [외부 조사 도구 연동 설계](external-research-tools.md): GitHub API·Tavily·비동기 Research 단계 설계
- [기술명 정규화·대표 기술 집계 설계안](technology-normalization-design.md): 기술 alias·Registry·LLM fallback 기반 정규화 설계
- [기술 Evidence Level 평가·LLM 연동 설계안](technology-level-llm-handoff.md): Backend Fact Pack 분석과 LLM 역할·검증·저장 설계
- [노트북 로컬 LLM GPU 런북](../infra/local-llm-runbook.md): WSL2·Docker Desktop·Ollama 실행 계약

## 1. AI의 역할

GitJob에서 AI는 분석 결과를 임의로 만드는 주체가 아니라, Registry·파이프라인·Evidence가 확정한 사실을 사용자에게 설명하고 검색하는 보조 계층이다.

| 기능 | AI 적용 | 근거/제약 |
|---|---|---|
| 기술 레벨 | 적용하지 않음 | L0~L3 규칙과 Evidence로 판정 |
| Skill Gap | 적용하지 않음 | Personal Level과 수요 규칙으로 결정 |
| 학습 후보 순위 | 기본 적용하지 않음 | Rule-first, 수요·Gap·선행관계 사용 |
| 프로젝트 Template | 자유 생성하지 않음 | 검수된 카탈로그만 노출 |
| 설명 생성 | 선택 적용 | 확정 Fact만 사용, 검증 실패 시 Rule Template |
| 기술 Q&A | 필수 기능 | 검색 결과와 인용을 포함하는 RAG |
| Pain/FAQ | 분석 보조 | Stack Overflow 반복 문제에서 도출, 검수 후 공개 |

## 2. Fact 기반 설명

분석·추천 결과 설명은 `Fact Pack`을 입력으로 한다.

```text
Evidence / Job Demand / Trend / Pain
              ↓
          Fact Pack
              ↓
   AI explanation 또는 Rule Template
              ↓
    근거 검증 → renderable 응답
```

설명 응답은 다음 정보를 갖는다.

- `generatedBy`: `AI` 또는 `RULE_TEMPLATE`
- `renderable`: 화면에 표시할 근거가 있는지
- `sources`: 사용한 채용·GitHub·Stack Overflow 출처
- `usedEvidenceIds`: 사용한 Evidence ID
- `registryVersion`, `analysisFinishedAt`, `generatedAt`
- AI 생성 실패·검증 실패 시 `fallbackReason`

`sources`와 `usedEvidenceIds`가 모두 비어 있으면 설명 블록을 렌더링하지 않는다. 모델이 근거에 없는 수치·순위·숙련도·채용 가능성을 생성하면 결과를 폐기하고 동일 Fact로 만든 Rule Template으로 대체한다.

## 3. 기술 Q&A/RAG

### 처리 흐름

```text
POST /api/v1/qa/questions
  → questionId·QUEUED 반환
  → Stack Overflow corpus 검색
  → PostgreSQL FTS, pgvector 또는 hybrid retrieval 중 확정한 방식
  → 출처·답변 상태 검증
  → grounded answer 생성
  → GET /api/v1/qa/questions/{questionId}
```

### 데이터와 검색 규칙

- 원본 Stack Exchange 데이터는 HDFS/Parquet corpus에서 관리한다.
- RAG Q&A 기능은 필수이며, PostgreSQL Full-Text Search 단독, `pgvector`, hybrid retrieval 중 검색 구현 방식만 별도 결정한다.
- 질문·답변의 URL, 제목, score, accepted 여부를 함께 반환한다.
- 출처가 없거나 검색 근거가 부족하면 `INSUFFICIENT_EVIDENCE`를 반환하고 답변을 생성하지 않는다.
- 원문 전체를 재게시하지 않고 필요한 요약과 링크만 제공한다.
- 기술 `tech_id`, `registry_version`, corpus 기간을 결과에 남긴다.
- 질문 등록과 답변 조회를 분리하고 사용자별 요청 한도를 둔다.

### 상태

```text
QUEUED → RUNNING → COMPLETED
                 ├→ INSUFFICIENT_EVIDENCE
                 ├→ FAILED
                 └→ CANCELED
```

실제 상태 enum·질의 한도·동기/비동기 방식은 구현 전에 확정한다. 현재 API 명세는 `202 Accepted` + polling을 기준으로 한다.

## 4. Pain Topic·FAQ

Stack Overflow 질문 수는 기술의 객관적 난이도가 아니다. C조 파이프라인은 기술별로 다음 신호를 만들고, Backend는 검수된 결과만 반환한다.

- 반복 질문 후보와 `questionShare`
- unanswered ratio
- accepted answer ratio
- 대표 질문·답변 링크
- 원인 요약, 해결 방향, 주의사항
- corpus 기간·표본 수·Registry 버전

FAQ는 초안 생성 → 사람이 검수 → 공개의 단계를 거친다. 출처가 없는 항목, 버전 차이를 숨기는 항목, 질문 빈도를 난이도로 번역한 항목은 공개하지 않는다.

## 5. AI 안전장치

### 근거·권한

- GitHub Token·개인 저장소 원문·민감한 환경 변수는 모델 입력에 필요 이상으로 넣지 않는다.
- 사용자가 접근 권한을 부여한 public/private 저장소와 공개 데이터만 사용한다. private 원문은 해당 사용자 분석에만 사용하고 시장 Trend에는 넣지 않는다.
- Prompt와 결과에 `analysisId`, `registryVersion`, source period를 연결한다.
- 모델에게 규칙 판정·시장 순위·채용 확률을 위임하지 않는다.
- 외부 링크와 인용은 검색 결과에 존재하는 것만 사용한다.

### 검증

1. 모델 출력의 기술명·수치·레벨·순위가 Fact Pack에 존재하는지 검증한다.
2. `usedEvidenceIds`와 설명 문장이 실제 Evidence에 연결되는지 확인한다.
3. source URL과 인용 문장이 검색 결과에 존재하는지 확인한다.
4. 실패하면 Rule Template 또는 `INSUFFICIENT_EVIDENCE`로 안전하게 종료한다.
5. prompt version·model version·fallback reason을 운영 로그에 남긴다. Token과 원문 코드는 남기지 않는다.

## 6. AI 운영 API

현재 API 명세에는 다음 내부/보조 API가 기록되어 있다.

| API | 용도 | 공개 범위 |
|---|---|---|
| `GET /api/v1/qa/questions/{questionId}` | Q&A 결과 조회 | 로그인 사용자 |
| `GET /api/v1/me/explanations` | 분석·추천 설명 | 로그인 사용자 |
| AI `/health` | API process liveness | 내부 |
| AI `/ready` | Ollama/model 준비 상태 | 내부 |
| AI metrics | LLM 성공·재시도·queue 상태 | 운영자 |

AI health/ready/metrics의 정확한 URI와 인증 정책은 최신 API 기능 ID가 부여되지 않은 초안이므로 구현 전 확정한다.

## 7. 현재 레포와 다음 작업

`Infra/docker/worker/Dockerfile`은 `AI/requirements.txt`를 설치하고 `python -m worker`를 실행하는 계약을 가정한다. Collector도 같은 이미지에서 `python -m collector`로 실행하도록 Compose가 구성되어 있다.

구현 순서:

1. 수집·정규화 결과의 Fact Pack schema와 version 고정
2. Rule Template 기반 설명을 먼저 구현
3. Stack Overflow corpus·검색·인용 구조 구현
4. Q&A queue·상태·quota·실패 격리 구현
5. AI 생성기를 붙이고 Fact 검증·fallback 추가
6. prompt/model/근거 로그와 품질 검증 데이터셋 구성

## 8. 원문 출처

- [요구사항 명세서](https://app.notion.com/p/db40dff912cf829e888b0141c8b5fd8d)
- [기능 명세서 작성](https://app.notion.com/p/d700dff912cf822ebaa981630e77682c)
- [API 명세서](https://app.notion.com/p/5110dff912cf82049d59817bbbb6b670)
- [회의록](https://app.notion.com/p/5900dff912cf82f8ade6816778a1ec77)
