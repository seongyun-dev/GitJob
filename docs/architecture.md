# GitJob 시스템 아키텍처

> 상태: 목표 구조와 현재 구현 경계
>
> 기준일: 2026-09-10
>
> 현재 구현·배포·인수 구분은 [중간 통합 상태](2026-09-10-current-status.md)를 따른다.

## 1. 시스템 목적

GitJob은 사용자가 접근 권한을 부여한 GitHub public/private 저장소의 개발 활동을 기술별 Evidence로 변환한다. 단순히 기술 이름을 검색하거나 사용자의 숙련도를 추정하는 것이 아니라, 저장소·파일·라인·Commit·본인 기여 여부를 추적할 수 있는 근거를 제시한다. 이후 목표 직무의 채용공고 기술 수요와 공개 GitHub 활동 추세를 출처별로 비교해 Skill Gap과 학습 후보를 제공한다. private 저장소 원문은 시장 Trend에 사용하지 않는다.

요구사항의 핵심은 “판정 가능한 근거와 출처를 보여주는 것”이다. 기술 레벨은 숙련도나 채용 가능성의 확률이 아니며, 등록된 규칙에 의해 계산된 Repository Level과 Personal Level이다.

## 2. 논리 아키텍처

```text
┌──────────────────────────────┐
│ React Frontend                │
│ 화면·차트·분석 진행·Evidence │
└──────────────┬───────────────┘
               │ HTTPS / WebSocket(STOMP)
┌──────────────▼───────────────┐
│ Nginx                         │
│ SPA /api reverse proxy /ws    │
└──────────────┬───────────────┘
               │
┌──────────────▼───────────────┐
│ Spring Boot Backend           │
│ Auth · GitHub · Analysis API  │
│ Profile · Demand · Recommend  │
└───────┬──────────┬────────────┘
        │          │
        │          └──────────────┐
        ▼                         ▼
┌───────────────┐         ┌────────────────┐
│ PostgreSQL    │         │ Redis          │
│ 서비스·Snapshot│         │ 세션·캐시·보조 │
└───────┬───────┘         └────────────────┘
        │
        │ Kafka event / replay
        ▼
┌──────────────────────────────────────────┐
│ Kafka                                     │
│ source events · analysis requests/results │
└───────────────┬──────────────────────────┘
                ▼
┌──────────────────────────────────────────┐
│ Collector / Analysis Worker               │
│ GitHub·채용 수집                          │
│ 정규화·Evidence·집계·품질·DLQ             │
└─────────┬───────────────────┬────────────┘
          ▼                   ▼
┌────────────────┐    ┌────────────────────┐
│ HDFS / Parquet │    │ Spark / Hadoop     │
│ raw·장기 이력  │    │ batch·replay 처리  │
└────────────────┘    └────────────────────┘
```

## 3. 요청부터 결과까지

1. 사용자가 GitHub OAuth로 로그인하고 승인된 scope를 세션에 연결한다.
2. Backend가 접근 가능한 저장소를 페이지네이션으로 조회한다.
3. 사용자가 하나 이상의 저장소를 선택해 저장한다. 선택은 Snapshot이 아니라 다음 분석의 입력이다.
4. 분석 요청은 즉시 `analysisId`를 반환하고 Kafka 기반 비동기 Job으로 실행한다.
5. Collector가 Commit·파일·메타데이터를 수집해 raw layer에 저장하고, Worker가 Registry 규칙에 따라 기술 Fact와 Evidence를 판정한다.
6. 결과는 PostgreSQL에 Snapshot으로 저장하고, 원본·장기 데이터는 HDFS/Parquet에 둔다. PostgreSQL에는 원본 위치·버전·체크섬을 기록한다.
7. Frontend는 분석 상태를 polling 또는 push로 갱신하고, 완료된 분석의 프로필·근거·Skill Gap·추천을 조회한다.

## 4. 상태와 버전

모든 분석 결과는 최소한 다음 기준을 함께 가져야 한다.

| 기준 | 의미 |
|---|---|
| `analysisId` | 한 번의 분석 실행과 결과 Snapshot 식별자 |
| `commitSha` | 저장소별 분석 기준 Commit |
| `registryVersion` | 기술 Registry·판정 규칙 버전 |
| `parserVersion` | 소스 파서 버전 |
| `registryChecksum` | 분석 당시 Registry 무결성 확인값 |
| `datasetArtifact` | raw/result dataset 위치·버전·체크섬·행 수 |

코드가 바뀌면 새 분석 Snapshot을 만들고, Registry만 바뀌어도 과거 결과를 덮어쓰지 않고 재처리한다. Snapshot 비교에서는 변화 원인을 `CODE_CHANGE`, `CRITERIA_CHANGE`, `MIXED`, `UNKNOWN`으로 구분한다.

## 5. 설계 원칙

### 5.1 출처별 지표 유지

채용공고 건수/비율과 GitHub 기간별 활동은 단위·기간·분모가 다르다. 따라서 하나의 임의 가중치 점수로 합치지 않고 출처별 Fact Pack과 기준을 나란히 반환한다.

### 5.2 규칙 우선, AI 보조

레벨·Skill Gap·추천 후보는 Registry와 Evidence 규칙을 우선한다. AI는 확정된 Fact를 설명하는 보조 역할만 수행하며, 근거에 없는 수치·판정을 만들면 Rule Template으로 대체한다.

### 5.3 개인정보·원본 보호

GitHub Token은 암호화 저장하고 응답·로그·이벤트에 넣지 않는다. API는 원본 코드를 반환하지 않고 경로·라인·Commit permalink와 판정 정보를 제공한다. 사용자가 권한을 부여한 범위 밖의 저장소나 데이터를 수집하지 않는다.

### 5.4 재시도와 멱등성

분석 요청, Kafka consumer, HDFS archiver, 기술 정규화 sink, 시계열 집계 sink는 중복 이벤트가 발생해도 같은 결과를 만들 수 있어야 한다. 실패는 무한 재시도하지 않고 backoff·DLQ·checkpoint·replay로 처리한다.

## 6. 현재 레포와 목표 구조의 차이

현재 레포에는 `BE/`, `FE/`, `AI/`, `Infra/` 코드가 모두 존재한다. 다만 파일 존재와 로컬 테스트를 운영 서비스 인수로 해석하지 않고 아래 상태를 구분한다.

| 계층 | 현재 확인 상태 |
|---|---|
| FE | Vite/React 주요 화면 초안 존재, 실제 B/C 응답 연결 E2E 미검증 |
| BE | OAuth·저장소·분석 요청·Outbox와 일부 C 호출 계약 존재, Worker 완료 결과와 사용자 조회 인수 미완료 |
| AI/C | Registry·공고·추천·Trend·DB 저장·내부 API 로컬 구현, 이번 migration/이미지 운영 적용 미검증 |
| PostgreSQL·Redis·Kafka | 과거 core healthcheck·Kafka smoke 기록과 로컬 DB 검증 존재, 이번 변경 운영 인수는 별도 |
| HDFS·Spark | 과거 cluster·Parquet/Top20k 처리 기록 존재, 월별 운영 모집단과 새 계산 소비 경로는 별도 |
| Nginx·Jenkins·EC2 | 설정·배포 기록은 Infra 문서에 존재, 이번 브랜치 배포·장애 조치는 미검증 |

상세 실행 명령은 [Infra 문서](infra/README.md), 기능 계약은 [BE 문서](be/README.md)와 [Data 문서](data/README.md)를 기준으로 한다.

## 7. 원문 출처

- [요구사항 명세서](https://app.notion.com/p/db40dff912cf829e888b0141c8b5fd8d)
- [기능 명세서 작성](https://app.notion.com/p/d700dff912cf822ebaa981630e77682c)
- [와이어프레임](https://app.notion.com/p/4590dff912cf8278b234819b7b0bd5d5)
- [API 명세서](https://app.notion.com/p/5110dff912cf82049d59817bbbb6b670)
- [개발 환경](https://app.notion.com/p/77f0dff912cf8305a10b017245b40a78)
