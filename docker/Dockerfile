FROM python:3.11-slim AS builder
WORKDIR /build

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install build

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN pip install --target=/deps -e . 2>/dev/null || pip install --target=/deps \
    fastapi uvicorn[standard] gunicorn sqlalchemy[asyncio] asyncpg alembic pydantic pydantic-settings \
    pyjwt[crypto] bcrypt redis celery google-generativeai openai httpx structlog python-multipart \
    meilisearch-python-async cryptography python-jose[cryptography]


FROM python:3.11-slim
WORKDIR /app

COPY --from=builder /deps /usr/local/lib/python3.11/site-packages
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts/start.sh ./scripts/start.sh
RUN chmod +x ./scripts/start.sh

EXPOSE 8000
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

CMD ["./scripts/start.sh"]
