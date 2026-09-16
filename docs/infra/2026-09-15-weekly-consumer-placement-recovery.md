# Weekly Trend Consumer 배치 복구

## 배경

2026-09-15 운영 확인에서 데이터 서버의
`gitjob-data-weekly-trend-consumer-1`이 종료 코드 75로 반복 재시작했다.
컨테이너는 Kafka의 기존 주간 완료 이벤트를 읽은 뒤 빈
`WEBHDFS_DATANODE_HOSTS` 때문에 NameNode의 DataNode redirect를 허용하지 못했고,
`INPUT_ADAPTER_UNAVAILABLE`을 재시도 상태로 처리했다.

서비스 서버에는 host network와 Tailscale WebHDFS 경로를 사용하는 정식 Consumer가
별도로 실행 중이었다. 따라서 데이터 서버 컨테이너는 필요한 이중화가 아니라 잘못
남은 중복 Consumer였다.

## 원인

기본 `compose.yaml`은 `weekly-trend-consumer`를 `data` profile에 둔다. 데이터
클러스터 override가 이를 `profiles: [weekly]`로 바꿨지만 Compose는 sequence를
병합하므로 실제 profile은 `[data, weekly]`가 됐다. 그 결과 Jenkins의 `data` 배포가
구형 Consumer를 다시 생성했다.

기존 회귀 테스트는 YAML block에 `[weekly]` 문자열이 있는지만 검사했기 때문에 실제
Compose 병합 결과를 검증하지 못했다.

## 변경된 배포 계약

- 데이터 클러스터와 서비스 weekly override는 `profiles: !override [weekly]`로
  상속된 `data` profile을 완전히 교체한다.
- Jenkins 배포는 서비스 서버에도 Worker 이미지를 빌드하고
  `compose.weekly-host.yaml`로 Weekly Consumer를 기동한다.
- 데이터 서버 배포는 기존 Weekly Consumer를 명시적으로 중지·제거한 후 data stack을
  올린다. 이 정리는 컨테이너가 없어도 성공하며 HDFS volume이나 export 파일을
  삭제하지 않는다.
- 배포 검증은 서비스 서버 Consumer의 실행 상태와 데이터 서버에서의 부재를 각각
  확인한다.

## 필요한 서비스 서버 환경변수

`.env.service`에는 다음 값이 필요하다. endpoint는 인터넷 공개 주소가 아니라 두
서버에서 접근 가능한 Tailscale 주소를 사용한다.

```text
WEEKLY_CONSUMER_KAFKA_BOOTSTRAP
WEEKLY_CONSUMER_GROUP
WEEKLY_CONSUMER_WEBHDFS_URL
WEEKLY_CONSUMER_DATANODE_HOSTS
WEEKLY_CONSUMER_POSTGRES_HOST
```

offset reset 기본값은 `earliest`, WebHDFS 사용자는 `hadoop`, PostgreSQL port는
`5432`다.

## 배포 및 확인

Jenkins에서 `Build with Parameters`를 선택하고 `DEPLOY_ENABLED=true`로 실행한다.
성공 조건은 다음과 같다.

1. 서비스·데이터 서버 HEAD가 배포한 `develop` SHA와 같다.
2. 데이터 서버에 `gitjob-data-weekly-trend-consumer-1`이 없다.
3. 서비스 서버의 `gitjob-service-weekly-trend-consumer-1`만 `running`이다.
4. 데이터 profile의 실제 Compose 렌더링에 `weekly-trend-consumer`가 없다.
5. HDFS, Spark, Collector, Worker와 기존 서비스 health가 유지된다.

## 별도 운영 선행조건

배치 위치 복구와 실제 Trend 계산 준비는 구분한다. Weekly Consumer가 새 완료 이벤트를
처리하려면 호환되는 `PUBLIC_GITHUB` snapshot과 서비스 서버의 read-only
`C_WEEKLY_EXPORT_DIR` 산출물이 먼저 있어야 한다. 기존 Kafka offset 0 이벤트의 재처리나
consumer group offset 변경은 이 배포에서 자동 수행하지 않는다.
