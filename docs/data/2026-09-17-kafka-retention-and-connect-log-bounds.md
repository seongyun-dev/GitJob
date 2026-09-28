# github.events retention 확정과 Kafka Connect 로그 상한

- Jira: `S15P21E102-258`
- 기준일: 2026-09-17
- 범위: `github.events` retention 정책 확정 및 IaC 정렬, Kafka Connect worker 로그 bounded rotation
- 이 문서는 Production 변경 기록이 아니다. Production topic config와 Connect 컨테이너는 이 시점에 건드리지 않았다

## 1. retention 값이 세 군데에서 달랐다

2026-09-14 디스크 고갈 장애 이후 `github.events`의 retention이 서로 다른 세 값으로 남아 있었다.

| 출처 | 값 | 성격 |
|---|---|---|
| `Infra/scripts/kafka-topics.sh` (IaC) | `-1` | 전 topic 공통 기본값 |
| `S15P21E102-258` Jira 현재 상태 | `12h` | 장애 대응 중 적용한 임시 복구값 |
| Production Runtime | `24h` (`86400000`) | `DYNAMIC_TOPIC_CONFIG` |

Runtime 값이 어디에도 기록되어 있지 않았다 — `origin/develop` 전체에서 `86400000`·`43200000` 검색 결과 0건이었다. 즉 12h → 24h 변경은 근거 없이 남은 drift였다.

drift가 보이지 않았던 이유는 `kafka-topics.sh`가 `--create --if-not-exists`만 쓰기 때문이다. 이미 존재하는 topic의 config는 읽지도 고치지도 않으므로, 손으로 바꾼 값은 영구히 남고 IaC는 그것을 모른다.

## 2. 확정

**`github.events` 정식 운영값은 24h (`retention.ms=86400000`)다.** 소유자 결정(2026-09-17).

| 구분 | 값 |
|---|---|
| 이전 IaC 기본값 | `-1` (무기한) |
| 장애 대응 임시값 | `12h` — **운영 정책이 아니다** |
| **최종 운영값** | **`86400000` (24h)** |

근거는 세 가지다.

- **replay 여력.** 24h면 C1이 하루를 통째로 밀려도 재다운로드 없이 따라잡을 수 있다. 이 topic이 실제로 필요로 하는 replay 범위는 그것이다.
- **disk safety.** `github.events`는 publisher가 얼마나 빨리 도는지 외에 아무것도 크기를 제한하지 않는 유일한 topic이다. `-1`은 backlog 복구 시 발행량 전체가 영구히 남는다는 뜻이다.
- **Kafka와 DataNode4가 같은 root를 공유한다.** 2026-09-17 실측으로 service host `/`는 309 GB 중 220 GB 사용이고, 그중 **192.5 GB가 HDFS DataNode4 볼륨**이다. Kafka 로그 디렉터리는 40 MB에 불과하다. 남은 90 GB는 Kafka 증가분과 HDFS 증가분이 함께 먹는다. 2026-09-14의 `No space left on device`가 재발하지 않으려면 Kafka 쪽에 천장이 있어야 한다.

다른 topic은 `-1`을 유지한다. 이들은 작고, offset 0부터의 replay가 소비 방식 그 자체다.

## 3. IaC 정렬

`Infra/scripts/kafka-topics.sh`의 topic 표가 `name:partitions` 2열에서 `name:partitions:retention.ms` 3열이 되었다. 전역 `RETENTION_MS` 변수는 제거했다 — 이제 retention은 topic마다 다르므로 하나의 값으로 표현할 수 없다.

```text
github.events:6:86400000
so.raw:3:-1
jobs.collected:3:-1
gitjob.repository-analysis.requests.v1:3:-1
gitjob.repository-analysis.results.v1:3:-1
gitjob.repository-analysis.dlq.v1:3:-1
gitjob.repo-activity-weekly.completed.v1:1:-1
```

## 4. 기존 topic에 적용·검증하는 canonical 방법

topic 생성만으로는 drift를 고칠 수 없으므로 세 모드 전부가 live `retention.ms`를 표와 대조한다.

```bash
# 보고만 한다. 아무것도 바꾸지 않는다
Infra/scripts/kafka-topics.sh --check

# 없는 topic을 만들고, retention drift는 DRIFT로 보고만 한다
Infra/scripts/kafka-topics.sh

# 기존 topic의 retention까지 표에 맞춘다 (kafka-configs --alter)
Infra/scripts/kafka-topics.sh --enforce-retention
```

출력 구분:

- `OK` — partition 수와 `retention.ms`가 모두 표와 같다
- `DRIFT` — partition은 맞고 `retention.ms`만 다르다. exit 1. `--enforce-retention`으로 고친다
- `ALTER` — `--enforce-retention`이 실제로 정렬한 항목
- `MISMATCH` — partition 수가 다르다. **자동 수정하지 않는다** (아래)

retention은 고치고 partition은 고치지 않는 것이 의도적이다. `--alter retention.ms`는 레코드를 얼마나 오래 두는지만 바꾸므로 분포도 순서도 건드리지 않는다. partition 수를 올리면 모든 key가 rehash되어 per-key ordering이 깨지고, 내리는 것은 Kafka가 아예 못 한다.

override가 없는 topic은 broker default(`log.retention.hours=168`)를 상속하므로 `-1`과 다르다. 그래서 override 부재는 `<broker-default>`로 보고하며, 비교를 조용히 통과시키지 않는다.

`existing_retention` 파싱은 2026-09-17 Production 실출력으로 검증했다 — `github.events → 86400000`, `so.raw → -1`, `gitjob.connect.configs → <broker-default>`. 현재 Production에 `--check`를 돌리면 7개 topic 전부 `OK`다.

## 5. Kafka Connect 로그 상한

### 5.1 무엇이 열려 있었나

Connect worker가 쓰던 appender는 image 기본값이었다.

```properties
log4j.appender.appender=org.apache.log4j.DailyRollingFileAppender
log4j.appender.appender.DatePattern='.'yyyy-MM-dd-HH
log4j.appender.appender.File=${kafka.logs.dir}/connect-service.log
```

`DailyRollingFileAppender`는 log4j 1.x에서 **`MaxFileSize`도 `MaxBackupIndex`도 지원하지 않는다.** 매시 파일을 하나 만들고 **아무것도 지우지 않는다.** 2026-09-14 Rebootstrapping 폭주가 여기에 4.54 GiB를 썼다.

compose의 `logging: json-file (max-size 10m, max-file 3)`은 이 경로를 막지 못한다. 그것은 컨테이너 stdout 캡처를 제한할 뿐이고, `/kafka/logs`는 별개의 파일 집합이다.

### 5.2 적용한 정책

`Infra/cdc/connect-log4j.properties`를 저장소에서 관리하고 `/kafka/config/log4j.properties`로 read-only bind mount 한다.

```properties
log4j.appender.appender=org.apache.log4j.RollingFileAppender
log4j.appender.appender.File=${kafka.logs.dir}/connect-service.log
log4j.appender.appender.MaxFileSize=10MB
log4j.appender.appender.MaxBackupIndex=9
```

**총 상한 100 MB** (활성 1 + 백업 9). 시간 경계는 포기했다 — 디스크를 지켜준 적이 없는 속성이고, 이 log4j에서 size와 count를 동시에 제한할 수 있는 appender는 `RollingFileAppender`뿐이다.

### 5.3 왜 env var가 아니라 파일인가

Debezium entrypoint의 `CONNECT_LOG4J_*` 경로는 property 이름을 **전부 소문자로 바꾼다**(`tr '[:upper:]' '[:lower:]'`). log4j 1.x는 `MaxFileSize`를 bean property 이름으로 찾으므로 `maxfilesize`는 파일에 기록되고 **조용히 무시된다.** env var로 넣으면 설정된 것처럼 보이면서 아무것도 제한하지 않는다.

read-only mount가 안전한 이유는 entrypoint가 기본값을 `cp -rn`(no-clobber)로 복사하고, 이 파일을 `sed -i`로 고치는 분기는 `CONNECT_LOG4J_*` 또는 `LOG_LEVEL`이 설정된 경우에만 실행되는데 이 서비스는 둘 다 설정하지 않기 때문이다.

### 5.4 왜 10 MB × 10인가

2026-09-17 운영 worker 실측: 연속 21개 시간 파일(`2026-09-16-06` ~ `2026-09-17-01`)이 각각 132,985~133,869 B였다. 시간당 약 133 KB, 하루 약 3.2 MB다.

- `MaxFileSize=10MB` — compose의 json-file `max-size: 10m`과 같은 수. 이 컨테이너의 로그 상한이 서로 다른 두 숫자가 되지 않는다
- `MaxBackupIndex=9` — 1 + 9 = **100 MB 고정 천장**

100 MB는 실측 속도로 약 31일치이므로 평상시 보존 기간은 기존 시간 회전보다 길어진다. 장애가 재발해도 같은 폭주가 100 MB에서 멈춘다 — 실제로 쓴 4.54 GiB의 **46분의 1**이고, 2026-09-17 root 여유 90 GB의 0.1%다. 폭주 진단에는 최근 100 MB로 충분하다.

## 6. 검증

Production은 변경하지 않았다. 아래는 전부 일회성 컨테이너와 정적 검사다.

| 항목 | 결과 |
|---|---|
| `bash -n Infra/scripts/kafka-topics.sh` | PASS |
| topic 표 파싱 (7 entries, partitions/retention 형식) | PASS — `github.events` 86400000, 나머지 6개 `-1` |
| `existing_retention` 파싱 (Production 실출력 대조) | PASS — `86400000` / `-1` / `<broker-default>` 3경우 |
| `docker compose --profile core --profile app --profile ci config -q` | PASS |
| 렌더된 kafka-connect volume | `/home/ubuntu/.../Infra/cdc/connect-log4j.properties → /kafka/config/log4j.properties`, `read_only: true` |
| log4j 설정 적용 (일회성 `debezium/connect:3.4.3`, `--network none`) | PASS — 컨테이너 정상 기동, 마운트된 파일이 유효 설정, `log4j:ERROR`/`No appender` 0건 |
| rollover 상한 실증 (`MaxFileSize=4KB`, `MaxBackupIndex=2`로 축소) | PASS — `connect-service.log`, `.1`, `.2` **3개에서 멈춤**, 초과 백업 삭제됨 |
| `git diff --check` | exit 0 |

축소 실증은 같은 설정 형태에서 size 기반 rollover와 보존 개수 상한이 모두 동작함을 보인 것이다. 10MB × 10으로 확대하면 100 MB 천장이 된다.

## 7. Production 반영에 남은 일

이 커밋은 코드·config·문서만 바꾼다. 아래는 배포 후 운영자가 수행한다.

1. develop 배포
2. `Infra/scripts/kafka-topics.sh --check`로 drift 재확인 (현재 예상: 7 topic 전부 `OK`)
3. `kafka-connect` 컨테이너 재생성 — bind mount는 재생성 시에만 적용된다. `logging` 외 다른 설정은 바뀌지 않는다
4. 재생성 후 `/kafka/logs`에 `connect-service.log`만 있고 `connect-service.log.2026-*` 시간 파일이 더 생기지 않는지 확인. 기존 시간 파일은 새 appender가 지우지 않으므로 운영자가 판단해 정리한다
5. `analysis-outbox` connector/task RUNNING 재확인

`S15P21E102-258`은 위가 끝나기 전에는 완료 처리하지 않는다.

## 8. Rollback

두 변경은 서로 독립이므로 따로 되돌린다.

### 8.1 Connect 로그 상한

컨테이너 재생성만으로 적용되고 재생성만으로 풀린다. 상태를 남기지 않는다.

```bash
# compose에서 이 서비스의 volumes 항목만 제거하고 재생성하면 image 기본
# DailyRollingFileAppender로 돌아간다. 이미 쌓인 파일은 그대로 남는다.
docker compose ... up -d --no-deps --force-recreate --no-build kafka-connect
```

되돌릴 이유가 생긴다면 그것은 로그가 부족해진 경우다. 그때도 appender를 되돌리는
것이 아니라 `MaxBackupIndex`를 올리는 편이 낫다 — 되돌리면 상한이 다시 없어진다.

### 8.2 retention

```bash
# 값 자체를 되돌린다 (예: 이전 무기한 보존으로)
Infra/scripts/kafka-topics.sh  # 표를 되돌린 커밋을 배포한 뒤
# 또는 즉시 수동으로
kafka-configs.sh --bootstrap-server localhost:9092 --entity-type topics \
  --entity-name github.events --alter --add-config retention.ms=-1
```

**되돌릴 수 없는 것이 하나 있다.** retention을 줄이면 broker가 그 경계 밖 세그먼트를
지우고, 다시 늘려도 지워진 레코드는 돌아오지 않는다. 2026-09-17 기준
`github.events`는 이미 log-start == log-end로 비어 있으므로 24h 확정 자체가 새로
삭제하는 것은 없지만, **backlog 복구 중에 retention을 더 줄이는 변경은 발행한 데이터를
잃는다.** 복구 창에서는 retention을 만지지 않는다.

`--enforce-retention`은 `--add-config`만 쓰므로 `cleanup.policy`를 포함한 다른
override는 건드리지 않는다. partition 수는 어느 모드에서도 바뀌지 않는다.
