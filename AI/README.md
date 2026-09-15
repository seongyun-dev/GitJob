# GitJob AI

This directory contains the Python 3.12 runtime boundaries for GitJob's
collector and analysis worker. The collector exposes a liveness endpoint;
the worker also implements authenticated C computation and snapshot queries.
Registry matching, job quality/classification/demand, Evidence consumption,
Gap/recommendation/What-if, fact-grounded explanations, public GitHub artifact
observations, and separate JOB/GITHUB trends are implemented locally.
Stack Overflow and project recommendations are outside the current MVP.
Private repository Evidence attribution remains the B-team boundary.

`llm/` generates the per-technology summaries described under "Technology
summary generation" below. It explains levels the rules engine already decided;
it does not decide them.

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
├── Worknet_Collector_V1/   # 워크넷(고용24) 채용공고 수집기
├── Saramin_Collector_V1/   # 사람인 채용공고 수집기
├── GameJob_Collector_V1/   # 게임잡 채용공고 수집기 (기준 A 미통과, 스케줄 비활성)
├── Career_Collector_V1/    # 커리어 채용공고 수집기 (기준 A 미통과, 스케줄 비활성)
├── JobKorea_Collector_V1/  # 임시 JobKorea 백엔드 채용공고 수집기 (제외 결정)
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

## Technology summary generation

Issue `S15P21E102-256` implements the contract in
`docs/ai/technology-summary-contract.md`. The rules engine has already decided
L0~L3 before anything here runs; the local model only writes the Korean
sentence explaining why that level, and the level on screen always comes from
SQL. Handing the judgment back to the model would put two answers on one card
with no way to say which is right.

| | |
|---|---|
| Model | `qwen3.5:4b` on local Ollama |
| Context | 8,192 tokens |
| Request version | `technology-summary-request/v1` |
| Prompt version | `tech-summary/2026-09-15.1` |
| Unit | one user x one technology, one request |

```text
[BE] rule decision -> L0~L3
        v
[BE] Fact Pack
        v
[llm.service] Ollama -> validate -> retry at 0 -> template fallback
        v
[BE] store against cache_key
```

### Modules

| Module | What it owns |
|---|---|
| `llm/contracts.py` | Fact Pack and summary models, and the Ollama `format` schema |
| `llm/facts.py` | evidence rows -> at most eight deduplicated highlights |
| `llm/prompt.py` | system prompt, the one few-shot pair, the data-only envelope |
| `llm/validation.py` | the chapter 5 content checks and the template fallback |
| `llm/cache.py` | the key a stored summary is filed under |
| `llm/client.py` | the Ollama HTTP call |
| `llm/service.py` | ask, check, retry once, else fall back |
| `llm/server.py` | `POST /technology-summary` |
| `llm/smoke.py` | the hard cases, run against the real model |

`llm/test_server.py` stays as it is: it is the free-prompt smoke test for the
model itself, not part of this path.

### What the model is not given

Code snippets, commit SHAs, e-mail addresses, GitHub logins, evidence counts,
and other contributors' names. Counts are the important omission -- given
`SOLE_AUTHOR 32 / UNVERIFIED 12` the model writes "about 73%", and the
wireframe forbids ratios. `authorship` is therefore a band
(`MOSTLY_MINE`, `MIXED`, `MOSTLY_OTHERS`, `NOT_VERIFIED`), not a number.
`NOT_VERIFIED` means the commit could not be tied to the account, not that the
person did not write the code, and both the prompt and the validator keep the
summary from asserting otherwise.

`user_id` is passed to the service, never into the prompt: it is needed to
separate two people's cache entries, and a value that points at a person has no
business in a summary.

### Fact types

`llm/contracts.py` mirrors `FactTypeV3` in `analysis/results.py` -- all seven
types the rules engine emits -- and a test asserts the two stay equal. The
contract document names three (`API_CALL`, `IMPORT`, `DEPENDENCY`), which is one
type short of usable: in `analysis/data/rule_pack_20260911_4.json`, L3 rules are
built from `API_CALL`, `ANNOTATION`, `SYNTAX_NODE` and `CONFIG_KEY`, so three
types would drop most L3 evidence -- including the `@EnableMethodSecurity` the
contract's own example asks about, which is an `ANNOTATION` fact.

`CONFIG_KEY` highlights carry `KEY` and never `VALUE`. A config value is
whatever the file says, which can be a connection string or a password, and
neither a prompt nor a card sentence is a place for one.

### Two fields the model does not get to decide

`confidence` is a function of the Fact Pack -- whether the person's own
evidence held an API call -- so it is computed in `derive_confidence` and the
model's value is overwritten. This is a deliberate deviation from the contract,
which has the model emit it: measured on `qwen3.5:4b`, a dependency-only input
comes back `HIGH`, which would put a band on the card that the evidence below
it contradicts. The model's own value is reported as `model_confidence` when the
two disagree, so the drift stays visible in the backend's logs.

`gap` is still written by the model, but its presence is now checked: null with
a non-null `next_level` is rejected, and vice versa. The contract implies this;
it is not in the chapter 5 table because the behaviour only shows up against a
real model. Measured: the model folds the gap wording into `summary` and leaves
the field null, which drops the one sentence that makes the card actionable.

### Validation and fallback

Ollama's `format` makes the reply syntactically valid JSON. It does not make it
true, so `validate_summary` runs every check in chapter 5 and any one failure
discards the response. The check that matters is the last one: every English
identifier in the prose must already appear in the Fact Pack. Beyond the
contract's list, the allowed set also includes `highlights.file` -- the
contract's own worked example names `SecurityConfig` and `build.gradle`, which
exist only as file paths.

```text
reject -> retry once at temperature 0
reject -> template sentence, llm_status = FALLBACK
```

The template names the levels, as chapter 5 writes it, which is the one place a
level string is allowed in prose. A failed generation never empties the card:
the level, the evidence and the permalinks are on screen without the model.

### Run locally

Start Ollama first. On the AI server host that means the WSL-native path --
`bash Infra/scripts/llm-serve-wsl.sh` from the repository root, which is
idempotent and also pulls the model if it is missing. See
`docs/infra/local-llm-runbook.md` ch3.1 for the one-time install and why the
container path does not apply there. Then:

On the WSL host, from `AI/`:

```bash
APP_PORT=8082 ../.venv/bin/python -m llm
```

On the Windows notebook, from `AI/`:

```powershell
$python = "..\.venv\Scripts\python.exe"
$env:APP_PORT = "8082"
& $python -m llm
Remove-Item Env:APP_PORT
```

`OLLAMA_BASE_URL`, `LLM_MODEL` and `OLLAMA_TIMEOUT_SECONDS` are the same
variables the test server reads. WSL-native Ollama is at
`http://127.0.0.1:11434`, which is the default; from inside a container it is
`http://host.docker.internal:11434`.

```bash
curl -s http://127.0.0.1:8082/health

# jq is not installed on this host, so the venv's Python builds the body.
../.venv/bin/python -c 'import json,sys;
print(json.dumps({"user_id": "user-1", "fact_pack": json.load(open(
  "llm/fixtures/technology_summary_request_v1.json"))}))' \
  | curl -s -X POST http://127.0.0.1:8082/technology-summary \
      -H 'Content-Type: application/json' --data @-
```

The endpoint always answers 200. A model that is down, slow, or ungrounded
comes back as `llm_status: FALLBACK` with the rejected attempts listed by
failure code, because the caller is rendering a card that is already complete
without it.

Run only this suite with:

```powershell
& $python -m pytest tests/test_llm_contracts.py tests/test_llm_facts.py `
  tests/test_llm_prompt.py tests/test_llm_validation.py `
  tests/test_llm_cache.py tests/test_llm_service.py tests/test_llm_server.py -q
```

### Reaching it from the deployed stack

The EC2 service host has no GPU, so the generator stays on the notebook and the
call goes EC2 -> notebook. The two are on the same tailnet, so no SSH tunnel is
involved; what is needed is a listener on the Windows Tailscale address, because
the server itself runs inside WSL. This notebook is the GPU host and stays up as one, so all three pieces are
services rather than windows someone has to remember to open:

```bash
bash Infra/scripts/llm-install-services-wsl.sh   # WSL: systemd user units, once
```
```powershell
powershell -ExecutionPolicy Bypass -File `
  \\wsl.localhost\Ubuntu-24.04\home\ssafy\workspace\S15P21E102\Infra\scripts\llm-bridge-install-task.ps1
```

| | |
|---|---|
| `gitjob-ollama.service` | inference runtime on `127.0.0.1:11434` |
| `gitjob-llm-summary.service` | this FastAPI app on `0.0.0.0:18080` |
| `GitJob LLM Tailscale Bridge` | Windows logon task publishing 18080 on the tailnet |

One step still needs root and is not automated:
`sudo loginctl enable-linger ssafy`. Without it both units stop when the last
WSL session closes.

`docs/infra/local-llm-runbook.md` ch3.2 has the diagram, the reason the existing
`netsh portproxy` rule does not bind on its own, and the verification commands.
Verified on 2026-09-14: `gitjob-service-backend-1` on EC2 posted a Fact Pack and
got `llm_status: OK` back.

`LLM_SUMMARY_BASE_URL` and `LLM_SUMMARY_TIMEOUT_SECONDS` are in `.env.example`
for the backend call that does not exist yet. Empty has to mean "do not call":
the card is complete without a summary.

### Checking it against the real model

The unit tests use a fake client. They prove the code is right and say nothing
about whether a 4B model can satisfy the contract, so there is a second runner
that asks the real one:

```bash
../.venv/bin/python -m llm.smoke
```

Its five cases are all ones the model got wrong at least once; the `why` line in
`llm/fixtures/technology_summary_smoke_cases.json` says what each is for. A
fallback is a working outcome, not a crash, so the run never fails -- the count
is the signal. On this host, three consecutive runs each gave **4 OK / 1
FALLBACK**, warm, at 3-8 seconds per technology.

The one that keeps falling back is `NOT_VERIFIED`: the model writes the summary
correctly but then puts "본인이 직접 작성한 코드에서 …" in the `gap`, which
presupposes it knows whose code it is. Three prompt revisions did not remove it,
so it is left to the fallback rather than tuned further. `GRADE_WORD` is the
other recurring rejection, and the temperature-0 retry clears it most times.
Raising that count after a prompt edit means the edit made things worse.

### Picking this up

The AI server host is this WSL distro. Ollama runs natively there, not in
Docker: the daemon is not running, WSL integration is off, and `sudo` wants a
password, so `Infra/scripts/llm-up.sh` does not apply. Use
`Infra/scripts/llm-serve-wsl.sh` (idempotent; safe to run before anything that
needs the model) and read `docs/infra/local-llm-runbook.md` ch3.1 for the
one-time install and the measured GPU numbers.

Order to read the code in: `contracts.py` (what crosses the boundary) ->
`facts.py` (how evidence becomes highlights) -> `prompt.py` -> `validation.py`
(where responses die) -> `service.py` (the loop that ties them together).
`docs/ai/technology-summary-contract.md` is the handed-over contract; its ch9
lists every place the implementation deviates and why, so read that before
"fixing" something back to the contract's letter.

Three tests in the wider suite fail on this branch and on its base commit
alike, unrelated to this work: `test_analysis_parse.py::test_report_summarises_what_it_read`,
`test_analysis_personal_consumer.py::test_consumer_publishes_v4_without_identity_in_the_request_event`,
and `test_worknet.py::test_period_deadline_makes_the_posting_active`.

Pushing needs a GitLab token; `git fetch` fails without one. Pass it as a
one-shot credential helper rather than writing it into `.git/config` or a
remote URL:

```bash
git -c credential.helper= \
    -c credential.helper='!f() { echo username=oauth2; echo "password=$(cat /path/to/token)"; }; f' \
    push origin <branch>
```

`.git/refs/remotes/origin/infra/` is owned by root from an earlier run, so
fetching `infra/*` branches prints "cannot lock ref". Every other branch
fetches; fixing it needs `sudo chown`.

### Still owned by the backend

Assembling the Fact Pack: the `authorship` band, `next_level.missing`, the
personal-commit `period`, and reading `value` out of `fact_payload`.
`llm/facts.py` provides the last two steps of that -- the per-`fact_type` key
order and the deduplication -- but the queries themselves are backend work, as
is storing the summary against `cache_key`. Chapter 7 of the contract lists
what is missing.

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
