# 개인 기여 판정 활성화와 확인 Runbook

- Jira: `S15P21E102-279` 후속
- 대상: `analysis-worker`(git blame) → `backend`(GitHub 조회) → `analysis_evidence_commit`
  → `personalLevel`
- 성격: **배포·확인 절차.** 왜 이렇게 설계됐는지는
  `BE/.../service/EvidenceAuthorshipService.java` 와 `V14`·`V19` 마이그레이션 주석에 있다.
- 작성일: 2026-09-17

> 이 절차는 아직 **한 번도 실행된 적이 없다.** 기여 판정은 운영에서 돈 적이 없고,
> 아래 확인 쿼리는 코드와 스키마에서 뽑은 것이지 실제 결과를 보고 쓴 것이 아니다.
> 예상과 다르면 §6을 먼저 보고, 그래도 다르면 이 문서를 고친다.

---

## 0. 무엇을 켜는가

`ANALYSIS_ATTRIBUTE_AUTHORS` 하나다. 지금은 꺼져 있어서 파이프라인 네 칸이 전부 비어 있다.

| # | 하는 일 | 어디서 | 지금 |
|---|---|---|---|
| ① | 근거 줄을 `git blame` 해 커밋 해시를 붙인다 | analysis-worker | **안 함** |
| ② | 근거를 `commit_sha` 와 함께 저장한다 | backend | 전부 `NULL` |
| ③ | 그 커밋을 GitHub 에 물어 작성자를 확인한다 | backend | 0건 |
| ④ | 본인 근거만으로 규칙을 다시 평가한다 | backend | 미판정 |

①이 꺼져 있으면 ②~④는 오류 없이 조용히 빈다. 화면에는 기술과 근거가 정상으로
보이고 `personalLevel` 만 영영 안 나온다.

### 0.1 Registry 44 전환과는 별개다

`repository-analysis-result/v1` 계약도 근거에 `commit_sha` 를 싣는다
(`docs/data/contracts/repository-analysis-result-v1.schema.json` 의 `EvidenceItem`).
**이 절차는 [Registry 44 / v3 전환](2026-09-16-registry44-v3-result-activation.md)을
기다리지 않아도 된다.** 둘은 순서 제약이 없다.

다만 목적지가 다르다. 이 절차는 `personalLevel` 까지만 살린다. 공고 매칭·추천까지
가려면 Rule Pack 계보가 필요하고 그것은 v3 전환 쪽이다.

---

## 1. 전제

### 1.1 배포돼 있어야 하는 것

`Fix/S15P21E102-279-be-result-contract-compatibility` 의 `d8ae529` 이후 backend.
포함돼야 하는 것:

- `V19__evidence_contribution_other_author.sql` — 기여 라벨에 `OTHER_AUTHOR` 를 연다.
  **이게 없으면 판정이 CHECK 제약에 걸려 트랜잭션이 깨진다.**
- 커밋 조회 상한 도달 경고 (§5에서 본다)

워커 이미지는 바뀌지 않았다. 플래그만 켠다.

### 1.2 확인

서비스 호스트에서 운영 Compose 설정을 명시해 확인한다.

```bash
ENV_FILE=.env.service COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2.yaml \
PROFILES=core,app bash Infra/scripts/verify-deployment.sh
```

`schema` 줄의 최신 마이그레이션이 `V19` 인지 본다.

---

## 2. 켜기 전에 봐야 할 것

이 플래그는 **전체 히스토리 클론**을 함께 켠다. 얕은 체크아웃에서 `git blame` 은
실패하지 않고 모든 줄을 tip 커밋에 돌리기 때문에 둘이 한 스위치로 묶여 있다 —
답이 그럴듯하게 틀리느니 켜지 말라는 뜻이다.

### 2.1 디스크

측정치(`spring-petclinic`, 근거 40 파일):

```text
depth 1  클론 1.4s / 디스크  3MB / blame 2.1s  (답이 틀림)
full     클론 4.0s / 디스크 13MB / blame 2.7s
```

저장소마다 배수가 다르다. 확인할 것:

- `ANALYSIS_WORK_ROOT`(기본 `/tmp/gitjob-analysis`) 가 있는 볼륨의 여유
- `ANALYSIS_MAX_REPOSITORY_BYTES`(기본 2GiB) 에 새로 걸리는 저장소가 생길 수 있다.
  크기는 fetch **뒤에야** 알 수 있어 `REPOSITORY_TOO_LARGE` 로 실패한다
  (`AI/analysis/clone.py`). 실패한 분석은 사용자에게 그대로 보인다.

### 2.2 GitHub API 한도

기여 판정은 **사용자 본인의 토큰**으로 커밋을 조회한다. 커밋 하나가 호출 하나다.

- 한 분석에서 조회하는 고유 커밋은 최대 100개(`MAX_COMMIT_LOOKUPS`)
- 같은 커밋은 `repository_commit` 에 캐시돼 재분석에서 다시 묻지 않는다
- 상한에 걸리면 남은 커밋은 미확인으로 남고 기여가 **과소평가**된다. 그 사실은
  경고 로그에만 남는다(§5.2)

---

## 3. 켜기

### 3.1 설정

data 호스트의 env 파일을 본다.

```bash
grep -n ANALYSIS_ATTRIBUTE_AUTHORS .env.data
```

- **줄이 없으면** 그대로 두면 된다. compose 기본값이 이미 `true` 다.
- **`=false` 로 적혀 있으면** 그 줄을 지우거나 `=true` 로 고친다. env 파일이 compose
  기본값을 덮어쓴다.

### 3.2 재시작

```bash
ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data-cluster.yaml \
PROFILES=data ./Infra/scripts/up.sh
```

현재 2호스트 HDFS/Spark 구성에서는 반드시 `compose.ec2-data-cluster.yaml`을 쓴다.
`compose.ec2-data.yaml`만 사용하면 NameNode의 Tailscale RPC publish와 host-network
DataNode 설정이 빠져 NameNode/DataNode healthcheck가 서로 기다리게 된다.

`up.sh` 는 `compose up -d` 라 설정이 바뀐 컨테이너만 다시 만들고 healthcheck 까지
돌린다. 값은 **기동 시점에만** 읽으므로 컨테이너를 다시 띄우지 않으면 반영되지 않는다.

### 3.3 실제로 켜졌는지

```bash
docker exec "$(docker ps -qf name=analysis-worker)" printenv ANALYSIS_ATTRIBUTE_AUTHORS
```

`true` 여야 한다.

---

## 4. 재분석

**기존 분석은 자동으로 채워지지 않는다.** `commit_sha` 는 분석 시점에 `git blame` 으로만
얻을 수 있고 나중에 채울 방법이 없다. 켠 뒤에 새로 분석한 것부터 값이 생긴다.

### 4.1 대상 고르기

확인용 사용자 한 명을 고를 때 **세 조건을 모두** 만족해야 한다. 하나라도 어긋나면
파이프라인이 정상인데도 화면이 비어 보인다.

1. **본인이 실제로 커밋을 쓴 저장소**여야 한다. 커밋 작성자의 GitHub login 과 사용자
   login 이 정확히 일치할 때만 본인 기여로 잡힌다. 포크·클론 저장소로 시험하면
   전부 `OTHER_AUTHOR` 가 된다.
2. **GitHub 계정에 등록된 이메일로 커밋**했어야 한다. 등록하지 않은 주소로 커밋하면
   본인 코드여도 GitHub 이 계정을 붙이지 못해 `UNVERIFIED` 가 된다. 과소평가는
   의도된 것이다 — 없는 기여를 주장하지 않는다.
3. 그 사용자의 **저장소를 전부** 재분석한다. 일부만 하면 §7의 C 계산 쪽이 막힌다.

### 4.2 실행

재분석은 사용자 인증이 필요한 API다. **운영자가 남의 계정으로 대신 걸 수 없다.**
대상 사용자가 화면에서 직접 누르거나, 그 사용자의 세션으로 호출한다.

```text
POST /api/v1/analyses
{ "repositoryFullName": "owner/repo", "branchName": "main" }
```

202면 새로 등록, 200이면 이미 진행 중인 분석을 안내한 것이다.

---

## 5. 확인

### 5.1 홉별 쿼리

`<analysisId>` 는 4.2에서 받은 값이다. **순서대로 본다** — 앞 칸이 비면 뒤는 볼 필요가 없다.

**① + ② 워커가 blame 했고 저장됐는가**

```sql
SELECT count(*) AS 근거,
       count(commit_sha) AS 커밋붙은근거
  FROM analysis_evidence
 WHERE analysis_id = '<analysisId>';
```

`커밋붙은근거` 가 0이면 ①이 안 된 것이다. §6.1.

**③ 작성자를 확인했는가**

```sql
SELECT contribution_type, count(*)
  FROM analysis_evidence_commit
 WHERE analysis_id = '<analysisId>'
 GROUP BY contribution_type;
```

기대: `SOLE_AUTHOR` 가 1건 이상. 전부 `UNVERIFIED` 면 §6.2, 전부 `OTHER_AUTHOR` 면
§4.1의 1번 조건을 다시 본다.

**④ personalLevel 이 나오는가**

```text
GET /api/v1/me/technologies
```

기술 항목의 `personalLevel` 이 채워져야 한다.

> **③에 `SOLE_AUTHOR` 가 있는데 ④가 비는 것은 정상일 수 있다.** 규칙의 `REQUIRED`
> 절이 **전부** 본인 근거로 덮여야 레벨이 나온다. 하나만 있으면 되는 식이면 Personal
> 과 Repository 가 거의 같아져 두 칸을 둘 이유가 사라지기 때문이다.

### 5.2 로그

backend 컨테이너에서 본다. 기여 판정은 워커가 아니라 **backend** 가 한다.

```bash
docker logs --tail 200 "$(docker ps -qf name=backend)" 2>&1 | grep authorship
```

정상:

```text
INFO  authorship recorded: analysisId=..., evidence=120, commits=37,
      lookedUp=37, cached=0, skipped=0
```

- `lookedUp` 은 GitHub 호출 수, `cached` 는 `repository_commit` 에서 답을 얻은 수다.
  재분석에서 `lookedUp=0, cached=37` 이면 API 한도를 전혀 안 쓴 것이다.

주의해서 볼 것:

```text
WARN  authorship lookup budget exhausted: analysisId=..., commits=120,
      lookedUp=100, cached=0, skipped=20, limit=100.
      남은 커밋은 묻지 못해 미확인으로 남았고 기여가 과소평가된다.
```

이 경고는 **그 분석의 기여가 실제보다 적게 잡혔다**는 뜻이다. 저장된 행만 보면
"미확인이 많은 저장소"와 구분되지 않으므로, 이 로그가 유일한 단서다.

자주 나오면 알려 달라. `MAX_COMMIT_LOOKUPS=100` 이 맞는 수치인지 판단할 데이터가
아직 없고, 이 로그가 그 데이터가 된다.

### 5.3 전체 상태

data 호스트에서는 운영 cluster overlay를 명시한다.

```bash
ENV_FILE=.env.data COMPOSE_OVERRIDE_FILE=Infra/compose/compose.ec2-data-cluster.yaml \
PROFILES=data bash Infra/scripts/verify-deployment.sh
```

```text
analysis-personal      OK      최근 성공 분석 an_xxx 근거 612/651 건에 commit_sha 있음
```

ACTION 이면 그 줄의 remedy 를 본다.

---

## 6. 안 될 때

### 6.1 `commit_sha` 가 전부 비어 있다

① 이 안 돌았다. 순서대로 확인한다.

1. `printenv ANALYSIS_ATTRIBUTE_AUTHORS` 가 `true` 인가 (§3.3)
2. 컨테이너를 재시작했는가 — 값은 기동 시점에만 읽는다
3. 그 분석이 **켠 뒤에** 시작됐는가 — 켜기 전 요청은 옛 설정으로 돈다
4. 워커 로그에 `authorship unavailable` 이 있는가. 있으면 blame 이 실패한 것이고
   보통 클론이 얕거나 파일이 사라진 경우다

### 6.2 `contribution_type` 이 전부 `UNVERIFIED`

③ 은 돌았지만 작성자를 못 붙였다.

- §4.1의 2번(등록되지 않은 커밋 이메일)이 가장 흔하다. 대상 사용자의 GitHub
  Settings → Emails 를 확인한다
- backend 로그에 `authorship skipped, repository name unknown` 이 있으면
  `analysis_job.repository_full_name` 이 비어 있는 것이다
- GitHub 토큰이 만료됐으면 조회가 실패한다. 그때는 근거는 남고 이 표만 빈다 —
  분석을 되돌리지 않는 것이 설계다

### 6.3 분석이 `REPOSITORY_TOO_LARGE` 로 실패한다

전체 히스토리가 `ANALYSIS_MAX_REPOSITORY_BYTES` 를 넘었다(§2.1). 그 저장소만
제외하거나 상한을 올린다. 상한을 올릴 때는 워커 디스크를 함께 본다.

---

## 7. 여기까지 해도 끝나지 않는 것

`personalLevel` 은 살아나지만 **공고 매칭·추천은 여전히 계산되지 않는다.** 두 가지가
더 필요하다.

1. **Rule Pack 계보** — [Registry 44 / v3 전환](2026-09-16-registry44-v3-result-activation.md).
   계보가 없는 분석은 C 가 근거를 전부 버린다.
2. **`C_COMPUTE_URL` / `C_COMPUTE_TOKEN`** — 비어 있으면 backend 가 C 를 아예 호출하지
   않고 계산 결과를 미준비로 내린다. `verify-deployment.sh` 의 `backend-compute` 가
   이 상태를 잡는다.

한 사용자를 화면까지 온전히 보내려면 **세 가지를 모두** 켠 뒤 그 사용자의 저장소를
전부 재분석해야 한다. 저장소마다 Registry 가 섞이면 C 가 `MIXED_RULE_PACK` 으로
계산을 건너뛴다.

---

## 8. 되돌리기

`ANALYSIS_ATTRIBUTE_AUTHORS=false` 로 두고 analysis-worker 를 재시작한다. 그 뒤
분석부터 `commit_sha` 가 다시 비고, 이미 쌓인 `analysis_evidence_commit` 행은 남는다.

`V19` 마이그레이션은 되돌리지 않는다. 값 집합을 늘린 것뿐이라 기존 행에 영향이 없고,
되돌리면 이미 저장된 `OTHER_AUTHOR` 행이 제약을 위반하게 된다.
