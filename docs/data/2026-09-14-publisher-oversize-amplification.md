# oversized 이벤트가 `github.events` 를 2.4배로 불린 경로

Jira: `S15P21E102-257`
측정: 2026-09-14, 운영 브로커·checkpoint 실측

---

## 1. 무슨 일이 있었나

`github.events` 에 같은 hour 가 반복 적재됐다.

```
2026-09-13 publish 15회   →  3 성공 / 12 실패
같은 hour(2026-09-04T21) 가 12회 재전송
checkpoint 기록 12.4M events  vs  Kafka 레코드 최소 29.7M
                                  → 최소 2.4배 증폭
```

디스크 고갈 P0 에 기여했다.

## 2. 경로

1. `AI/common/kafka.py` 가 `KafkaProducer(...)` 에 `max_request_size` 를 주지 않아 kafka-python 기본 **1,048,576 B** 가 쓰였다
2. GH Archive 에 1 MiB 를 넘는 이벤트가 실재한다. 관측 최대 **1,834,656 B**, `MessageSizeTooLargeError` **584건**
3. `send_many` 는 enqueue → flush → future 검사 순서다. **실패가 드러나기 전에 ack 된 레코드는 이미 broker 에 durable** 하다
4. 첫 실패 future 에서 `KafkaError` 가 올라온다
5. `publish_hours` 의 `except (KafkaError, OSError, gzip.BadGzipFile)` 이 그것을 받아 `failed` 에 넣고 `continue` 한다 — **`checkpoint.record()` 에 닿지 못한다**
6. 다음 cron 에서 `checkpoint.has(hour_key)` 가 False 이므로 **hour 를 처음부터 다시 보낸다**
7. 같은 파일·같은 이벤트라 같은 자리에서 또 실패한다

`enable_idempotence=True` 는 **한 producer 세션 안에서만** 중복을 막는다. cron 실행마다 새 producer 이므로 교차 실행 중복에는 아무 효과가 없다. consumer dedup 은 보조 안전장치일 뿐이고, producer 가 무한히 다시 보내는 것을 정상 동작으로 의존해선 안 된다.

## 3. 크기를 올려서 해결할 수 없었다

운영 브로커 실측(2026-09-14):

```
broker  message.max.bytes        1,048,588
topic   max.message.bytes        1,048,588   (브로커 기본 상속)
broker  replica.fetch.max.bytes  1,048,576
```

producer `max_request_size` 만 올리면 거부 지점이 client 에서 broker 로 옮겨갈 뿐이다. 1.75 MiB 를 통과시키려면 **셋을 함께** 올려야 한다 — `replica.fetch.max.bytes` 를 빠뜨리면 브로커가 받아들인 레코드를 복제본이 가져가지 못해 복제가 멈춘다.

Kafka config 변경은 이 이슈 범위가 아니므로, **한계를 넘는 이벤트는 거부**한다.

## 4. 무엇을 바꿨나

### 4.1 크기 계약을 한 곳에 둔다

`common.kafka.MAX_MESSAGE_BYTES` 하나를 producer 의 `max_request_size` 와 전송 전 게이트가 함께 읽는다. 값은 취향이 아니라 브로커의 것이고(둘 중 작은 쪽인 1,048,576), `KAFKA_MAX_MESSAGE_BYTES` 로 덮을 수 있다 — 브로커 한계가 올라가는 날 둘이 같이 따라 올라가게 하려는 것이다. 무제한은 허용하지 않는다.

### 4.2 한계 초과 이벤트는 hour 를 실패시키지 않는다

`iter_hour_messages` 가 **전송 전에** 크기를 보고, 넘으면 `RejectedEvent` 로 분리한다.

```
hour       2026-09-01T00:00:00Z
source_id  2026-09-01T00:00:00Z/14172383030
bytes      1,834,656
limit      1,048,576
reason     EVENT_EXCEEDS_MAX_MESSAGE_BYTES
```

파싱이 안 되는 줄을 담는 `skipped_lines` 와는 별도다. 이쪽은 정상적으로 파싱·봉투화된 이벤트이고, 단지 어떤 브로커도 받지 못할 뿐이다.

### 4.3 거부가 있어도 hour 는 완료된다

`checkpoint.record(hour, events=..., rejected=...)` 로 기록한다. 거부된 이벤트는 결정적이라 파일을 다시 읽어도 또 거부된다. 다시 보내봐야 나머지를 중복 적재할 뿐이므로 hour 는 끝난 것으로 본다. **이것이 루프를 끊는 지점이다.**

### 4.4 transient 와 deterministic 을 나눈다

| | 처리 | 이유 |
| --- | --- | --- |
| 크기 초과 | 전송 전 거부, hour 는 완료·checkpoint | 결정적. 재시도해도 결과가 같다 |
| broker 다운 · 소켓 끊김 · 깨진 gzip | hour 실패, checkpoint 미기록, **마지막 ACK 지점부터** 다음 pass 재시도 (4.6) | 일시적. 재시도에 의미가 있다 |

`except` 에 도달하는 것은 이제 일시적 실패뿐이다 — 크기 초과는 그 전에 걸러졌다.

### 4.5 기록

`PublishSummary` 가 `published` / `failed` / `rejected_events` 를 각각 들고, `as_dict()` 가 `rejected_events` 개수와 샘플 10건을 낸다. checkpoint 항목은 `events` 와 `rejected` 를 나눠 적는다.

`rejected` 는 0 일 때도 쓴다. 이 수정 이전에 기록된 hour 에는 키 자체가 없어서, "없음" 과 "0" 이 구분되어야 한다.

### 4.6 transient 실패는 마지막 ACK 지점부터 재개한다

4.3 은 **결정적** 실패의 루프를 끊었다. **일시적** 실패의 루프는 그대로 남아 있었다.

```
1회차  1~50 broker ACK  →  51 timeout  →  hour 실패  →  checkpoint 미기록
2회차  checkpoint.has() False          →  1 부터 다시 전송
```

같은 hour 를 처음부터 다시 보내는 것은 §2 와 완전히 같은 증폭이고, 원인만 크기 초과에서 네트워크로 바뀐 것이다. 실측으로 확인했다 — 수정 전 코드에서 2회차는 이미 ACK 된 50건을 **전부** 다시 보냈다.

#### `publish-progress.json` — checkpoint 와 별개 파일

| 파일 | 답하는 질문 | 실패 방식 |
| --- | --- | --- |
| `publish-checkpoint.json` | 이 hour 는 끝났나 | 손상돼도 재전송이면 된다 (consumer dedup) |
| `publish-progress.json` | 안 끝났다면 어디부터 이어가나 | 손상되면 **멈춘다** |

한 파일에 합치지 않은 이유는 둘의 안전한 실패 방향이 반대이기 때문이다. 끝난 hour 는 절대 다시 보내면 안 되고, 안 끝난 hour 는 반드시 이어갈 수 있어야 한다. 한 레코드가 동시에 "없음" 이면서 "있음" 일 수는 없다.

```json
{
  "topic": "github.events",
  "hours": {
    "2026-09-01T00:00:00Z": {
      "next_line": 50,
      "acknowledged": 50,
      "limit": 1048576,
      "updated_at": "2026-09-14T11:02:31+00:00"
    }
  }
}
```

#### cursor 는 줄 번호이고, ACK 에만 움직인다

`send_many` 가 `on_batch_acknowledged(누적 ACK 수)` 를 부른다. **`producer.send()` 가 반환할 때가 아니라, `flush()` 후 그 chunk 의 future 를 전부 확인한 뒤에만** 부른다. enqueue 시점에 cursor 를 옮기면 버퍼에 남은 채 프로세스가 죽은 레코드를 건너뛰게 된다 — 중복보다 나쁜 유실이다.

cursor 로 "몇 번째 레코드" 가 아니라 **파일의 줄 번호**를 쓴다. 파싱 실패로 건너뛴 줄과 크기로 거부된 줄이 그 사이에 섞여 있어서, 보낸 개수는 파일 위치를 가리키지 못한다. 줄 번호는 가리킨다.

`limit` 을 함께 적는 이유는 크기 한계가 바뀌면 cursor 를 버려야 하기 때문이다. cursor 자체는 유효하지만, 옛 한계에서 거부된 이벤트가 cursor 뒤에 앉아 있어 재개가 다시는 보지 않는다. 한계가 바뀐 hour 는 처음부터 다시 읽는다.

#### 최대 중복 구간 — 5,000 events

exactly-once 는 아니다. 기록이 남는 창(window)이 하나 있다:

```
broker 가 chunk 를 ACK 함
         ↓   ← 여기서 프로세스가 죽으면 그 chunk 는 durable 하지만 기록되지 않았다
progress 파일 기록 (tmp → replace, atomic)
```

이 창에 들어갈 수 있는 최대치는 **flush chunk 하나 = `KafkaPythonTransport.batch_flush_size` = 5,000 events** 다. hour 크기와 무관하게 고정이다.

```
수정 전   중복 상한 = hour 전체        ≈ 117,600 events   (그리고 매 pass 반복)
수정 후   중복 상한 = flush chunk 1개  =   5,000 events   (1회, 프로세스 사망 시에만)
```

progress 쓰기는 `.tmp` 에 쓴 뒤 `replace` 이므로, 반쯤 쓰인 파일이 남지는 않는다. 손상된 파일을 만나면 hour 를 `PROGRESS_UNREADABLE` 로 실패시키고 **파일은 건드리지 않는다** — 믿으면 broker 에 닿지 않은 레코드를 건너뛰고, 무시하면 hour 를 통째로 재전송한다. 둘 다 나쁘므로 사람이 본다.

### 4.7 거부 목록은 파일로 남는다

`publish-rejected-events.jsonl` — 한 줄에 하나, `(hour, source_id)` 로 중복 제거.

```json
{"hour": "2026-09-01T00:00:00Z", "source_id": "2026-09-01T00:00:00Z/14172383030", "bytes": 1834656, "limit": 1048576, "reason": "EVENT_EXCEEDS_MAX_MESSAGE_BYTES", "recorded_at": "2026-09-14T11:02:31+00:00"}
```

summary 에만 있으면 로그가 회전하는 순간 사라지고, hour 는 checkpoint 됐으므로 다시 만들어지지 않는다. 브로커 한계를 올리기로 하는 날 한 달치 아카이브를 다시 훑는 대신 이 파일을 읽으면 된다.

재개된 hour 는 같은 거부를 다시 만나므로, 이미 적힌 항목은 다시 쓰지 않는다. 실패한 hour 의 거부도 적는다 — hour 는 재시도되겠지만 목록은 지금 읽을 수 있어야 한다.

## 5. 남은 것

- **이미 적재된 중복 레코드는 정리하지 않았다.** `github.events` 의 기존 중복은 이 수정 범위 밖이다
- **거부된 이벤트는 Kafka 로 가지 못한다.** 원본은 HDFS Raw 에 그대로 있으므로 유실은 아니지만, 스트리밍 경로로는 흐르지 않는다. 브로커 한계를 올리기로 결정하면 §3 의 세 설정을 함께 올린 뒤 해당 hour 를 checkpoint 에서 빼고 재실행하면 된다
- **exactly-once 는 아니다.** 4.6 의 창이 남아 있다 — broker ACK 후 progress 기록 전에 프로세스가 죽으면 최대 5,000 events 가 한 번 중복된다. consumer 의 `source_id` dedup 이 이를 흡수한다
- **Production 미반영.** producer 실행·cron 복구·Kafka config 변경은 하지 않았다

## 6. 재발 방지로 테스트가 고정한 것

`tests/test_gharchive_publisher_oversize.py` 24건 — 크기 계약과 결정적 거부:

- `test_a_rerun_does_not_resend_an_hour_that_had_rejections` — 루프 자체
- `test_duplicates_stay_bounded_across_repeated_runs` — 10회 반복 실행이 이벤트를 한 번만 보낸다
- `test_an_hour_recorded_before_this_fix_is_still_honoured` — 구 checkpoint 항목을 재전송하지 않는다

`tests/test_gharchive_publisher_resume.py` 18건 — 일시적 실패의 재개:

- `test_events_acknowledged_before_a_transient_failure_are_not_resent` — 100건 중 1~50 ACK 후 실패, rerun 이 51 부터 시작하고 1~50 재전송은 0
- `test_resume_starts_after_the_last_acknowledged_chunk` — 재개 지점이 마지막 ACK chunk 바로 다음
- `test_the_cursor_does_not_move_on_enqueue_alone` — enqueue 만 된 레코드는 건너뛰지 않고 다시 보낸다
- `test_a_crash_between_ack_and_progress_costs_at_most_one_chunk` — 4.6 의 창이 실제로 chunk 하나로 막혀 있다
- `test_the_duplicate_window_does_not_grow_with_the_hour` — 이벤트를 10배로 해도 창은 그대로
- `test_a_changed_size_limit_restarts_the_hour` — 한계가 바뀌면 cursor 를 버린다
- `test_a_corrupt_progress_file_fails_closed` — 손상된 progress 는 전송 없이 `PROGRESS_UNREADABLE`
- `test_an_old_checkpoint_with_no_progress_file_is_honoured` — progress 파일이 아예 없는 구 배포 상태와 호환
- `test_oversized_and_transient_failure_in_one_hour` — 초과 1건 + 일시 실패가 한 hour 에 같이 있어도 재개하고 완료한다
- `test_repeated_passes_do_not_grow_the_rejected_log` — 거부 목록이 반복 실행으로 불어나지 않는다

테스트가 헛돌지 않는지는 progress 저장만 무력화해 확인했다 — 그 한 줄을 끄면 2회차가 1~50 을 전부 다시 보낸다(50건 중복), 켜면 0건이다.
