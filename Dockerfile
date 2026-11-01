# Service image for the agent gateway. The reasoning model runs on Anthropic's
# API, so this image carries no model weights and needs no GPU. The Llama Guard 4
# safety classifier runs in its own model-server container (see docker-compose).

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System build deps for psycopg and spaCy wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first for layer caching.
COPY pyproject.toml requirements.txt README.md ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Presidio's default recognizers need a spaCy model. Pull it once at build time.
RUN python -m spacy download en_core_web_lg

# Now the source.
COPY src ./src
COPY eval ./eval
RUN pip install -e .

# Run as a non-root user.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Secrets are provided at runtime via env/--env-file, never baked in.
CMD ["uvicorn", "support_agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
