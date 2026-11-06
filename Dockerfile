# Service image for the agent gateway. The reasoning model runs on Anthropic's
# API, so this image carries no model weights and needs no GPU. The Llama Guard 4
# safety classifier runs in its own model-server container (see docker-compose).

FROM python:3.12.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_CACHE_HOME=/tmp/.cache \
    TLDEXTRACT_CACHE=/tmp/tldextract

WORKDIR /app

# System build deps for psycopg and spaCy wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for layer caching.
COPY pyproject.toml requirements.lock README.md ./
RUN pip install --require-hashes -r requirements.lock

# Presidio's default recognizers need a spaCy model. Pull it once at build time.
RUN pip install --no-deps https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.8.0/en_core_web_lg-3.8.0-py3-none-any.whl

# Now the source.
COPY src ./src
COPY eval ./eval
COPY website ./website
COPY knowledge_base/approved ./knowledge_base/approved
RUN pip install --no-deps -e .

# Run as a non-root user.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Secrets are provided at runtime via env/--env-file, never baked in.
HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=10)" || exit 1

CMD ["uvicorn", "support_agent.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--limit-concurrency", "40", "--timeout-keep-alive", "5", "--no-access-log"]
