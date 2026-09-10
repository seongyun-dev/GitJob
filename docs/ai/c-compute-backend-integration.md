# B ↔ C compute 연동 (미착수)

> 아래 운영 상태는 2026-09-09 관측 기록이다. 2026-09-10 -199/-88 변경은 로컬에서만
> 검증했으며, 새 버전은 public Registry V3와 C Compute 003까지 필요하다. 과거의
> `schema_version=1` 또는 `/ready=200` 기록을 새 코드의 배포 인수로 사용하지 않는다.
> 현재 실행 설정은 [런타임](c-compute-runtime.md), [DB Registry](../data/technology-registry-db.md),
> [검토 큐](c-registry-review.md)를 따른다. 실제 서버 상태는 배포 시 다시 확인해야 한다.

C compute 런타임은 운영에서 준비를 마쳤다. 계산을 실제로 돌리려면 입력을 넣어 주는 쪽이
필요한데 그것이 아직 없다. 이 문서는 무엇이 되어 있고 무엇이 남았는지 남긴다.

계약 자체는 [C 계산 실행·저장 계약](c-compute-runtime.md)이 원본이다. 여기서는 연동에
필요한 것만 다룬다.

## 현재 준비된 것 (2026-09-09)

| | 상태 |
| --- | --- |
| `c_compute` 스키마 | 적용됨. `event`·`snapshot`·`head`·`schema_version`, `schema_version=1` |
| `C_COMPUTE_TOKEN` | 서비스·데이터 호스트에 **같은 값**으로 설정됨 (48자) |
| `GET /ready` | `200 READY`, `registry_version=registry-20260908.1` |
| `verify-deployment.sh` | `worker-ready OK` |

`/internal/v1/c/*`는 이제 503을 반환하지 않는다. 다만 **호출하는 쪽이 없어 아무 계산도
일어나지 않는다.**

## 남은 것

입력 경로가 두 가지인데 둘 다 연결되어 있지 않다.

### 경로 1: B 백엔드가 C 를 호출한다 (미구현)

`docs/ai/c-compute-runtime.md`가 정의한 역할 분담은 이렇다. B는 사용자 인증과 소유권을
확인하고, C의 결과를 서비스 API로 전달한다. **B는 계산을 다시 구현하지 않는다.**

현재 BE에는 C 클라이언트 코드가 없다. `C_COMPUTE_URL`과 `C_COMPUTE_TOKEN`을 참조하는
것은 `AI/worker` 내부 클라이언트뿐이다.

붙일 때 필요한 것:

- BE에서 worker로의 HTTP 클라이언트. 모든 요청에 `Authorization: Bearer <C_COMPUTE_TOKEN>`
- `compose.yaml`의 backend 서비스에 `C_COMPUTE_TOKEN`과 `C_COMPUTE_URL` 전달.
  **지금은 backend에 전달되지 않는다.** 토큰은 이미 `.env.service`에 있으므로 compose
  매핑만 추가하면 된다
- 서비스 호스트와 데이터 호스트의 `C_COMPUTE_TOKEN`이 **같은 값이어야 한다.** 어긋나면
  worker가 `401 INTERNAL_AUTH_REQUIRED`를 반환한다
- `C_COMPUTE_URL`은 호스트가 갈려 있다는 점에 주의한다. worker는 데이터 호스트에 있고
  backend는 서비스 호스트에 있으므로, `.env.example`의 기본값 `http://worker:8080`은
  같은 Compose 네트워크를 전제한 로컬 값이다. 운영에서는 데이터 호스트 주소여야 한다

개인 결과 조회에는 `user_id`가 필요하며, 그 값은 **B가 인증한 사용자**여야 한다.
브라우저가 지정하는 값이 아니다.

### 경로 2: 완료 manifest 자동 감시 (미설정)

`C_INTAKE_CONFIG`가 비어 있어 intake 러너가 뜨지 않는다. 이 경로는 HTTP가 아니므로
토큰과 무관하게 동작한다.

켜려면 `c-intake-config/v1` JSON 경로와 mount가 필요하다.
[c-compute-runtime.md](c-compute-runtime.md)의 "Compose에서 반드시 추가할 mount"와
"입력 설정 예"를 따른다. 신뢰된 입력·설정은 read-only로, 공개 checkpoint는 쓰기 가능하게
mount한다.

## 어느 쪽을 먼저 붙일지

경로 2가 먼저다. B 연동 없이도 공고 완료 입력만으로 cohort와 수요 Snapshot이 쌓이기
시작하고, 그러면 B가 붙을 때 조회할 결과가 이미 있다. 반대 순서면 B를 붙여도 읽을
Snapshot이 없다.

## 확인 방법

연동 후에는 `verify-deployment.sh`의 `worker-ready`가 아니라 실제 결과로 확인한다.
`worker-ready`는 스키마와 토큰 준비까지만 본다.

```
GET /internal/v1/c/intake/status   # 자동 감시의 활성/실행 여부, 최근 poll 결과
GET /internal/v1/c/registry        # 실행 중인 Registry Snapshot
```

`docs/ai/c-compute-runtime.md`의 "상태 확인과 복구 순서"를 따른다.
