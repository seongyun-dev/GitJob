# Assumed contract: AI contains requirements.txt and exposes collector/worker
# as Python modules. Both Compose services use this image with different
# module commands.

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# git is the repository analysis consumer's fetch mechanism; curl backs the
# Compose healthchecks.
RUN apt-get update \
  && apt-get install --no-install-recommends --yes curl git \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --system --uid 10001 --create-home appuser

WORKDIR /app
COPY AI/requirements.txt /tmp/requirements.txt
RUN pip install --requirement /tmp/requirements.txt
ARG JOBKOREA_OCR_ENABLED=false
COPY AI/requirements-ocr.txt /tmp/requirements-ocr.txt
# PaddleOCR is intentionally opt-in. The data-host deployment builds the
# collector and worker tags separately so only the collector pays the image
# size and runtime dependency cost. PaddlePaddle's CPU wheel uses its official
# package index; the OCR front-end and its remaining dependencies use PyPI.
RUN if [ "${JOBKOREA_OCR_ENABLED}" = "true" ]; then \
      apt-get update \
      && apt-get install --no-install-recommends --yes \
        libgl1 libglib2.0-0 libgomp1 \
      && rm -rf /var/lib/apt/lists/* \
      && python -m pip install paddlepaddle==3.2.0 \
        --index-url https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
      && python -m pip install --requirement /tmp/requirements-ocr.txt \
      && python -c "import paddle, paddleocr; print('PaddleOCR CPU runtime:', paddle.__version__, paddleocr.__version__)"; \
    fi
COPY AI/ ./

# Keep the existing /app module layout used by A's collectors. Package only
# the checked-in files referenced by approved Registry provenance separately.
COPY AI/common/server.py /opt/gitjob-provenance/AI/common/server.py
COPY AI/job/contracts.py /opt/gitjob-provenance/AI/job/contracts.py
COPY AI/job/fixtures/job_analysis_expected_v1.json AI/job/fixtures/job_analysis_input_v1.json /opt/gitjob-provenance/AI/job/fixtures/
COPY AI/requirements.txt /opt/gitjob-provenance/AI/requirements.txt
COPY BE/build.gradle /opt/gitjob-provenance/BE/build.gradle
COPY BE/src/main/java/com/example/git_job/GitJobApplication.java /opt/gitjob-provenance/BE/src/main/java/com/example/git_job/GitJobApplication.java
COPY FE/package.json /opt/gitjob-provenance/FE/package.json
COPY FE/src/main.tsx /opt/gitjob-provenance/FE/src/main.tsx
COPY Infra/compose/compose.yaml /opt/gitjob-provenance/Infra/compose/compose.yaml
COPY docs/data/2026-09-08-technology-registry-mvp.md /opt/gitjob-provenance/docs/data/2026-09-08-technology-registry-mvp.md
COPY BE/src/main/resources/db/c-compute/001_c_compute.sql /app/migrations/001_c_compute.sql
COPY BE/src/main/resources/db/c-compute/002_job_matching_projection.sql /app/migrations/002_job_matching_projection.sql
COPY BE/src/main/resources/db/c-compute/003_registry_review.sql /app/migrations/003_registry_review.sql
COPY BE/src/main/resources/db/c-compute/004_registry_review_source_identity.sql /app/migrations/004_registry_review_source_identity.sql
ENV C_REGISTRY_REPOSITORY_ROOT=/opt/gitjob-provenance
RUN python -c "from pathlib import Path; from analysis.rulepack import load_rule_pack; from registry.contracts import load_registry; registry = load_registry(Path('registry/data/technology_registry_20260911_4.json'), repository_root=Path('/opt/gitjob-provenance')); load_rule_pack(Path('analysis/data/rule_pack_20260911_4.json'), registry=registry)"

# Collector resume state (`collector-state:/data`). Created here, before the
# volume is ever mounted, because Docker seeds a fresh named volume from the
# image's directory — ownership included. Without this the volume is created
# root-owned and `appuser` cannot write the cursor or the identity store, so
# every run starts with an empty id set and re-collects postings.
RUN mkdir -p /data && chown appuser:appuser /data

EXPOSE 8080
USER appuser
CMD ["python", "-m", "worker"]
