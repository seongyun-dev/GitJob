# 기술 요약 생성기 — BE 연동 실측 보고

> 보내는 쪽: BE / 받는 쪽: AI (`AI/llm`)
> 측정일: 2026-09-16
> 대상 서버: 노트북 GPU 호스트(`LLM_SUMMARY_BASE_URL`) · `qwen3.5:4b` · `prompt_version=tech-summary/2026-09-15.1`
> 브랜치: `Feat/S15P21E102-256-be-llm-call-api`

## 0. 세 줄 요약

1. **BE→AI 호출 경로는 정상 동작한다.** 개발 DB의 실제 데이터로 기술 4개를 끝까지 돌렸고, 3건이 모델 생성(`OK`), 1건이 `FALLBACK`이었다.
2. **BE가 만드는 Fact Pack은 계약을 지킨다.** 4건 모두 `llm/contracts.py`의 `FactPack` 검증을 통과했다. 422는 한 번도 없었다.
3. **확인 요청 한 건, 개선 제안 한 건이 있다.** `lombok`이 `UNGROUNDED_IDENTIFIER`로 두 번 다 버려진 원인, 그리고 그 원인을 부르는 쪽에서 알 방법이 없다는 점이다.

---

## 1. 실측 결과

개발 DB의 실제 분석 결과(`user_id=2`, 성공한 저장소 분석 9건)로 `TechnologySummaryService`를 통해 호출했다.

| 기술 | 1차 호출 | 2차 호출 | `llm_status` | `confidence` |
|---|---|---|---|---|
| `spring-security` | 3,558ms | 31ms | `OK` | `HIGH` |
| `lombok` | 7,911ms | 28ms | **`FALLBACK`** | `MEDIUM` |
| `redis` | 8,315ms | 23ms | `OK` | `HIGH` |
| `spring-boot` | 5,470ms | 19ms | `OK` | `MEDIUM` |

2차 호출은 BE의 DB 캐시(`technology_summary`)에서 나오므로 HTTP가 아예 발생하지 않는다. `/health`는 기술 4개를 처리하는 동안 **1번만** 호출됐다(BE가 60초 TTL로 캐시).

문장 품질은 좋았다. 예를 들어 `spring-boot`는 기간·파일·API·작성자 구분을 전부 입력에 있던 사실에서만 가져왔다.

> **스프링 부팅 의존성과 애플리케이션 실행을 구성했다**
> build.gradle 에 스프링 부팅 관련 의존성을 직접 추가하고, DemoApplication 에서 SpringApplication.run 을 호출하여 애플리케이션을 시작했다. 하지만 import 문은 대부분 다른 사람이 작성한 것으로 확인됐다.
> `gap`: spring-boot 를 import 한 곳이 확인되지 않았다.

레벨 문자열(`L0`~`L3`)은 어느 문장에도 나오지 않았다. 비율 표기도 없었다.

---

## 2. 확인 요청 — `lombok`이 두 번 다 버려진다

재현되는 현상이다. 같은 Fact Pack으로 두 번 보냈고 두 번 다 같은 결과였다.

```
llm_status: FALLBACK
  attempt1 temp=0.2 codes=['UNGROUNDED_IDENTIFIER'] error=None
  attempt2 temp=0.0 codes=['UNGROUNDED_IDENTIFIER'] error=None
```

보낸 Fact Pack은 아래와 같다. 계약 위반은 없다.

```
authorship : MIXED
levels     : [('L1', mine=True), ('L0', mine=True)]
next_level : null            (레지스트리에 L2 이상 규칙이 없음)
highlights : IMPORT lombok                          mine=True
             IMPORT lombok.RequiredArgsConstructor  mine=True
             IMPORT lombok.Getter                   mine=True
             IMPORT lombok.AllArgsConstructor       mine=True
             IMPORT lombok.Builder                  mine=True
             IMPORT lombok.NoArgsConstructor        mine=True
             IMPORT lombok.Data                     mine=True
             DEPENDENCY org.projectlombok:lombok    mine=True
```

### 가설 (확정 아님)

`llm/validation.py`의 `_allowed_tokens()`를 이 Fact Pack에 직접 돌려 허용 어휘 56개를 뽑아 봤다. 그중 눈에 띄는 것:

```
... product, product.java, productcontroller, productcontroller.java, ...
```

**`productcontroller`는 있지만 `controller`는 없다.** `_TOKEN_SPLIT_PATTERN`이 `[^A-Za-z0-9]+`라 구분자에서만 쪼개고, camelCase 합성어는 분해되지 않기 때문이다. 같은 이유로 `Entity`, `Service`, `Repository` 같은 일반 명사도 허용 집합에 없다.

`lombok`은 highlights가 import 8줄뿐이라 모델이 쓸 구체적 재료가 적고, 그럴수록 "Controller 클래스에서" 같은 일반적인 표현으로 문장을 채우게 된다 — 그런데 그 단어가 정확히 걸린다. `spring-security`(허용 어휘 57개, 대부분 구체적 API 이름)에서는 같은 문제가 안 났다.

**검증기가 틀렸다고 보지는 않는다.** 환각을 잡는 것이 이 검사의 목적이고, 실제로 잡고 있다. 다만 재료가 빈약한 기술에서 FALLBACK이 구조적으로 잦아질 수 있어 보인다.

### 확인해 주셨으면 하는 것

1. `llm/smoke.py`나 로컬에서 이 Fact Pack을 재현해, **실제로 어떤 식별자가 걸렸는지** 확인
2. 그 단어가 위 가설대로 일반 명사라면, 프롬프트에 "highlights에 없는 영문 단어는 한국어로 풀어 쓴다" 류의 지시를 넣는 것이 나을지 검토

재현용 Fact Pack은 아래 부록에 요청 본문 전체로 실어 뒀다. 그대로 POST하면 된다.

---

## 3. 개선 제안 — 버려진 문장을 진단에 남겨 주면 좋겠다

지금 `attempts[]`에는 `temperature`, `failure_codes`, `error`만 있다. **무엇이 ungrounded였는지가 응답에 없다.**

```json
{"temperature": 0.2, "failure_codes": ["UNGROUNDED_IDENTIFIER"], "error": null}
```

그래서 위 2절의 원인을 BE 쪽 로그만으로는 좁힐 수 없었다. 허용 토큰 집합을 `validation.py`에서 직접 뽑아 추측하는 데까지가 한계였다.

`ValidationFailure`에는 이미 `detail`이 있고(`UNGROUNDED_IDENTIFIER`의 경우 걸린 식별자 목록), `AttemptReport`가 그것을 버리고 `code`만 싣고 있다. **`detail`까지 실어 주시면** 프롬프트를 고칠 때 BE 로그가 그대로 신호가 된다.

```python
# llm/server.py — AttemptReport
failure_codes: tuple[str, ...] = ()
failure_details: tuple[str, ...] = ()   # ← 이것만 있으면 충분
```

문장 본문 전체가 아니라 `detail`만으로 충분하다. 본문을 통째로 실으면 검증에서 떨어진 문장이 로그에 남게 되는데, 그건 원치 않으실 것 같다.

---

## 4. 운영 신호 — 18080이 닫혀 있던 구간이 있었다

오늘 오전 점검 때 다음 상태였다.

| 확인 | 결과 |
|---|---|
| Tailscale 피어 (`desktop-ub20p0o-2`) | `active; direct` |
| ICMP ping | 성공 |
| TCP 18080 | **실패 (8초 timeout, drop)** |

연결 거부가 아니라 timeout이라 서버 프로세스가 아니라 **방화벽/브리지 경로**에서 끊긴 것으로 보였다. 이후 다시 확인했을 때는 `/health`가 107ms에 200으로 응답했다.

BE는 이 상태를 장애로 올리지 않는다 — 요약 없이 카드를 그린다. 다만 그동안 사용자에게는 요약이 안 보이므로, `llm-summary-serve-wsl.sh`와 `llm-tailscale-bridge.ps1`이 재부팅 후에도 자동으로 올라오는지 한 번 봐 주시면 좋겠다.

---

## 5. 참고 — BE가 부르는 방식

AI 쪽에서 부하를 예상할 때 참고할 내용이다.

- **기술 1개 = 요청 1개.** 목록 화면이 아니라 카드마다 따로 부른다.
- **동시 요청 2건으로 제한**(`Semaphore`). GPU가 한 대라 어차피 직렬화되므로, 서버 큐를 늘리는 대신 BE에서 막는다. 자리를 2초 안에 못 받으면 보내지 않고 화면에 `PENDING` 을 내리며, 화면은 5초쯤 뒤 같은 요청을 다시 보낸다. **그래서 카드가 몰릴 때 같은 기술의 요청이 몇 번에 걸쳐 도착할 수 있다** -- 중복 생성처럼 보이지만 앞선 요청은 BE 에서 막혀 그쪽에 도달하지 않은 것이다.
- **`/health` 60초 캐시.** 프롬프트 버전과 모델 이름을 여기서 읽는다.
- **결과는 BE DB에 저장**(`technology_summary`, 사용자×기술당 1행). 같은 Fact Pack이면 다시 부르지 않는다. 캐시 키는 BE가 만든 `fact_pack_sha256`이고, 응답의 `cache_key`는 추적용으로만 보관한다.
- **`prompt_version`이 바뀌면 캐시가 자동으로 밀린다.** 조회 조건에 들어 있다. 프롬프트를 고치실 때 버전만 올려 주시면 BE 쪽에서 할 일은 없다.
- **connect 5초 / read 120초.** cold start가 1분에 가깝다고 들어 읽기는 길게 열어 뒀다.

---

## 6. 계약 검증 결과

BE가 실제로 보내는 요청 본문 4건을 `llm/contracts.py`의 `FactPack`에 그대로 먹였다.

```
OK    lombok
OK    redis
OK    spring-boot
OK    spring-security
통과 4 / 실패 0
```

관측된 특성 중 AI 쪽에서 알아 두면 좋을 것:

- **`next_level`이 `null`인 경우가 잦다.** 현재 레지스트리에서 L3 규칙을 가진 기술이 둘뿐이라, 대부분의 기술은 도달 가능한 최고 레벨에 이미 있다. 위 4건 중 `gap` 문장이 나온 것은 `spring-boot` 하나뿐이었다.
- **`period`는 본인 커밋 기준으로 채운다.** 기여 판정이 없으면 `null`로 보내고, 그러면 요약도 기간을 말하지 않는다.
- **`authorship`은 판정된 근거만 분모로 센다.** 미판정은 "남이 썼다"가 아니라 "모른다"이고, 그것을 남의 것처럼 세면 본인 몫이 체계적으로 과소평가된다. 근거와 실측치는 `TechnologySummaryFactStore.authorship()` 주석에 있다.

---

## 부록 — 재현 방법

아래 JSON을 `lombok.json`으로 저장하고 그대로 보내면 된다. BE가 실제로 보내는
요청 본문 전체이며, 손대지 않았다.

```bash
# 주소는 .env 의 LLM_SUMMARY_BASE_URL 을 쓴다. 이 문서는 커밋되므로 적지 않는다.
curl -s -m 5 "$LLM_SUMMARY_BASE_URL/health"

curl -s -X POST "$LLM_SUMMARY_BASE_URL/technology-summary" \
  -H 'Content-Type: application/json' \
  --data-binary @lombok.json
```

```json
{
  "user_id": "2",
  "fact_pack": {
    "schema_version": "technology-summary-request/v1",
    "locale": "ko-KR",
    "technology": {
      "tech_id": "lombok",
      "display_name": "Project Lombok",
      "repository_level": "L1",
      "personal_level": "L1",
      "registry_version": "registry-20260910.2"
    },
    "authorship": "MIXED",
    "levels": [
      { "level": "L1", "rules": ["Project Lombok import"], "mine": true },
      { "level": "L0", "rules": ["Project Lombok 의존성 선언"], "mine": true }
    ],
    "next_level": null,
    "highlights": [
      { "index": 0, "fact_type": "IMPORT", "value": "lombok",
        "file": "product/Product.java", "mine": true },
      { "index": 1, "fact_type": "IMPORT", "value": "lombok.RequiredArgsConstructor",
        "file": "product/ProductController.java", "mine": true },
      { "index": 2, "fact_type": "IMPORT", "value": "lombok.Getter",
        "file": "response/ApiResponse.java", "mine": true },
      { "index": 3, "fact_type": "IMPORT", "value": "lombok.AllArgsConstructor",
        "file": "response/ErrorCode.java", "mine": true },
      { "index": 4, "fact_type": "IMPORT", "value": "lombok.Builder",
        "file": "review/Review.java", "mine": true },
      { "index": 5, "fact_type": "IMPORT", "value": "lombok.NoArgsConstructor",
        "file": "review/Review.java", "mine": true },
      { "index": 6, "fact_type": "IMPORT", "value": "lombok.Data",
        "file": "dto/MyReview.java", "mine": true },
      { "index": 7, "fact_type": "DEPENDENCY", "value": "org.projectlombok:lombok",
        "file": "build.gradle", "mine": true }
    ],
    "repositories": [
      { "full_name": "Card-GGaduek/cardGGaduekMainServiceBackend", "mine": false },
      { "full_name": "cseongbo/Tripplannerz", "mine": false },
      { "full_name": "cseongbo/cardGGaduekMainServiceBackend", "mine": true },
      { "full_name": "cseongbo/naverStoreProjectBack", "mine": true }
    ],
    "period": { "first": "2025-05-06", "last": "2025-07-21", "months": 3 }
  }
}
```

BE 쪽에서 같은 것을 다시 뽑으려면 `DumpRealFactPack` 을 쓴다. 개발 DB 의 실제
데이터로 Fact Pack 을 만들어 파일로 떨군다.

```bash
DUMP_FACT_PACK=1 DUMP_USER_ID=2 DUMP_OUT=fact-packs \
  ./gradlew test --tests '*DumpRealFactPack'
```
