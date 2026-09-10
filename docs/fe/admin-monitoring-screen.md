# Admin System Monitoring 화면

- Jira: `S15P21E102-210` (parent Story `S15P21E102-52`)
- API: `S15P21E102-209` → [Admin Monitoring API](../be/admin-monitoring-api.md)
- Visual Source of Truth: `GitJob Admin Monitoring v2.dc.html`
- 기준일: 2026-09-10
- 상태: **구현됨 · 브라우저 확인됨(정상·미설정 경로) · 실제 BE 연결 `Runtime verification pending`**

## 1. 위치

```
FE/src/features/admin/
  layouts/AdminLayout.tsx          ADMIN 헤더 + Monitoring / Technology Registry
  monitoring/
    api/monitoringApi.ts           BE 응답 타입과 호출
    model/topology.ts              구조 모델
    model/topology.config.ts       현재 topology 선언  ← 인프라가 바뀌면 여기만 고친다
    model/thresholds.ts            CPU/Memory 80·90, Disk 85·90
    model/monitoringState.ts       도메인 상태와 UI fallback 매핑
    adapter/toMonitoringView.ts    config + 응답 → 뷰모델
    adapter/toChartData.ts         서버별 시계열 → 그래프 한 줄
    components/                    8개 섹션
    ui/                            상태 배지 · 값 표기 · 선 그래프 · 서식
    pages/SystemMonitoringPage.tsx
```

라우트는 `/admin`이며 index가 Monitoring이다. `/admin/technology-candidates`는 티켓 14에서
쓰던 경로를 그대로 유지하고 `AdminLayout` 아래로 옮겼다 — 경로를 바꾸면 팀이 공유한 링크가
깨진다.

## 2. 인프라가 바뀔 때 고칠 곳

**컴포넌트에는 서버 이름도, 서비스 배치도, 개수도 없다.** 전부
`model/topology.config.ts`에서 온다. 서버를 늘리는 절차는 다음 두 단계다.

1. `Infra/monitoring/prometheus/targets/node-exporter.yml`에 node-exporter target과
   `cluster`/`role`/`node`/`host` 라벨 추가
2. `topology.config.ts`의 `servers`에 항목 추가 (`role`이 1번의 라벨과 같아야 한다)

컴포넌트와 BE 계약은 건드리지 않는다. `S15P21E102-207`의 HDFS·Spark 2호스트 확장이 실제로
이 경로를 쓴다.

config와 지표를 잇는 열쇠는 `role`(같은 role에 서버가 둘 이상이면 `instance`)이다. 호스트명과
IP는 열쇠로 쓰지 않는다 — 그것들이 바뀌기 때문이다.

**config에 없는데 Prometheus가 아는 서버는 지도에 경고로 드러난다.** 조용히 버리지 않는다.
서버가 추가됐는데 config를 갱신하지 않은 상황이 그 경고로 보여야 하고, 감추면 운영자는
화면에 보이는 서버가 전부라고 믿는다.

## 3. 도메인 상태와 공용 UI 상태를 구분한다

`shared/ui/StateCard`의 `StateKind`는 공용 어휘이고 그 파일은 값을 임의로 늘리지 말라고 못
박아 두었다. 모니터링의 `PrometheusState`는 층이 다르다 — 운영자가 "무엇이 고장났고 누가
고쳐야 하는가"를 알아야 하는 이 화면만의 사실이다. **`StateKind`를 확장하지 않고, 도메인
상태를 UI 상태로 치환하지도 않는다.**

| 도메인 상태 | 화면 표기 | 고칠 사람 |
|---|---|---|
| `CONNECTED` | 정상 | — |
| `NOT_CONFIGURED` | 연결 설정 없음 | 배포 담당자 (`PROMETHEUS_BASE_URL`) |
| `UNREACHABLE` | 연결 실패 | 운영자 (관리자망·Prometheus) |
| `INVALID_RESPONSE` | 응답 오류 | 운영자 (주소·버전) |

전용 `PrometheusStateBadge`와 화면 상단 배너가 이 네 값을 그대로 보여준다. 공용
`StateCard`를 재사용해야 하는 empty/error 영역에서만 `stateCardKindFor()`로 UI fallback을
고르고(`NOT_CONFIGURED`→`PREPARING`, 나머지→`ERROR`), 그 카드 본문에도 도메인 상태 이름과
설명을 함께 남긴다.

상태 점(`UpDot`)은 `boolean | null` 세 값이다. `null`은 "모른다"이고 회색이다. Prometheus에
닿지 못한 동안 빨간 점을 켜면 화면이 없는 장애를 만든다. 같은 이유로 `NOT_CONFIGURED`는
`false`가 아니다.

## 4. 값이 없을 때

- 수치는 `0`이 아니라 `—`. `0`은 "측정했더니 0"이라는 다른 사실이다.
- 그래프는 0으로 채운 점을 만들지 않는다. 평평한 0 선은 장애가 아니라 한가한 서버로 읽힌다.
- Disk 합계는 서버 한 대라도 용량을 못 읽으면 만들지 않는다. 반쪽 합계는 실제보다 작은
  사용량을 주장하고 그것이 "여유 있다"는 오판으로 이어진다.
- 네트워크 합계도 IN·OUT 중 하나만 있으면 만들지 않는다.
- `kafka.up`이 `null`이면 "죽었다"가 아니라 "아직 재보지 않았다"로 표시한다.

## 5. 디자인에 있지만 렌더하지 않는 것

확정 디자인 파일 상단에 `DESIGN MOCK DATA ONLY. DO NOT COPY THESE VALUES INTO PRODUCTION
FRONTEND`가 적혀 있다. 아래는 근거가 없어 옮기지 않았다.

| 디자인 | 이유 |
|---|---|
| Recent Events 5줄 | Alertmanager 미도입, API에 이벤트 필드 없음 → 표 골격 + PREPARING |
| `Uptime 41d 6h` | uptime을 주는 지표가 API에 없다 |
| CPU 보조의 `load 0.9` | `node_load1`이 S15P21E102-205 수집 확인 목록에 없다 |
| `job-postings · 3 partitions` | 실제 토픽은 `gitjob.*`이고 partition 수를 주는 API가 없다 |
| Grafana `Dashboards 4 · Datasource OK` | Grafana API 호출이 이번 범위 밖 → 링크만 노출 |
| HDFS 복제 계수 | `Infra/`에 `dfs.replication` 설정이 없다 → config에서 `null` |
| 서비스 칩별 개별 상태 | 컨테이너 UP/DOWN exporter(cAdvisor) 없음 → 호스트 상태를 따른다 |

Infrastructure Map은 디자인의 픽셀 좌표(1174x372)를 쓰지 않는다. 그 좌표는 서버가 정확히
두 대일 때만 맞고 세 대가 되면 선이 허공을 가리킨다. 대신 논리 순서(`column`)와 격자·띠로
옮겼다 — 왼쪽에서 오른쪽으로 흐르고 아래에서 수집한다는 의미는 같고 서버 수에 종속되지
않는다.

## 6. 갱신 주기

| 대상 | 주기 | 이유 |
|---|---|---|
| `overview` | 30초 | 확정 디자인의 `Auto refresh ON · 30s` |
| 시계열 | 5분 | BE 범위가 60분·5분 step이라 더 자주 읽어도 같은 점이 온다 |

재시도는 `retry: 1`로 못 박았다. 운영 화면은 실패를 빨리 드러내야 한다 — 조회가 실패했는데
계속 "불러오는 중"이면 기다리면 되는 상황인지 지금 손을 써야 하는 상황인지 알 수 없다.
같은 이유로 값이 없고 오류가 남아 있으면 로딩보다 오류를 먼저 보여준다.

브라우저가 오프라인으로 판정되면 react-query는 요청을 보내지 않고 쿼리를 멈춘다
(`fetchStatus === 'paused'`, 기본 `networkMode: 'online'`). 그때는 로딩 문구를 "네트워크 연결을
기다리는 중"으로 바꿔 원인을 서버가 아닌 연결로 가리킨다.

## 7. 확인한 것과 확인하지 못한 것

### 로컬에서 확인됨

- `npm run typecheck`, `npm run lint` 통과
- Vite dev + **로컬 stub BE**(저장소 밖 scratchpad, 커밋하지 않음)로 브라우저 확인
  - 정상 경로: 8개 섹션 렌더, 콘솔 오류 없음, 임계치 색 동작(84%가 caution `oklch(0.62 0.13 75)`),
    레이아웃 계산값이 디자인과 일치(`.gj-mon-charts` 1.35fr/1fr, `.gj-mon-row`
    `190px repeat(4,1fr) 120px`, `.gj-split` 본문+372px)
  - `NOT_CONFIGURED` 경로: 모든 수치 `—`, 배지 `UNKNOWN`, 링크 비활성, **가짜 숫자 0건**
  - config에 없는 target 1개를 넣었을 때 지도에 경고 표시
  - 오프라인 일시정지 상태에서 로딩 문구가 원인을 바르게 가리킴

### 미확인 — `Runtime verification pending`

- **실제 BE `/api/v1/admin/monitoring/**` 연결.** 확인한 것은 stub 응답이며 실제 BE는
  아직 돌려보지 않았다.
- `UNREACHABLE` / `INVALID_RESPONSE` 경로. BE를 내린 상태에서는 이 브라우저 pane이
  오프라인으로 판정되어 react-query가 쿼리를 멈추고(`failureCount: 0`) 실패까지 도달하지
  않았다. 코드 경로는 있으나 런타임으로 확인하지 못했다.
- 비ADMIN 계정의 401/403 화면.
- 실제 라벨(`role`·`node`·`host`)이 config의 `role`과 맞는지. 어긋나면 서버 카드의 지표가
  비고 Server Detail에 "수집 대상에서 찾지 못했습니다"가 뜬다.

## 8. 후속

- `S15P21E102-209` 병합 후 실제 BE로 위 미확인 항목 확인
- Alertmanager 도입 시 Recent Events 공급원 연결
- HDFS/Spark exporter 도입 시 `coverage`가 `COLLECTED`로 오고 카드에 수치 연결
- `node_load1` 존재 확인 후 CPU 보조 표기 추가
- 기존 `TechnologyCandidatePage`가 Final v2 브랜드 토큰을 쓰지 않아 Monitoring과 톤이
  다르다. 이번 범위 밖이며 별도 티켓이 필요하다.
