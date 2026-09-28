# C compute forward migrations

이 디렉터리는 Flyway 대상이 아니다. Worker 이미지의 `python -m worker.migrate`가
advisory lock `331029`와 migration checksum을 사용해 번호 순서대로 적용한다.

- `001`~`004`: 기존 Snapshot, matching, Registry review 계약
- `005`: 불변 `job_fact`와 원자적으로 게시하는 검색 Projection
- `006`: 불변 `user_result`, `(user_id, target_key)`별 current/previous head,
  matching의 `job_fact_id` 참조
- `007`: event 순서 기반 current head, fact 단위 matching source, Projection head
  단조 게시와 감사 가능한 rollback
- `008`: payload-free Current Market 집계를 위한 불변 market job/candidate sidecar

적용된 파일은 수정하지 않는다. 변경은 다음 번호의 forward migration으로만 추가한다.
런타임 프로세스는 DDL을 자동 실행하지 않으며 현재 코드는 schema version 8을 요구한다.
실행·검증·롤백 순서는
[`docs/ai/job-search-projection-runbook.md`](../../../../../docs/ai/job-search-projection-runbook.md)를
따른다.
