# GitJob AI

This directory contains the Python 3.12 runtime boundaries for GitJob's
collector and analysis worker. The collector exposes a liveness endpoint;
the worker also implements authenticated C computation and snapshot queries.
Registry matching, job quality/classification/demand, Evidence consumption,
Gap/recommendation/What-if, fact-grounded explanations, public GitHub artifact
observations, and separate JOB/GITHUB trends are implemented locally.
Stack Overflow and project recommendations are outside the current MVP.
Private repository Evidence attribution remains the B-team boundary.

Start with the Korean [C-team implementation guide](../docs/ai/README.md)
for the feature map, ownership, Evidence decisions, and integration order.
[Verification and remaining acceptance](../docs/ai/c-mvp-verification.md)
separates synthetic tests, actual public-data reads, and service integration.

Detailed implementation and integration contracts:

- [Job cohort and demand](../docs/ai/c-job-demand.md)
- [Evidence consumption](../docs/ai/c-recommendation.md) and
  [recommendation/What-if](../docs/ai/c-recommendation-engine.md)
- [Fact-grounded explanation](../docs/ai/c-recommendation-explanation.md)
- [Public GitHub observations](../docs/ai/c-public-analysis.md),
  [partition/resume pipeline](../docs/ai/c-public-pipeline.md), and
  [source-specific trends](../docs/ai/c-public-trend.md)
- [C API, PostgreSQL migration and runtime](../docs/ai/c-compute-runtime.md)
- [Completion-event client and CLI](../docs/ai/c-compute-client.md)

Local execution does not establish production deployment or B/FE integration.
The worker requires an explicit database migration and a service token before
computation is ready; `/health` alone remains only a liveness check.

The [September 7 Registry/classification report](../docs/ai/2026-09-07-registry-job-review-implementation.md)
is historical and does not describe the full current C implementation.

## Package boundaries

```text
AI/
├── collector/       # collector process entrypoint
├── worker/          # analysis worker process entrypoint
├── common/          # shared process infrastructure
├── registry/        # Technology Registry analysis
├── job/             # job-posting analysis
├── recommendation/  # Evidence consumption, Gap, What-if and explanation
├── trend/           # separate JOB and GITHUB metrics
├── stackoverflow/   # historical boundary; excluded from current MVP
├── github/          # GitHub 수집 경계와 A→C Repo Snapshot 계약
├── Worknet_Collector_V1/   # 워크넷 채용공고 수집기
├── Saramin_Collector_V1/   # 사람인 채용공고 수집기
├── GameJob_Collector_V1/   # 게임잡 채용공고 수집기
├── JobKorea_Collector_V1/  # 임시 JobKorea 백엔드 채용공고 수집기
├── llm/             # Fact-grounded LLM behavior
└── tests/
```

The domain packages do not contain placeholder results. The `github` package
contains the bounded GitHub collection client used by the Repo Fetch
Orchestrator; semantic technology analysis remains outside that client.

The temporary JobKorea collector documented below is an explicit standalone
exception for this short-lived collection task.

## Windows and PowerShell setup

Run these commands from `AI/` with Python 3.12 available as `py -3.12`.
The example creates a virtual environment at the repository root. Reuse an
existing project environment (including `AI/.venv`) when already configured;
adjust `$python` accordingly. `.dockerignore` excludes both locations:

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
$env:PYTHONPATH = (Get-Location).Path + ";" + (Resolve-Path ..\Infra\spark).Path
& $python -m pytest
& $python -m ruff check .
& $python -m ruff format --check .
```

Database integration tests require an explicitly selected, isolated PostgreSQL
database in `C_COMPUTE_TEST_DATABASE_URL`; without it those tests skip. Do not
point tests at an operating database. The [verification guide](../docs/ai/c-mvp-verification.md)
records the full-run conditions and pre-existing lint failures.

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

The v1 input contract is established; it is not waiting for a new schema design.
Current [completed-input intake](../docs/ai/c-compute-runtime.md) validates actual
writer manifests and JSON batches, while [input union and demand](../docs/ai/c-job-demand.md)
define how later closed/changed observations affect the C cohort. Operating input
mounts, sufficient valid postings, and original posting-date quality remain
acceptance work. C owns validation, semantic duplicate adjudication, Registry
matching, classification, and downstream facts. No online source client is part
of the contract boundary described above.

## Registry Mapper and job requirement classification

Issue `S15P21E102-81` is implemented in `registry/mapper.py`. Callers provide
an exact source type, raw value, optional package/import ecosystem, and context.
The result is `MATCHED`, `AMBIGUOUS`, or `UNKNOWN` and always includes ordered
candidate IDs, structured match evidence, and the Registry version used.
Display-name matching for the short names C, R, and Go remains ambiguous unless
the context contains an adjacent, explicit programming-language signal.

Issue `S15P21E102-82` is implemented in `job/classifier.py`. It consumes the
unchanged `JobAnalysisInputBatch` and produces the separate
`job-technology-classification/v1` model. Each source mention produces one
classification result, so repeated evidence is not collapsed. Results retain
the original evidence text, section, source surface, character location, and
mapping context. Each output record also preserves the canonical/source job
identity, source URL, job/category/company/region dimensions, posting state and
dates, collection time, and source content hash required by a later demand
aggregation job. Registry and `job-requirement-rules/v4` parser versions remain
explicit. Version v4 retains the v2/v3 responsibilities and `우대 자격 요건`
policies and recognizes decorated/numbered headings such as `📋 주요업무`,
`2. 자격요건`, and `3. 우대사항`. Responsibilities (`담당업무`, `주요업무`,
`업무내용`, `responsibilities`) count as `REQUIRED`, including when the collector
carried `PREFERRED` from an earlier section. The original input type and label
remain unchanged in the output alongside the parsed section and correction reason.
Unrecognized source labels no longer suppress section correction at the evidence
offset. Other conflicting section/input signals and unresolved Registry matches
remain `REVIEW_REQUIRED`.

C also scans the original body through the evidence offset for complete
required/preferred/general headings, without a fixed preceding-line window.
`parsed_section` preserves this observation separately from A's
`evidence_section`; explicit A section labels remain authoritative, while a
missing/generic label can use the parsed boundary. A requirement that conflicts
with the corresponding general section requires review. Different technologies
sharing one evidence sentence share its location.

The unchanged V1 collector limits preceding-section searches and collapses
mentions by technology/requirement/surface. C preserves every delivered mention,
but cannot restore evidence already discarded upstream. Synthetic tests invoke
the actual collector extractor, validate the A-to-C contract, and run C mapping
and classification. On 2026-09-07, a bounded live probe (August date range,
one list page, three rows, existing delays, one attempt, OCR disabled) returned
no in-range records. This does not establish real-posting end-to-end validation;
the sample and manifest stay outside the repository.

Run the focused suites from `AI/` with `AI` on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = (Get-Location).Path
& $python -m pytest tests/test_registry_mapper.py tests/test_job_classifier.py -q
Remove-Item Env:PYTHONPATH
```

## C-side Registry review and reprocessing

Issue `S15P21E102-88`'s C-side boundary is implemented in
`registry/review.py`. `ReviewStore` writes an atomic, caller-path JSON snapshot,
supports status queries, records automatic and manual attempts separately, and
reprocesses pending records with a caller-supplied newer `RegistryMapper`.
Stable review IDs make repeated ingestion idempotent. Source record IDs, source
site/URL/surface, full mapping context, candidates, reasons, evidence, decision
actor/note, and version history remain queryable.

This local file store is executable verification of C-team behavior, not the
B-team administrator API or operating database. B-team integration must supply
the approved Registry snapshot and explicit review decision while preserving
the same provenance and attempt-history semantics.
The completed C boundary and the pending integration agreement are documented
in [the Registry contract](../docs/data/2026-09-01-technology-registry-v1.md#10-c측-review-구현과-b측-통합-경계).

## Temporary JobKorea backend crawler

The temporary `AI/JobKorea_Collector_V1` tool collects ordinary `백엔드개발자`
category postings registered during an inclusive date range. It uses
JobKorea's public category-list response sorted by registration date, follows
the public detail iframe when enabled, validates every record against the
`job-analysis-input/v1` contract, and writes a run-specific JSON/CSV snapshot
plus a manifest.

Run from the repository root after installing `requirements-dev.txt`:

```powershell
$python = ".\.venv\Scripts\python.exe"
$env:PYTHONPATH = "AI"
& $python -m JobKorea_Collector_V1 `
  --start-date 2026-08-01 `
  --end-date 2026-08-31 `
  --output-dir data\jobkorea
Remove-Item Env:PYTHONPATH
```

Use `--no-detail --max-pages 1 --request-delay 0` for a quick list-only
smoke run. The default date range is `2026-08-01` through `2026-08-31` and
`--end-date` is inclusive. Each run is written under
`data/jobkorea/<pipeline-run-id>/`.

This is a temporary, rate-limited public-page collector. It does not log in,
solve CAPTCHA, or bypass access controls. JobKorea's detail page states that
the information must not be copied, redistributed, or repurposed without
consent and is for job-seeking use; keep generated snapshots internal and
respect the site's terms and request limits. The result is limited to postings
that are still exposed by the public category listing; postings already
removed from that listing cannot be reconstructed by this tool.

### GUI

The same crawler is available as a local Streamlit GUI. It provides date and
request settings, OCR controls, progress, result tables, technology summaries,
OCR diagnostics, and downloads for the generated JSON/CSV/manifest files.

Install the GUI dependency and start it from the repository root:

```powershell
$python = ".\.venv\Scripts\python.exe"
& $python -m pip install -r AI\requirements-gui.txt
$env:PYTHONPATH = "AI"
& $python -m streamlit run AI\JobKorea_Collector_V1\gui.py
Remove-Item Env:PYTHONPATH
```

The browser page opens on the local Streamlit address shown in the terminal.
Install `AI\requirements-ocr.txt` as described below when the GUI should also
recognize image-based postings.

### Image OCR and technology extraction

Image OCR is enabled by default. The collector uses PaddleOCR's Korean model
for image sources discovered in the detail iframe, then appends the recognized
text under `[OCR 이미지]` before extracting technology mentions. Each mention
keeps its source surface (`TITLE` or `BODY`), evidence text, extraction method,
and requirement type (`REQUIRED`, `PREFERRED`, or `MENTIONED`). The raw
`body_status` remains `IMAGE_ONLY` when the source body is image-only, so the
original source condition is not hidden by OCR output.

Install the optional OCR dependency in the same virtual environment. Paddle
Paddle is installed separately because its CPU/GPU wheel depends on the target
platform; the official [PaddleOCR quick start](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/quick_start.en.md)
has the current selector and wheel commands. For a WSL CPU setup, an example
is:

```powershell
$python = ".\.venv\Scripts\python.exe"
& $python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
& $python -m pip install -r AI\requirements-ocr.txt
```

The first OCR run may download model files. Use `--ocr-device gpu:0` when the
environment has a supported Paddle GPU installation, or `--no-ocr` to collect
the postings without image recognition. OCR status, image URLs, confidence,
and per-image errors are recorded in `manifest.json`; the normalized mentions
are present in both the JSON contract and the `technology_mentions` CSV column.
If PaddleOCR is unavailable, the crawler records a warning and preserves the
image-only record for later reprocessing.

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

`APP_ENV` and the existing Compose connection variables are preserved.
The worker uses the configured PostgreSQL connection and `C_COMPUTE_TOKEN`;
authenticated `/ready` checks that the explicit C migration is present.
Follow the runtime contract above to configure computation. Missing database
or token configuration does not turn a liveness response into readiness.

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
