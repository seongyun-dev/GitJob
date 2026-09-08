# Repo Snapshot `tree_sha` lineage correction

> Jira: `S15P21E102-150` 구현 보정 / `S15P21E102-114` Production Snapshot 후속 / `S15P21E102-160` A→C Consumer Read 보정
>
> 기준 develop: `3a509254883eb619be9a38e21f7e12acfbffff3b`
>
> 상태: metadata-only correction 완료 / C조 Consumer Read 재검증 대기

## 1. 범위와 원인

기존 Snapshot의 Artifact 원문과 pinned commit은 변경하지 않는다. 이번 작업은
`pinned_commit_sha`와 실제 Git root `tree_sha`의 lineage를 분리하고, 실행 계보를
새 Snapshot metadata에 남기는 보정이다.

기존 `AI/github/repo_fetch_orchestrator.py`는 HEAD/commit 응답의
`commit.tree.sha`를 확보한 뒤에도 commit SHA를 Recursive Tree API의 ref로 사용하고,
Tree 응답의 최상위 `sha`를 `tree_sha`로 우선 저장할 수 있었다. 이 경우
`tree_sha == pinned_commit_sha`가 되어 두 Git object 의미가 합쳐진다.

수정 후에는 commit 응답의 중첩 `commit.tree.sha`를 authoritative root tree로
보존하고, Tree API도 그 SHA로 조회한다. Tree 응답의 최상위 `sha`는 ref를 반영할
수 있으므로 authoritative 값으로 덮어쓰지 않는다.

## 2. Source와 correction Snapshot

| 항목 | 값 |
|---|---|
| source snapshot | `s15p21e102-114-phase1-20260907-fix-001` |
| target snapshot | `s15p21e102-114-phase1-20260908-treefix-001` |
| source HDFS | `hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=s15p21e102-114-phase1-20260907-fix-001/` |
| target HDFS | `hdfs:///gitjob/analysis_input/github/repo_snapshot/snapshot_id=s15p21e102-114-phase1-20260908-treefix-001/` |
| source pipeline | `s15p21e102-114-run-002` |
| correction pipeline | `s15p21e102-114-treefix-run-001` |
| correction policy | COMPLETE/PARTIAL records만 실제 pinned commit tree를 조회; 나머지는 tree를 fabricate하지 않음 |

기존 target namespace는 overwrite하지 않는다. 새 Snapshot의 record metadata만
생성하며 Artifact URI는 immutable source Artifact를 그대로 가리킨다. 따라서 정상
Artifact byte를 다시 다운로드하거나 기존 Artifact를 삭제하지 않는다.

## 3. 실행 provenance

```text
GH Archive Raw
  → Repo Activity Snapshot
  → Top20k candidates.json
  → GitHub Fetch Run
  → source Repo Snapshot
  → metadata-only tree correction
  → corrected Repo Snapshot
```

| provenance | 값 |
|---|---|
| candidates | `/home/ubuntu/workspace/S15P21E102/.local/repo-snapshot-bootstrap/s15p21e102-114-phase1-20260907-fix-001/candidates.json` |
| candidates SHA-256 | `8a21f89af0c38f6b66603eff43192974084881740d27ef0d0535c8e65d64ce9` |
| candidates schema | `repo-fetch-candidates/v1` |
| candidates input_root | `hdfs:///gitjob/parquet/github/repo_activity/period=2026-08/snapshot=s15p21e102-109-20260902` |
| Repo Activity period | `[2026-08-01T00:00:00Z, 2026-09-01T00:00:00Z)` |
| GH Archive Raw range | `hdfs:///gitjob/raw/gharchive/dt=2026-08-*/*.json.gz` |
| correction execution Git SHA | `3a509254883eb619be9a38e21f7e12acfbffff3b` |
| image digest | correction used host Python; historical Bootstrap image digest was not available, so no digest is claimed |

## 4. Code and reuse behavior

- `AI/github/repo_fetch_orchestrator.py`: root tree SHA preservation, Tree API root,
  ambiguous response SHA rejection, and legacy terminal checkpoint metadata repair.
- `AI/github/repo_fetch_store.py`: cache/checkpoint tree-only repair that preserves
  Artifact URI/hash/size and does not increment collection attempts.
- `AI/github/repo_fetch_benchmark.py`: missing nested commit tree is not replaced by
  the commit SHA.
- `AI/github/repo_snapshot_tree_correction.py`: GraphQL commit/tree lookup and a
  metadata-only new Snapshot publisher with resumable `tree-map.json` state.

Same-SHA cache reuse performs one HEAD lookup and repairs a legacy cache record before
returning `REUSED`; same-dataset checkpoint replay repairs a legacy terminal record by
checking the pinned commit object, without Artifact/raw fetch. If the tree cannot be
verified, the correction removes the misleading commit-as-tree value rather than
fabricating one.

관련 검증은 기존 orchestrator/benchmark suite **50 passed**, v1 contract suite
**26 passed**, 새 legacy-checkpoint repair 회귀 테스트를 포함한 orchestrator 수동
runner **23 passed**로 확인했다. 변경 Python 파일 `ruff check`와 bytecode compile도
통과했다. 전체 AI suite는 기존 로컬 환경 의존성 문제(tzdata/pytest 등)로 별도
재실행하지 않았다.

## 5. Validation

The source Snapshot contains 13,101 `COMPLETE`, 291 `PARTIAL`, and 18 post-pin
`FAILED` records (13,410 records in the immutable Snapshot; pre-pin failures are not
Snapshot records). All 13,392 COMPLETE/PARTIAL records in the source carried the
legacy `tree_sha == pinned_commit_sha` value.

The correction run recorded:

- eligible, resolved, and unresolved tree metadata counts and lookup errors;
- unchanged COMPLETE/PARTIAL/FAILED status counts;
- unchanged Artifact signature and per-Artifact content hashes;
- target `snapshot.json`, `run-summary.json`, `failures.json`, and `_SUCCESS.json`
  checksums plus HDFS read-back;
- four public COMPLETE samples linking pinned commit → GitHub commit `tree.sha` →
  corrected Snapshot value;
- a sample Artifact read-back from its immutable source URI.

실측 결과:

- source eligible COMPLETE/PARTIAL: **13,392건**, legacy `tree_sha == pinned_commit_sha`: **13,392건**;
- corrected target records: **13,392건** eligible, actual tree resolved **13,390건**, unresolved **2건**;
- unresolved: `agmpro-byte/hg-calendar` (`NOT_FOUND`), `guatoc-ecohub/Chagra` (`HTTP_404`);
- target Snapshot record statuses: COMPLETE 13,101 / PARTIAL 291 / post-pin FAILED 18;
  source run-summary status counts remain COMPLETE 13,101 / PARTIAL 291 / NOT_FOUND 6,579 / FAILED 29 / REUSED 0;
- target schema: `github-repo-snapshot/v1`; HDFS read-back: 4 metadata files, logical **23.7 MiB**;
- target metadata SHA-256: `snapshot.json`
  `0bc9f91535a77bd4a18f6741841a11eeb66f1acf6ff938b79602dd34edcdd656`,
  `run-summary.json`
  `1ea1095a60685cc466f1fca44ffb28597da615e25beac86e49d247cd1bd6ebf1`,
  `failures.json`
  `d54077345eb02f5e14d0846c2dbc24a6ab13296fb3d30fd35a0e2430283fde02`,
  `_SUCCESS.json`
  `b4fe52c2db9e9e3d6d4261ef1e6dba4b7083acdd502bc72569e872ec518d95fd`;
- Artifact signature before/after: **`4f4380ac1fbc0f91eaf62e4b3928badd165f571609f82ce2d7886945ebead648`**;
  Artifact 4,876개 / 10,792,131 bytes unchanged;
- tree lookup: 13,392 logical commit/tree lookups (GraphQL batched), rate-limit wait 0회 / 0초;
- sample Artifact read-back SHA matched its recorded `content_hash`.

Known four-sample lineage values:

| Repo | pinned commit | actual tree SHA |
|---|---|---|
| `ugmoddev/API-NEW-NAT-3-` | `9f9954c7457d2615bf4bb51d086315fb8900498d` | `0c8898afd44c10044c3d920cc6349cf1e97032e0` |
| `LiamBruhin/SillyStuff` | `ac2dd0e5e749a4a016da9f228cf9340fb2ae073f` | `2a896caae25ddbac186a9850ebf9d7a26dfa5cb6` |
| `ugmoddev/noti-api-server` | `644c385bb228f42c5e7d38ccc36a398c5045a136` | `b846a96bdb8b0350963e2e9c7a29a284342f3c1d` |
| `CodeHub-Clients/CodeHub_Licenses` | `ec7ce3c2c0745537c9ddfff6c9c8dd76c4912e20` | `5329616222d486afcbe07a4fe7fdf339a6bab318` |

## 6. C조 Consumer Read 체크리스트

1. Read the target `snapshot.json` and validate `github-repo-snapshot/v1`.
2. For resolved COMPLETE/PARTIAL records, assert `tree_sha` is a valid Git tree SHA
   and differs from `pinned_commit_sha`.
3. For unresolved records, accept `tree_sha=null` with the recorded lookup reason;
   never infer a tree from the commit SHA.
4. Confirm status counts, source/target relation, candidate SHA, input root, pipeline
   id, execution SHA, and correction reason in `run-summary.json`/`_SUCCESS.json`.
5. Recompute the Artifact signature and read a sample Artifact through its immutable
   source URI; it must match the source Snapshot byte-for-byte.
6. Keep Technology Registry mapping and Evidence L0–L3 semantics in C조 scope only.

기존 기술 분석 결과는 Artifact 원문과 pinned commit에 기반하므로 계속 사용할 수
있다. 다만 lineage를 소비하는 검증은 기존 source Snapshot 대신 이 correction
Snapshot을 기준으로 재확인한다.
