# Assumed contract: AI contains requirements.txt and exposes collector/worker
# as Python modules. Both Compose services use this image with different
# module commands.

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
  && apt-get install --no-install-recommends --yes curl \
  && rm -rf /var/lib/apt/lists/* \
  && useradd --system --uid 10001 --create-home appuser

WORKDIR /app
COPY AI/requirements.txt /tmp/requirements.txt
RUN pip install --requirement /tmp/requirements.txt
COPY AI/ ./

EXPOSE 8080
USER appuser
CMD ["python", "-m", "worker"]
