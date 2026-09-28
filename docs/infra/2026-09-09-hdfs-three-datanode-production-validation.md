# S15P21E102-175 HDFS 3-DataNode Production Validation

- Jira: `S15P21E102-175`
- 대상: `J15E102A` / `j15e102a.p.ssafy.io`
- 검증일: 2026-09-09 (KST)
- 기준 develop: `0a1e546df68dc7806779b3f3867dd05987b12087`
- MR: !47 merged
- 배포 checkout: `/home/ubuntu/workspace/S15P21E102`

## 적용 범위

MR !47 merge 후 서버 checkout을 `develop` 기준으로 fast-forward하고, 기존
NameNode/DataNode-1을 유지한 채 `hdfs-datanode2`와 `hdfs-datanode3`만
targeted 기동했다.

```bash
docker compose --project-directory . --env-file .env.data \
  -f Infra/compose/compose.yaml -f Infra/compose/compose.ec2-data.yaml \
  --profile data up -d --no-build --no-deps --no-recreate \
  hdfs-datanode2 hdfs-datanode3
```

신규 volume 권한 초기화 helper도 동일하게 `--no-build --no-deps --no-recreate`
옵션으로 별도 실행했다. NameNode, DataNode-1, Jenkins 및 기타 서비스는
재기동/recreate하지 않았다.

## DataNode 등록 결과

| 항목 | 결과 |
|---|---|
| 적용 전 Live DataNode | 1 |
| 적용 후 Live DataNode | 3 |
| 기존 NameNode container | `9d2b50433641` 유지 |
| 기존 DataNode-1 container | `17fd02226361` 유지 |
| DataNode-2 container | `1dcf132b191a` |
| DataNode-3 container | `f60db1a96926` |
| 관리 포트 | `9864`, `9866`, `9867` 모두 충돌 없음 |
| safe mode | OFF |
| `dfs.client.use.datanode.hostname` | `false` (현재 Compose 내부 네트워크에서 확인) |

세 DataNode의 `datanodeUuid`와 cluster ID는 다음과 같으며 UUID는 모두 다르다.

| 노드 | datanodeUuid | clusterID |
|---|---|---|
| DataNode-1 | `b1ce2dcf-e408-48e0-aa8c-31599b8a3d07` | `CID-47d1b1a7-56b7-480f-861c-0a3b9459a867` |
| DataNode-2 | `dc3991a5-3b4d-4d76-831c-3be8b3353f02` | `CID-47d1b1a7-56b7-480f-861c-0a3b9459a867` |
| DataNode-3 | `32f7bc8d-a77f-48fd-b5e4-04fb3cafb37c` | `CID-47d1b1a7-56b7-480f-861c-0a3b9459a867` |

실제 volume은 다음 네 개로 확인했다.

- `gitjob-data_hdfs-namenode-data`
- `gitjob-data_hdfs-datanode-data` (기존 DataNode-1)
- `gitjob-data_hdfs-datanode2-data`
- `gitjob-data_hdfs-datanode3-data`

## 기존 데이터 read 및 fsck

다음 HDFS 경로의 listing/read를 확인했다.

- `/gitjob`
- `/gitjob/raw/gharchive`
- `/gitjob/parquet/github/repo_activity/period=2026-08`
- `/gitjob/analysis_input/github/repo_snapshot`

대표 파일의 HDFS read도 확인했다.

- GH Archive Raw `2026-08-01-0.json.gz`: gzip header read 성공
- Repo Activity Parquet `part-00000...snappy.parquet`: `PAR1` header read 성공
- Repo Snapshot `s15p21e102-114-phase1-20260907-fix-001/_SUCCESS.json`: JSON read 성공

`hdfs fsck /gitjob -files -blocks -locations` 최종 결과:

- filesystem: `HEALTHY`
- missing blocks: `0`
- corrupt blocks: `0`
- missing replicas: `0`
- mis-replicated blocks: `0`

신규 노드 등록 직후 NameNode report에서 under-replicated block 110개가 일시
관찰됐으나, block report 수렴 후 최종 fsck에서는 missing/corrupt/missing
replica가 모두 0이었다.

## replication=2 및 장애 read 테스트

테스트 전용 경로 `/gitjob/tmp/hdfs-three-datanode-validation/`에 작은 파일을
생성했다. 기본 replication=1에서 단일 block이 한 DataNode에 저장된 것을 확인한
뒤 해당 파일에만 `hdfs dfs -setrep -w 2`를 적용했다.

- replication=2 적용: 성공
- fsck block location: 서로 다른 DataNode 2개
- under-replicated: `0`
- 신규 DataNode-2 pause 중 테스트 파일 read: 성공
- DataNode-2 unpause 후 health: `healthy`
- 테스트 경로: 검증 후 삭제 완료

기존 `/gitjob` 전체의 replication은 변경하지 않았다.

## 용량 및 한계

최종 `dfsadmin -report`는 논리 DataNode 3개의 합산 capacity를 약 `926.79 GB`로
보고했다. 실제 동일 물리 디스크의 host `df -h`는 다음과 같다.

| 시점 | size | used | available | use% |
|---|---:|---:|---:|---:|
| 적용 전 | 309G | 27G | 283G | 9% |
| 적용 후/검증 후 | 309G | 28G | 282G | 9% |

용량 판단 기준은 host `df`이며, `dfsadmin -report` capacity는 동일 파일시스템을
논리적으로 세 번 표시할 수 있으므로 참고값이다. DataNode별
`dfs.datanode.du.reserved` 적용은 후속 이슈로 분리한다. 이 구성은 동일 물리
호스트 장애를 분산하는 HA 구성이 아니다.

신규 DataNode 최근 로그에서 `FATAL`, `ERROR`, `Exception`, `WARN` 패턴은
확인되지 않았다.
