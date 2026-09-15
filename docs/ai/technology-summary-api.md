# 기술 요약 API — 호출 레퍼런스

> 기준일: 2026-09-15 / `S15P21E102-256` / 구현: `AI/llm/`
>
> 계약과 설계 근거는 [technology-summary-contract.md](technology-summary-contract.md),
> 모델을 어떻게 띄우는지는 [local-llm-runbook.md](../infra/local-llm-runbook.md)
> 3.1·3.2장을 본다. 이 문서는 **부르는 쪽**을 위한 것이다.

| | |
|---|---|
| Base URL | `http://100.90.250.31:18080` (Tailscale. 노트북 GPU 호스트) |
| 인증 | 없음. tailnet 안에서만 닿는다 |
| Content-Type | `application/json`, UTF-8. 응답은 한국어 |
| 권장 timeout | 120초 (warm 3~8초, cold 약 56초) |

기술 하나에 요청 하나다. 12개 기술이면 12번 부른다 — 4B 모델에 한꺼번에
시키면 뒤쪽을 뭉개고, 하나씩 보내야 실패한 것만 다시 시킬 수 있다.

**동기 호출이다.** 큐도 폴링도 없고 서버 내부에 `async` 도 없다. VRAM 6GiB 에
3.4GB 모델이라 Ollama 의 동시 실행 슬롯이 사실상 1개이므로, 요청이 몇 개가
오든 GPU 에서는 한 번에 하나씩 돈다. 실측: 동시 3건이 각각 3.0s / 6.3s / 9.4s
로 3초씩 쌓였다. 12개를 한꺼번에 쏘면 마지막 응답은 40초쯤 뒤에 온다.
`cache_key` 로 저장해 두면 두 번째부터는 GPU 를 쓰지 않는다.

---

## 1. 엔드포인트

### `GET /health`

프로세스가 살아 있는지만 말한다. 모델 준비 상태는 말하지 않는다.

```bash
curl -s http://100.90.250.31:18080/health
```

```json
{
  "status": "alive",
  "service": "llm-technology-summary",
  "model": "qwen3.5:4b",
  "prompt_version": "tech-summary/2026-09-15.1",
  "ollama_base_url": "http://127.0.0.1:11434"
}
```

### `POST /technology-summary`

사용자 1명 × 기술 1개의 요약 한 건.

---

## 2. 요청

`user_id` 는 `fact_pack` **밖에** 둔다. 캐시 키는 사람을 구분해야 하지만,
모델에 넘기는 프롬프트에는 사람을 지목하는 값이 들어가지 않는다.

| 필드 | 타입 | |
|---|---|---|
| `user_id` | string (1~200) | 필수. 캐시 키 구분용 |
| `fact_pack` | object | 필수. 아래 |

### `fact_pack` — `technology-summary-request/v1`

모르는 필드는 422 로 거절한다.

| 필드 | | 설명 |
|---|---|---|
| `schema_version` | 필수 | `"technology-summary-request/v1"` 고정 |
| `locale` | 선택 | 기본 `"ko-KR"` |
| `technology` | 필수 | `tech_id`(소문자 슬러그), `display_name`, `repository_level`, `personal_level`, `registry_version`(`registry-YYYYMMDD.N`) |
| `authorship` | 필수 | 아래 표. **건수·비율이 아니라 구간** |
| `levels` | 선택 | `{level, rules[], mine}`. `rules` 는 1개 이상 |
| `next_level` | 선택 | `{level, rule, missing[]}`. 최고 레벨이면 `null`. `personal_level` 보다 위여야 한다 |
| `highlights` | 선택 | 최대 8개. `{index, fact_type, value, file, mine}`. `index` 는 배열 순서대로 `0..n-1` |
| `repositories` | 선택 | `{full_name, mine}` |
| `period` | 선택 | `{first, last, months}`. 본인 커밋 기준. 없으면 `null` — 그러면 요약이 기간을 언급하지 않는다 |

### `authorship`

| 값 | 뜻 |
|---|---|
| `MOSTLY_MINE` | 본인 근거(`SOLE_AUTHOR`·`CO_AUTHORED`)가 과반 |
| `MIXED` | 본인 근거가 있으나 과반은 아니다 |
| `MOSTLY_OTHERS` | 본인 근거가 소수다 |
| `NOT_VERIFIED` | 기여 판정 자체가 없다 — `commit_sha` 가 비었거나 GitHub 이 커밋을 계정에 붙이지 못했다. **"안 썼다"가 아니다** |

건수를 그대로 보내면 모델이 "약 73%" 를 쓴다. 와이어프레임이 비율 표기를
금지하므로 입력에서 없앤다.

---

## 3. highlights 만들기

`fact_payload` 에는 `value` 라는 키가 없다. `fact_type` 마다 다른 키를 하나로
눕혀 보낸다. 아래 순서가 선별 우선순위이기도 하다 — 각 종류가 닿는 최고 규칙
레벨을 따른다.

| 우선 | `fact_type` | payload 키 | 예 |
|---|---|---|---|
| 0 | `API_CALL` | `CALL` → 없으면 `METHOD` | `SpringApplication.run` |
| 1 | `ANNOTATION` | `NAME` | `@EnableMethodSecurity` |
| 2 | `SYNTAX_NODE` | `NAME` | `SecurityConfig` |
| 3 | `CONFIG_KEY` | `KEY` | `server.port` |
| 4 | `IMPORT` | `MODULE` | `org.springframework.security.web` |
| 5 | `SOURCE_FILE` | `FILE_PATH` | `src/main.c` |
| 6 | `DEPENDENCY` | `COORDINATE` | `org.projectlombok:lombok` |

**`CONFIG_KEY` 의 `VALUE` 는 보내지 않는다.** 설정 값은 파일에 적힌 그대로라
접속 문자열이나 비밀번호가 들어 있을 수 있다. 서버도 `KEY` 만 읽는다.

`API_CALL` 은 `CALL` 을 `METHOD` 보다 먼저 쓴다. `METHOD` 는 마지막 조각이라
`run`, `get`, `build` 처럼 혼자서는 아무 말도 안 되는 값이 나오고, 그것이 그대로
"run 을 호출했다" 가 된다.

값 기준으로 중복을 제거하고 8개만 보낸다 — `SecurityFilterChain` 이 12번
나와도 하나다. `file` 은 마지막 두 세그먼트로 줄여 보내면 된다(안 줄여도 서버가
줄인다). `mine` 은 기여 판정이 없으면 `false` 로 보낸다. 그 구분은 `authorship`
이 이미 싣고 있다.

`AI/llm/facts.py` 의 `fact_value()` 와 `select_highlights()` 가 이 규칙을
구현하고 있으므로, Python 쪽에서 조립한다면 그대로 쓰면 된다.

---

## 4. 테스트 요청

```bash
curl -s -X POST http://100.90.250.31:18080/technology-summary \
  -H 'Content-Type: application/json' \
  -d @- <<'JSON'
{
  "user_id": "user-1",
  "fact_pack": {
    "schema_version": "technology-summary-request/v1",
    "locale": "ko-KR",
    "technology": {
      "tech_id": "spring-security",
      "display_name": "Spring Security",
      "repository_level": "L2",
      "personal_level": "L2",
      "registry_version": "registry-20260910.2"
    },
    "authorship": "MOSTLY_MINE",
    "levels": [
      { "level": "L2", "rules": ["인증 필터 체인 구성"], "mine": true },
      { "level": "L1", "rules": ["Spring Security import"], "mine": true }
    ],
    "next_level": {
      "level": "L3",
      "rule": "메서드 보안 활성화",
      "missing": ["@EnableMethodSecurity", "@PreAuthorize"]
    },
    "highlights": [
      { "index": 0, "fact_type": "API_CALL", "value": "SecurityFilterChain",
        "file": "config/SecurityConfig.java", "mine": true },
      { "index": 1, "fact_type": "API_CALL", "value": "authorizeHttpRequests",
        "file": "config/SecurityConfig.java", "mine": true },
      { "index": 2, "fact_type": "API_CALL", "value": "passwordEncoder",
        "file": "config/SecurityConfig.java", "mine": true },
      { "index": 3, "fact_type": "IMPORT", "value": "org.springframework.security.web",
        "file": "filter/JwtAuthenticationFilter.java", "mine": true },
      { "index": 4, "fact_type": "IMPORT", "value": "org.springframework.security.core",
        "file": "service/UserDetailsServiceImpl.java", "mine": false }
    ],
    "repositories": [
      { "full_name": "gitjob-example/card-service-backend", "mine": true }
    ],
    "period": { "first": "2025-08-11", "last": "2025-08-19", "months": 1 }
  }
}
JSON
```

같은 Fact Pack 이 `AI/llm/fixtures/technology_summary_request_v1.json` 에 있다.

---

## 5. 응답

```json
{
  "llm_status": "OK",
  "summary": {
    "tech_id": "spring-security",
    "headline": "인증 필터 체인을 구성하고 비밀번호 인코딩을 처리했다",
    "summary": "2025 년 8 월 기간 동안 SecurityFilterChain 을 설정하고 authorizeHttpRequests 와 passwordEncoder 를 직접 호출했다. 코드에서 Spring Security 관련 라이브러리를 import 한 곳도 확인되었다.",
    "gap": "@EnableMethodSecurity 와 @PreAuthorize 를 사용한 곳이 확인되지 않았다.",
    "used_highlights": [0, 1, 2, 3],
    "confidence": "HIGH"
  },
  "cache_key": "ae0bbbb4dff3de5e0bd923f3a4a559d3e2ce6c7473b59537255f425fdf371fbb",
  "model": "qwen3.5:4b",
  "prompt_version": "tech-summary/2026-09-15.1",
  "attempts": [
    { "temperature": 0.2, "failure_codes": [], "error": null }
  ],
  "model_confidence": null
}
```

| 필드 | |
|---|---|
| `llm_status` | `OK` 모델이 쓴 문장 / `FALLBACK` 데이터에서 기계적으로 만든 문장. **둘 다 정상이다** |
| `summary.headline` | 40자 이내. 카드 제목. 레벨 문자열을 담지 않는다 — 레벨은 옆에 따로 그려진다 |
| `summary.summary` | 2~3문장, 200자 이내 |
| `summary.gap` | 다음 수준까지 무엇이 비었는지 한 문장. `next_level` 이 `null` 이면 `null`. 카드를 실행 가능하게 만드는 것이 이 필드다 |
| `summary.used_highlights` | 근거로 쓴 `highlights` 의 `index` 배열 |
| `summary.confidence` | `HIGH`·`MEDIUM`·`LOW`. 자신감이 아니라 **입력이 얼마나 구체적인가** |
| `cache_key` | sha256 hex 64자 |
| `model`·`prompt_version` | 재현용. `prompt_version` 은 캐시 키에 이미 들어 있다 |
| `attempts` | 버려진 시도와 이유. 로그용 |
| `model_confidence` | 모델이 낸 등급이 규칙 파생값과 달랐을 때만 채워진다. 보통 `null` |

---

## 6. 부르는 쪽이 알아야 할 것

### 정상 경로는 언제나 200이다

모델이 죽어 있어도, 느려도, 틀린 문장을 써도 200 과
`llm_status: "FALLBACK"` 이 나간다. 요약은 이미 완성된 카드 위에 얹는 것이다 —
수준·근거·permalink 는 이 응답과 무관하게 이미 있으므로, 이 호출이 실패해도
`/me/technologies` 가 실패하면 안 된다.

### 노트북이 꺼져 있으면 연결 자체가 안 된다

추론은 EC2 가 아니라 노트북 GPU 에서 돈다. 서버에는 GPU 가 없다. 연결 실패와
timeout 은 예외로 올리지 말고 요약 없이 렌더한다. `LLM_SUMMARY_BASE_URL` 이
비어 있으면 아예 호출하지 않는 쪽이 기본이어야 한다.

```dotenv
LLM_SUMMARY_BASE_URL=http://100.90.250.31:18080
LLM_SUMMARY_TIMEOUT_SECONDS=120
```

### confidence 는 AI 서비스가 계산한다

AI 서비스가 Fact Pack에서 규칙으로 계산해 모델 값을 덮는다. BE가 계산하는
필드가 아니다. 레벨을 모델에 맡기지 않은 것과 같은 이유다 — 실측에서
`DEPENDENCY`뿐인 입력에 모델이 `HIGH`를 돌려줬다. 어긋난 경우에만
`model_confidence`에 모델이 낸 값이 남는다.

| 값 | 조건 |
|---|---|
| `HIGH` | `mine: true` 인 `API_CALL`·`ANNOTATION`·`SYNTAX_NODE`·`CONFIG_KEY` 가 있다 |
| `MEDIUM` | 본인 근거가 `IMPORT`·`SOURCE_FILE`·`DEPENDENCY` 뿐이다 |
| `LOW` | `authorship` 이 `NOT_VERIFIED` 이거나 `highlights` 가 비었거나 본인 근거가 없다 |

### `attempts[].failure_codes`

모델 응답을 버린 이유다. 카드에 보여줄 값이 아니라 프롬프트를 고칠 때 보는
신호다.

| 코드 | 뜻 |
|---|---|
| `UNGROUNDED_IDENTIFIER` | 본문의 영문 식별자가 입력에 없던 이름. 환각을 잡는 핵심 검사 |
| `UNVERIFIED_AUTHORSHIP_CLAIM` | `NOT_VERIFIED` 인데 "직접 작성", "본인이" 를 썼다 |
| `GAP_MISSING` | `next_level` 이 있는데 `gap` 이 `null` |
| `GAP_WITHOUT_NEXT_LEVEL` | `next_level` 이 `null` 인데 `gap` 을 썼다 |
| `GRADE_WORD` | 초급·중급·고급·전문가·숙련이 들어갔다 |
| `RATIO_MENTIONED` | 숫자+`%`·퍼센트·비율이 들어갔다 |
| `LEVEL_STRING_IN_BODY` | 본문에 `L0`~`L3` 를 썼다 |
| `TECH_ID_MISMATCH` | 요청과 다른 `tech_id` 를 돌려줬다 |
| `HIGHLIGHT_INDEX_OUT_OF_RANGE` | `used_highlights` 에 없는 index |
| `HEADLINE_TOO_LONG` | 40자 초과 |
| `SUMMARY_TOO_LONG` | 200자 초과 |

---

## 7. 422 — 계약 위반

Fact Pack 이 계약을 어기면 모델을 부르기 전에 막는다.

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "fact_pack", "technology"],
      "msg": "Field required",
      "input": { "schema_version": "technology-summary-request/v1" }
    }
  ]
}
```

자주 걸리는 것 — `highlights` 의 `index` 가 배열 순서와 다름, `highlights` 가
9개 이상, `next_level.level` 이 `personal_level` 이하, `registry_version` 이
`registry-YYYYMMDD.N` 형식이 아님, `tech_id` 가 소문자 슬러그가 아님.
