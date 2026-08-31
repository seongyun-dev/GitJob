# GitJob AI

This directory contains the Python 3.12 runtime boundaries for GitJob's
collector and analysis worker. Both processes currently expose only a
liveness endpoint. Technology normalization, job analysis, GitHub trend,
Stack Overflow, and LLM behavior belong to their own follow-up issues.

## Package boundaries

```text
AI/
├── collector/       # collector process entrypoint
├── worker/          # analysis worker process entrypoint
├── common/          # shared process infrastructure
├── registry/        # Technology Registry analysis
├── job/             # job-posting analysis
├── stackoverflow/   # Stack Overflow analysis
├── github/          # GitHub analysis
├── llm/             # Fact-grounded LLM behavior
└── tests/
```

The domain packages are boundaries only. They do not contain placeholder
results or external-system clients.

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
