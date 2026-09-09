# 운영 상태 감시

배포와 무관하게 서비스가 살아 있는지 주기적으로 확인하고, 상태가 바뀌면 알린다.

## 왜 필요했나

2026-09-09에 nginx가 2시간 4분간 502를 반환했는데 아무도 몰랐다. 그것을 망가뜨린
배포는 성공으로 끝났고, 2시간 뒤 다음 배포가 우연히 실패하면서 발견됐다.

**운영을 보는 눈이 배포할 때뿐이었다.** 배포하지 않으면 무한정 깨져 있어도 모른다.
경위는 `2026-09-09-first-production-deploy.md`에 있다.

## 무엇을 확인하나

`Infra/scripts/health-probe.sh`가 두 가지를 본다.

| 확인 | 방법 |
| --- | --- |
| 진입점 | `https://127.0.0.1/health`가 `"status":"UP"`을 반환하는가 |
| 컨테이너 | `gitjob-` 컨테이너 중 exited·restarting·unhealthy가 있는가 |

진입점은 nginx가 있는 호스트에서만 확인한다. 데이터 호스트에는 nginx가 없으므로 컨테이너
상태만 본다. `-init-1`·`bootstrap-1`처럼 한 번 실행하고 끝나는 컨테이너의 `exited`는
실패로 세지 않는다.

## `verify-deployment.sh` 와 무엇이 다른가

목적이 다르므로 둘 다 필요하다.

| | `verify-deployment.sh` | `health-probe.sh` |
| --- | --- | --- |
| 묻는 것 | 이 배포가 완결되었는가 | 되던 것이 지금 깨졌는가 |
| 실행 | 배포 끝에 한 번 | 2분마다 계속 |
| CDC 미프로비저닝 | ACTION | 신경 쓰지 않음 |
| C compute 비활성 | SKIP | 신경 쓰지 않음 |

배포 검증은 "며칠 그 상태로 있어도 괜찮은" 항목을 포함한다. 감시는 사람을 깨울 만한
것만 본다. 감시가 배포 검증을 대신하려 들면 상시 경보가 울려 아무도 보지 않게 된다.

## 알림은 전이에만

한 시간 down 이면 열두 번이 아니라 한 번 알린다. 복구되면 한 번 더 알린다. 바뀌지 않은
실패를 반복해서 보내면 사람이 무시하도록 훈련되는데, 그것이 이 문제의 출발점이었다.

이전 판정은 `HEALTH_STATE_FILE`(기본 `/var/tmp/gitjob-health-probe.state`)에 남는다.

## 설치

각 EC2 호스트에서 한 번 수행한다.

```bash
sudo mkdir -p /etc/gitjob
sudo install -m 600 /dev/null /etc/gitjob/health-probe.env
sudo tee /etc/gitjob/health-probe.env >/dev/null <<'ENV'
HEALTH_ALERT_WEBHOOK=
HEALTH_HOST_LABEL=service   # 데이터 호스트에서는 data
ENV

sudo cp Infra/systemd/gitjob-health-probe.service /etc/systemd/system/
sudo cp Infra/systemd/gitjob-health-probe.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gitjob-health-probe.timer
```

확인:

```bash
systemctl list-timers gitjob-health-probe.timer
journalctl -t gitjob-health --since '-1h'
sudo systemctl start gitjob-health-probe.service   # 즉시 한 번 실행
```

알림은 SSAFY Mattermost incoming webhook으로 보낸다. URL은 리포지토리에 넣지 않고
`/etc/gitjob/health-probe.env`에만 둔다. 두 호스트 모두에서 실제로 POST 해 `HTTP 200 ok`와
채널 도착까지 확인했다(2026-09-09).

webhook을 비워 두면 감시는 돌고 journald에 기록되지만 **아무에게도 도달하지 않는다.**
그 상태는 "감시가 있다"고 말할 수 없다.

## 주기를 2분으로 둔 이유

얼마나 자주 볼 수 있는지가 아니라, **장애가 얼마나 오래 숨을 수 있는지**를 기준으로 정했다.
nginx는 자체 healthcheck가 unhealthy로 판정하기까지 최대 2분이 걸린다(`retries: 12`,
`interval: 10s`). 그보다 느리게 보면 떴다 사라지는 실패를 놓친다.

## 감시하지 않는 것

무엇을 보지 않는지 적어 두어야 다음 사각지대를 안다.

- **호스트 자체의 죽음.** 감시가 그 호스트에서 돌므로 호스트가 죽으면 알림도 죽는다.
  외부 uptime 서비스가 있어야 메울 수 있는 구멍이다.
- **기능이 맞게 도는지.** collector가 수집하는지, Spark가 집계하는지, CDC가 실제로
  이벤트를 흘리는지는 보지 않는다. 컨테이너가 healthy 한 것과 일을 하는 것은 다르다.
- **응답 시간·자원 사용량.** 메트릭과 대시보드는 범위 밖이다. 지금 필요한 것은
  "죽었는지 아는 것"이다.
- **데이터 정합성.** 큐 적체, outbox 미발행 누적 같은 것.

## 실패했을 때

알림은 무엇이 깨졌는지만 말한다. 원인 규명은 다음 순서를 따른다.

```bash
./Infra/scripts/health-probe.sh          # 지금 무엇이 실패하는지
./Infra/scripts/verify-deployment.sh     # 배포 단계가 빠진 것인지
docker logs --tail=100 <컨테이너>
```

진입점만 실패하고 backend는 healthy 하다면 nginx가 backend에 닿지 못하는 것이다.
`verify-deployment.sh`의 `entry-point` 항목이 복구 명령을 함께 출력한다.
