# 지급 서버 사양 및 네트워크 실측

> 상태: 읽기 전용 실측 완료 / 서버 구성 미변경
>
> 점검일: 2026-08-31
>
> Jira: `S15P21E102-96`

## 1. 점검 목적

지급된 J15E102, J15E102A 두 EC2의 실제 사양, 기본 runtime 설치 상태,
filesystem과 네트워크 연결성을 기록한다. 이 결과는 이후 서비스/배포 환경과
Big Data 처리 환경의 배치, Docker Compose 도입, 성능 benchmark 조건을 정할 때
사용하는 기초 자료다.

이 문서는 서버 실측 결과를 기록하며 Hadoop/Spark cluster 구성이나 두 EC2의
애플리케이션 이중화를 확정하지 않는다. 실측 당시 상태와 이후 설계 방향은
[8. 실측과 설계 결정의 구분](#8-실측과-설계-결정의-구분)에서 분리한다.

## 2. 점검 일시와 범위

- 점검일: 2026-08-31
- 실측 시간대: 11:55~11:56 KST
- 접속 방식: 각 서버에 지급된 SSH key를 사용한 `ubuntu` 계정 접속
- 변경하지 않은 항목: 패키지, UFW, Security Group, SSH/사용자 권한, hostname,
  network 설정, 서비스 상태
- 수행 범위: OS/CPU/RAM/disk/runtime/UFW/network 조회, 양방향 ICMP 및 TCP 22
  연결 확인

PEM, password, token, credential의 내용은 읽거나 이 문서에 기록하지 않는다.
SSH key 파일은 repository 밖에서 관리하며 Git에 포함하지 않는다.

## 3. J15E102 실측

| 항목 | 실제 결과 |
|---|---|
| SSH | 접속 성공 |
| Hostname | `ip-172-26-11-108` |
| OS | Ubuntu 24.04.4 LTS |
| Kernel / Architecture | `6.17.0-1019-aws` / x86_64 |
| EC2 표기 | Amazon EC2 `t3.xlarge`, KVM full virtualization |
| CPU | Intel Xeon Platinum 8259CL 2.50 GHz |
| CPU topology | 4 vCPU, 1 socket, 2 cores/socket, 2 threads/core |
| RAM | 15 GiB; 점검 당시 사용 6.1 GiB, available 9.3 GiB |
| Swap | 없음 |
| Block device | 단일 EBS 320 GiB; 추가 volume 없음 |
| Root filesystem | ext4 309 GiB; 사용 2.6 GiB, 가용 307 GiB |
| Python | 3.12.3 (`/usr/bin/python3`) |
| pip3 | 명령 미확인 |
| Java/JDK | 표준 PATH·패키지·경로에서 미확인 |
| Docker | CLI·service·표준 패키지에서 미확인 |
| Docker Compose | v1/v2 명령 미확인 |
| UFW | active; 기본 inbound deny, outbound allow; 22/tcp 허용 |
| Interface / Private IP | `ens5`, `172.26.11.108/20`, MTU 9001 |
| Public FQDN IP | `3.38.105.183` |

Block device와 mount 구조:

```text
nvme0n1       320G disk
|-nvme0n1p1   319G part /
|-nvme0n1p15  106M part /boot/efi
`-nvme0n1p16  913M part /boot

/dev/root  ext4  309G  2.6G  307G  1%  /
```

UFW 확인 결과:

```text
Status: active
Default: deny (incoming), allow (outgoing), disabled (routed)
22       ALLOW IN    Anywhere
22 (v6)  ALLOW IN    Anywhere (v6)
```

## 4. J15E102A 실측

| 항목 | 실제 결과 |
|---|---|
| SSH | 접속 성공 |
| Hostname | `ip-172-26-12-59` |
| OS | Ubuntu 24.04.4 LTS |
| Kernel / Architecture | `6.17.0-1019-aws` / x86_64 |
| EC2 표기 | Amazon EC2 `t3.xlarge`, KVM full virtualization |
| CPU | Intel Xeon Platinum 8259CL 2.50 GHz |
| CPU topology | 4 vCPU, 1 socket, 2 cores/socket, 2 threads/core |
| RAM | 15 GiB; 점검 당시 사용 1.0 GiB, available 14 GiB |
| Swap | 없음 |
| Block device | 단일 EBS 320 GiB; 추가 volume 없음 |
| Root filesystem | ext4 309 GiB; 사용 2.6 GiB, 가용 307 GiB |
| Python | 3.12.3 (`/usr/bin/python3`) |
| pip3 | 명령 미확인 |
| Java/JDK | 표준 PATH·패키지·경로에서 미확인 |
| Docker | CLI·service·표준 패키지에서 미확인 |
| Docker Compose | v1/v2 명령 미확인 |
| UFW | active; 기본 inbound deny, outbound allow; 22/tcp 허용 |
| Interface / Private IP | `ens5`, `172.26.12.59/20`, MTU 9001 |
| Public FQDN IP | `13.125.194.70` |

Block device와 mount 구조는 J15E102과 동일하게 단일 320 GiB EBS의 root,
`/boot`, `/boot/efi` 파티션으로 구성되어 있다.

## 5. 서버 비교

| 항목 | J15E102 | J15E102A |
|---|---|---|
| SSH | 성공 | 성공 |
| Ubuntu / Kernel | 24.04.4 / 6.17.0-1019-aws | 동일 |
| CPU | Xeon Platinum 8259CL | 동일 |
| vCPU | 4 | 4 |
| Core / Thread | 2 cores / 2 threads per core | 동일 |
| RAM | 15 GiB | 15 GiB |
| 점검 당시 available RAM | 9.3 GiB | 14 GiB |
| Swap | 없음 | 없음 |
| EBS | 320 GiB 단일 volume | 동일 |
| Root 가용량 | 307 GiB | 307 GiB |
| Java | 표준 설치 범위에서 미확인 | 동일 |
| Docker / Compose | 표준 설치 범위에서 미확인 | 동일 |
| Python | 3.12.3 | 3.12.3 |
| UFW | active, 22/tcp 허용 | 동일 |
| Private IP | 172.26.11.108 | 172.26.12.59 |

두 서버의 정적 사양은 동일하다. J15E102A의 available RAM이 더 많았던 것은
점검 시점의 실행 중 작업 차이이며 더 높은 서버 사양을 의미하지 않는다.

## 6. Private Network 검증

두 서버는 같은 `172.26.0.0/20` route를 사용했다.

| 출발 | 대상 | ICMP | TCP 22 |
|---|---|---|---|
| J15E102 (`172.26.11.108`) | J15E102A (`172.26.12.59`) | 3/3 성공, loss 0% | `OPEN` |
| J15E102A (`172.26.12.59`) | J15E102 (`172.26.11.108`) | 3/3 성공, loss 0% | `OPEN` |

- J15E102 → J15E102A private ping 평균 RTT: 약 0.481 ms
- J15E102A → J15E102 private ping 평균 RTT: 약 0.179 ms
- 양쪽 모두 `ens5`, MTU 9001, default gateway `172.26.0.1`을 사용

Public FQDN은 다음 public IP로 해석됐다.

```text
j15e102.p.ssafy.io  -> 3.38.105.183
j15e102a.p.ssafy.io -> 13.125.194.70
```

Public FQDN 간 ping은 양방향 모두 응답이 없었지만 TCP 22 연결은 가능했다.
따라서 ping 실패만으로 public network 통신 불가라고 판단하지 않는다.
내부 서비스 간 통신은 public FQDN보다 확인된 private network를 사용하는 방향이
적합하지만, 실제 서비스 port와 접근 정책은 별도로 검증해야 한다.

## 7. 자원 사용 특이사항

J15E102에서는 점검 당시 다음 부하가 관측됐다.

- load average: 약 `3.73 / 4.08 / 4.12`
- CPU idle: 약 2.4%
- Cursor의 `rg` 프로세스: 순간 약 400% CPU
- Cursor extension-host Node 프로세스: 약 5.4 GiB RSS, RAM의 약 34.9%

J15E102A는 같은 시점에 load average가 약 `0.11 / 0.04 / 0.01`, CPU idle이
약 97.7%, available RAM이 약 14 GiB였다.

이 값은 서버 정격 성능이 아니라 특정 시점의 snapshot이다. 프로세스를 종료하거나
설정을 변경하지 않았다. 장시간 benchmark 전에는 J15E102의 고부하 작업 소유자와
용도를 확인하고 안정된 baseline을 확보해야 한다.

## 8. 실측과 설계 결정의 구분

실측으로 확인한 사실:

- 두 서버의 OS·CPU·RAM·disk 사양은 동일하다.
- 두 private IP 사이의 ICMP와 TCP 22 경로는 양방향 연결 가능하다.
- 두 서버 모두 Java, Docker, Docker Compose가 표준 설치 범위에서 확인되지 않았다.
- UFW는 active이며 현재 확인된 inbound 허용은 22/tcp다.

실측 이후의 현재 기본 방향:

- J15E102A: Big Data 처리 환경 중심
- J15E102: 서비스/배포 환경 중심

이 역할 구분은 실측만으로 자동 결정된 결과가 아니라 이후의 아키텍처 방향이다.
두 EC2를 하나의 Hadoop/Spark 물리 cluster로 묶는 것은 현재 확정 구조가 아니다.
또한 기존 [2대 EC2 고가용성 설계](2026-08-27-ec2-high-availability-design.md)의
두 app node 모델 역시 AWS 리소스와 최종 배치가 확정되기 전의 설계안이므로,
이번 실측 결과와 동일한 의미로 해석하지 않는다.

## 9. 인프라 설계 시 참고할 사항

1. 각 서버의 data, Docker layer, log, Spark shuffle이 단일 root EBS를 공유할 수
   있으므로 실제 배치 전에 전용 data volume 필요성을 판단한다.
2. EBS 320 GiB라는 크기는 확인했지만 volume type, provisioned IOPS/throughput,
   burst 상태는 확인하지 않았다.
3. Swap이 없으므로 Java/Spark/컨테이너 memory limit을 정할 때 OS와 daemon용
   여유를 명시적으로 남겨야 한다.
4. 현재 UFW는 22/tcp만 허용한다. 서비스 port를 확정한 뒤 private source 범위에
   필요한 최소 규칙만 설계하고 AWS Security Group/NACL과 함께 검증한다.
5. Public FQDN은 public IP로 해석된다. 내부 component는 고정 private DNS 또는
   관리되는 hostname/IP mapping 정책을 사용해야 한다.
6. Java, Docker, Compose 설치 방식과 버전은 Hadoop/Spark 및 애플리케이션 버전
   matrix를 확정한 뒤 두 서버에 일관되게 적용한다.
7. J15E102에서 관측된 개발 도구 부하가 서비스/배포 작업과 경쟁하지 않도록 실행
   계정, 작업 시간, resource limit 또는 배치 분리를 검토한다.

이번 Jira에서는 위 설치와 설정 변경을 수행하지 않았다.

## 10. Benchmark 시 주의사항

- J15E102의 기존 고부하가 없는 안정된 시점에 baseline을 다시 측정한다.
- 동일 dataset hash, parser/registry version, partition, executor 설정으로 비교한다.
- warmup 후 여러 번 반복하고 평균만이 아니라 median과 편차를 기록한다.
- wall-clock time과 함께 CPU, RAM, disk 사용량, Spark spill/shuffle, failure/retry를
  수집한다.
- `t3.xlarge`의 CPU credit 관련 지표와 EBS IOPS/throughput을 함께 확인한다.
- 서비스/배포 workload와 data workload를 동시에 실행하는 경우와 분리한 경우를
  구분한다.
- 1 worker/2 worker 비교는 최종 배치가 확정된 후 동일 조건에서 수행하며, 이번
  실측만으로 scale-out 효과를 주장하지 않는다.

이번 작업에서는 benchmark를 실행하지 않았다.

## 11. 아직 확인되지 않은 항목

- 두 EC2의 Availability Zone, subnet ID와 private IP 유지 정책
- AWS Security Group, NACL의 전체 inbound/outbound 규칙
- EBS volume type, IOPS, throughput, snapshot/backup 정책
- CPU credit balance/mode와 장시간 부하 시 성능
- Hadoop, Spark, Kafka의 최종 설치 방식·버전·실제 실행 위치
- 내부 DNS/hostname 정책과 Hadoop/Spark 서비스 port 연결성
- Docker bridge CIDR과 `172.26.0.0/20`의 충돌 여부
- 실제 데이터의 압축/해제/Parquet 변환 크기와 peak shuffle 공간
- 독립적으로 제공된 신뢰 가능한 SSH host key fingerprint와의 대조
- J15E102 고부하 Cursor 프로세스의 지속 여부와 운영 영향

확인되지 않은 항목은 설치됨, 연결 가능함, 충분함으로 추정하지 않는다.

## 12. 관련 문서

- [Infrastructure 문서 목차](README.md)
- [인프라 준비도](2026-08-27-infra-readiness.md)
- [인프라 배포 준비 계획](2026-08-27-infra-deployment-plan.md)
- [2대 EC2 고가용성 설계](2026-08-27-ec2-high-availability-design.md)
- [데이터 플랫폼·파이프라인](../data/README.md)
