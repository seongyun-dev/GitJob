# GitJob AI

This directory contains the Python 3.12 runtime boundaries for GitJob's
collector and analysis worker. Both processes currently expose only a
liveness endpoint. The A-to-C job-analysis input contract is also available
as a library boundary. Technology Registry matching, requirement
classification, demand aggregation, GitHub trend, Stack Overflow, and LLM
behavior belong to their own follow-up issues.

## Package boundaries

```text
AI/
├── collector/       # collector process entrypoint
├── worker/          # analysis worker process entrypoint
├── common/          # shared process infrastructure
├── registry/        # Technology Registry analysis
├── job/             # job-posting analysis
├── stackoverflow/   # Stack Overflow analysis
├── github/          # GitHub 수집 경계와 A→C Repo Snapshot 계약
├── llm/             # Fact-grounded LLM behavior
└── tests/
```

The domain packages do not contain placeholder results. The `github` package
contains the bounded GitHub collection client used by the Repo Fetch
Orchestrator; semantic technology analysis remains outside that client.

## Windows and PowerShell setup

Run these commands from `AI/` with Python 3.12 available as `py -3.12`.
The virtual environment is created at the repository root so the existing
Dockerfile's `COPY AI/ ./` does not include it:

```powershell
py -3.12 -m venv ..\.venv
$python = "..\.venv\Scripts\python.exe"
& $python -m pip install --requirement requirements-dev.txt
```

If the Windows Python launcher is unavailable, replace `py -3.12` with the
absolute path to an installed Python 3.12 executable:

```powershell
$python312 = "C:\path\to\python.exe"
& $python312 -m venv ..\.venv
```

For a runtime-only environment, install `requirements.txt` instead.

## Test and static checks

```powershell
$python = "..\.venv\Scripts\python.exe"
& $python -m pytest
& $python -m ruff check .
& $python -m ruff format --check .
```

## A-to-C job-analysis input contract

Issue `S15P21E102-90` defines the strict batch contract in
`job/contracts.py`. The version is `job-analysis-input/v1`; unsupported
versions and unknown fields fail validation instead of being guessed or
silently discarded.

Required batch metadata:

- `schema_version`, `dataset_snapshot_id`, `pipeline_run_id`
- `collector_version`

`registry_version` and requirement-rule versions are C-team result metadata,
not A-team collection input. The expected fixture carries synthetic values for
the later Mapper/classifier tests; production analysis results must attach the
actual versions used for that run.

Each source record keeps `source_record_id`, the source posting ID and URL,
raw company/title/job/career/region fields, collection time, and a SHA-256
`content_hash`. `TEXT_AVAILABLE` requires `description_text`, while `IMAGE_ONLY`
requires `raw_artifact_uri`. `MISSING`, `BLOCKED`, and `PARSE_FAILED` remain
valid observable states. The boundary uses the existing shared data-contract
term `TEXT_AVAILABLE` from `docs/data/README.md`.

Technology mentions preserve the source spelling, source `technology_id`,
input requirement type, source surface, and Evidence. External payloads must
use `technology_id`; the internal Python name is not accepted or serialized at
this boundary. The adapter exposes the internal field as `tech_id` and only
applies the agreed legacy-ID mappings:

| A boundary `technology_id` | Internal `tech_id` |
|---|---|
| `c#` | `csharp` |
| `c++` | `cpp` |
| `.net` | `dotnet` |
| `.net-maui` | `dotnet-maui` |
| `node.js` | `nodejs` |
| `next.js` | `nextjs` |
| `vue.js` | `vuejs` |

Already-safe lowercase slugs pass through. Any other unsafe ID fails
input validation explicitly. A null `technology_id` is retained with its raw
spelling and Evidence, so later Registry work can classify it as `AMBIGUOUS`
or `UNKNOWN`. The input `MENTIONED` value is a source observation; the expected
fixture separately records the later classifier result as `SKILL` or
`REVIEW_REQUIRED`. This adapter implements neither decision.

`canonical_job_id` is treated only as an upstream semantic-duplicate candidate
key. Groups contain at least two distinct `source_record_id` values and are
exposed without removing either source record. Repeated delivery of the same
source record is not reported as a semantic duplicate. Kafka redelivery,
consumer restart, Spark retry, and replay idempotency remain A-team
responsibilities and are not inferred from this key.

Reusable synthetic fixtures are under `job/fixtures/`:

- `job_analysis_input_v1.json`: all five body states, closed, duplicate,
  C/R/Go ambiguity, every agreed legacy alias, pass-through, and unknown cases
- `job_analysis_expected_v1.json`: expected outcomes for the later Registry
  mapper/classifier issues plus synthetic expected result versions; it is not
  production inference output
- `invalid_job_analysis_input_v1.json`: unsupported schema, missing metadata,
  wrong ID type, missing body, invalid enum, unsafe ID, and internal-field-name
  cases

All fixture URLs and identifiers are synthetic. They are not copied from the
local A-team snapshot or production data. Generate a tool-neutral JSON Schema
from the authoritative Pydantic model when sharing the contract:

```powershell
$python = "..\.venv\Scripts\python.exe"
& $python -c `
  "from job.contracts import JobAnalysisInputBatch; import json; print(json.dumps(JobAnalysisInputBatch.model_json_schema(by_alias=True), ensure_ascii=False, indent=2))"
```

Run only the contract suite with:

```powershell
& $python -m pytest tests/test_job_contracts.py -q
```

A-team handoff still needs confirmation of actual Parquet/JSON types and
locations, real `schema_version`/collector version production values,
`raw_artifact_uri` availability, and revision/closed-posting policy. C-team
owns contract validation, semantic duplicate adjudication, Registry matching,
requirement classification, and downstream facts. No B-team online API is
introduced by this issue.

## Run locally

Collector and worker default to `0.0.0.0:8080`. Run them one at a time, or
set a different `APP_PORT` for one process when starting both on the same
host.

Terminal 1:

```powershell
$python = "..\.venv\Scripts\python.exe"
& $python -m collector
```

Terminal 2:

```powershell
$python = "..\.venv\Scripts\python.exe"
$env:APP_PORT = "8081"
& $python -m worker
Remove-Item Env:APP_PORT
```

Verify both processes:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-RestMethod http://127.0.0.1:8081/health
```

`GET /health` proves only that the HTTP process is alive. It does not claim
that Kafka, PostgreSQL, HDFS, Spark, or another dependency is ready.

`APP_ENV` and the existing Compose connection variables are preserved for
follow-up features. The base process does not use them to report false
readiness.

## Docker verification

Build from the repository root because the existing Worker Dockerfile copies
`AI/requirements.txt` and then the entire `AI/` directory:

```powershell
docker build `
  --file Infra/docker/worker/Dockerfile `
  --tag gitjob/worker:s15p21e102-79 `
  .
```

Smoke-test the two module commands sequentially:

```powershell
$container = docker run --rm --detach `
  --publish 127.0.0.1:18080:8080 `
  gitjob/worker:s15p21e102-79 python -m collector
try {
  Invoke-RestMethod http://127.0.0.1:18080/health
} finally {
  docker stop $container
}

$container = docker run --rm --detach `
  --publish 127.0.0.1:18081:8080 `
  gitjob/worker:s15p21e102-79 python -m worker
try {
  Invoke-RestMethod http://127.0.0.1:18081/health
} finally {
  docker stop $container
}
```
