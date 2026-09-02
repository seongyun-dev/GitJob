# 외부 조사 도구 연동 설계

> 상태: 설계 완료·구현 예정
>
> 기준일: 2026-09-01
>
> 관련 작업: `S15P21E102-77` / `infra/S15P21E102-77-ai-infra`

## 1. 배경과 목표

현재 RAG는 이미 수집한 corpus에서 근거를 찾는 데 적합하지만, 저장소에
사용된 기술의 최신 릴리스·변경사항·공식 사용법처럼 corpus 밖에서 갱신되는
정보를 자동으로 보완하지는 못한다.

GitJob의 GitHub 분석은 비동기 작업이며 최대 24시간이 소요될 수 있다. 이
시간을 LLM이 계속 답변을 생성하는 시간으로 사용하지 않고, 저장소 분석과
외부 조사를 단계적으로 실행하는 작업 예산으로 사용한다.

목표는 다음과 같다.

- 저장소 분석 결과에서 최신 확인이 필요한 기술을 식별한다.
- GitHub와 공식 문서를 우선 조사해 변경·호환성·사용법 근거를 수집한다.
- 근거와 출처를 보존한 뒤 로컬 LLM이 분석 보고서와 설명을 생성한다.
- 외부 검색 결과가 부족하거나 충돌하면 추측하지 않고 확인 필요 상태로 종료한다.

## 2. 도입 결정

### 2.1 GitHub 분석: GitHub REST/GraphQL API

저장소 자체 분석은 검색 엔진이 아니라 GitHub 공식 API를 사용한다.

- repository metadata, default branch, tree, contents를 수집한다.
- commits, tags, releases와 manifest·workflow·Dockerfile을 분석한다.
- 필요한 경우 dependency/security 관련 공식 endpoint를 추가한다.
- private repository 원문은 사용자 권한 범위 안에서 Worker와 로컬 저장소에만 둔다.

GitHub API는 public/private repository, contents, archive, release 관련
endpoint를 제공하므로 저장소 분석의 1차 수집 경로로 사용한다.

참고: [GitHub REST API - Repositories](https://docs.github.com/en/rest/repos)

### 2.2 최신 기술 조사: Tavily Search API

저장소 분석으로 얻은 기술명·버전·질의만 Tavily에 전달해 최신 외부 정보를
검색한다.

사용할 기능:

- `include_domains`: 공식 문서·공식 릴리스 노트 도메인 우선 제한
- `time_range` 또는 날짜 범위: 최신 변경사항 조사
- `include_raw_content=markdown` 또는 필요한 경우 `text`: 근거 원문 확보
- `max_results`: 검색 결과 수 제한과 비용·지연 제어

Tavily의 `include_answer` 자동 답변은 사용하지 않는다. 검색 결과의 제목,
URL, 발행·수정 시각, 발췌·원문만 수집하고 최종 답변은 Fact Pack 검증을
거친 로컬 LLM이 작성한다.

참고: [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)

### 2.3 초기 범위에서 제외하는 도구

- Exa: 의미 기반·심층 검색의 대안이지만, 초기에는 Tavily로 검색 계약을
  고정한 뒤 품질과 quota를 측정한다.
- Brave Search API: 독립 검색 인덱스가 장점이지만, 초기 구현에서 필요한
  원문 추출·도메인 정책을 별도로 검증해야 하므로 후순위다.
- 브라우저 자동화: 로그인·동적 페이지·레이아웃 변화에 취약하므로 API가
  없는 공식 문서를 보완하는 경우에만 검토한다.

## 3. 전체 처리 흐름

```text
분석 요청
  → QUEUED
  → GitHub snapshot / manifest / code facts 수집
  → 기술·버전·최근성 검사
  → 조사 대상과 질의 생성
  → GitHub API 또는 Tavily 공식 문서 검색
  → Evidence 정규화·중복 제거·출처 저장
  → Fact Pack 생성
  → 로컬 LLM 설명·요약 생성
  → Fact/출처 검증
  → COMPLETED 또는 INSUFFICIENT_EVIDENCE
```

내부 처리 단계는 다음을 제안한다.

```text
COLLECTING → RESEARCHING → SYNTHESIZING → VERIFYING
```

현재 공개 API의 상태 enum과 충돌하지 않도록 내부 단계로 먼저 사용하고,
외부에 노출할 상태는 기존 `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`,
`CANCELED`, `INSUFFICIENT_EVIDENCE` 계약을 우선한다.

## 4. 도구 호출 경계

LLM이 외부 API를 직접 호출하지 않는다. Worker가 도구를 실행하고 결과를
정규화해 모델에 전달한다.

| 도구 | 입력 | 출력 | 민감정보 경계 |
|---|---|---|---|
| `github_snapshot` | repository, ref, 사용자 권한 | tree, manifest, commit, release, code facts | GitHub token은 Worker 내부에서만 사용 |
| `tavily_search` | 기술명, 버전, 질의, 허용 도메인, 기간 | title, URL, published/updated time, snippet, raw content | private 소스 원문·token을 전송하지 않음 |
| `fact_pack_builder` | 정규화된 GitHub·검색 Evidence | versioned Fact Pack | source id와 수집 시각 보존 |
| `local_llm_synthesis` | Fact Pack, 분석 규칙, 출력 schema | 설명·요약·인용 | 외부 LLM으로 재전송하지 않음 |

검색 결과를 모델에게 넘길 때도 원문 전체를 무제한으로 넣지 않고, 질의와
관련된 발췌·필요 section만 token 예산 안에서 전달한다.

## 5. Evidence와 출처 규칙

각 외부 조사 결과는 최소한 다음 필드를 갖는다.

```json
{
  "evidenceId": "ev-...",
  "sourceKind": "GITHUB_RELEASE | OFFICIAL_DOC | PACKAGE_REGISTRY | OTHER",
  "sourceUrl": "https://...",
  "title": "...",
  "technology": "...",
  "observedVersion": "...",
  "publishedAt": "...",
  "fetchedAt": "...",
  "query": "...",
  "excerpt": "...",
  "sourceTrust": "PRIMARY | SECONDARY",
  "registryVersion": "..."
}
```

원칙:

1. 공식 문서·릴리스 노트·패키지 registry를 1차 출처로 우선한다.
2. 검색 도메인 allowlist를 기술별로 관리하고, 검색 결과 URL을 그대로
   신뢰하지 않는다.
3. 저장소에 고정된 버전과 최신 버전이 다르면 두 사실을 구분해 기록한다.
4. 서로 다른 출처가 충돌하면 최신이라는 이유만으로 하나를 선택하지 않고
   충돌 상태와 출처를 보고서에 남긴다.
5. URL·발행 시각·수집 시각·질의를 보존해 나중에 재현할 수 있게 한다.
6. 근거가 없는 기술 호환성, 보안 상태, 숙련도, 채용 가능성을 생성하지
   않는다.

## 6. 개인정보·보안

- `GITHUB_TOKEN`, `TAVILY_API_KEY`는 환경 변수 또는 secret manager에서만
  읽고 로그·event·Fact Pack에 저장하지 않는다.
- private repository의 소스·환경 변수·token·개인정보를 Tavily에 보내지
  않는다.
- 외부 검색 질의에는 필요한 기술명·버전·일반화된 오류만 포함한다.
- 검색 결과와 모델 출력에 private 코드가 섞였는지 출력 검증 단계에서
  검사한다.
- 외부 검색 quota, retry, rate limit과 실패 원인을 metrics에 남기되 secret과
  원문 코드는 기록하지 않는다.

## 7. LLM의 역할과 제한

로컬 LLM은 다음 작업을 담당한다.

- 어떤 기술·버전의 추가 조사가 필요한지 질의 후보를 만든다.
- 수집된 Evidence를 Fact Pack 기준으로 요약한다.
- 분석 결과와 최신 외부 정보를 사용자에게 설명하고 출처를 연결한다.

다음 판정은 LLM에 위임하지 않는다.

- 기술 레벨 L0~L3
- Skill Gap과 학습 후보 순위
- 채용 가능성·시장 순위
- 근거가 없는 최신성·호환성 판정

기존 Rule-first 정책과 `Fact Pack → AI explanation → 검증 → Rule Template /
INSUFFICIENT_EVIDENCE` fallback을 그대로 유지한다.

## 8. 24시간 비동기 작업 정책

24시간은 최대 작업 제한이며, 실제 작업은 단계별 timeout과 재시도로 관리한다.

- 동일 repository/ref/registry version 조합은 결과를 cache한다.
- GitHub API와 Tavily 호출은 bounded retry와 exponential backoff를 사용한다.
- 외부 검색이 일시 실패해도 기존 Fact Pack으로 가능한 설명을 먼저 만들고,
  최신성 근거가 필수인 항목은 `INSUFFICIENT_EVIDENCE`로 분리한다.
- 작업이 24시간을 넘기기 전에 마지막 정상 단계, 실패 도구, 재시도 횟수,
  다음 조치가 상태에 남아야 한다.
- 사용자는 polling으로 진행 상태를 확인하고, 완료 전 부분 결과 공개 여부는
  API 계약에서 별도로 결정한다.

## 9. 구현 순서

### 1단계: 계약과 adapter

- `github_snapshot`, `tavily_search`, `Evidence`, `FactPack` schema 정의
- `GITHUB_TOKEN`, `TAVILY_API_KEY`, timeout, retry, max results 환경 변수 정의
- 실제 외부 호출을 대체할 fixture와 mock response 작성
- 공식 도메인 allowlist와 source trust 정책 작성

### 2단계: Worker research stage

- manifest·imports·Dockerfile·CI에서 기술과 버전 추출
- 오래된 버전·unknown technology·최근성 확인 필요 조건 정의
- GitHub API → Tavily 순서의 bounded tool loop 구현
- 결과 정규화·중복 제거·cache·재시도·실패 격리 구현

### 3단계: 로컬 LLM 연결

- 현재 노트북 Ollama endpoint와 고정 모델 tag 사용
- Fact Pack만 입력으로 받는 synthesis prompt와 출력 schema 구현
- source URL, `usedEvidenceIds`, `generatedAt`, model/prompt version 기록
- 검증 실패 시 Rule Template 또는 `INSUFFICIENT_EVIDENCE` 반환

### 4단계: 통합 검증

- public repository fixture로 end-to-end 분석
- private repository 원문이 외부 검색 payload에 포함되지 않는지 검증
- 최신 release 변경·검색 결과 없음·API quota 초과·부분 실패 테스트
- 처리 시간, 검색 횟수, token 사용량, GPU/RAM 사용량 metrics 확인

## 10. 구현 전 결정이 필요한 항목

- Tavily 요금제·월 quota와 요청당 `max_results`
- 기술별 공식 도메인 allowlist
- GitHub token 최소 권한과 private repository 접근 정책
- 외부 검색 결과 보존 기간과 재검색 주기
- `RESEARCHING` 등 내부 상태를 API 응답에 노출할지 여부
- 검색 결과가 없을 때 기존 corpus만으로 답할 수 있는 조건
- 현재 `qwen3.5:4b`의 도구 호출 단위 context·동시성 제한과 최종 출력 품질 기준

## 11. 참고 문서

- [GitHub REST API - Repositories](https://docs.github.com/en/rest/repos)
- [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)
- [AI·분석 설계 문서](README.md)
- [노트북 로컬 LLM GPU 런북](../infra/local-llm-runbook.md)
