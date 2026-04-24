FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if needed (e.g., libpq for postgres)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY pyproject.toml README.md* ./
RUN pip install --upgrade pip && \
    pip install fastapi uvicorn[standard] gunicorn sqlalchemy[asyncio] asyncpg alembic pydantic pydantic-settings \
    pyjwt[crypto] bcrypt redis celery google-generativeai openai httpx structlog python-multipart \
    meilisearch-python-async cryptography python-jose[cryptography] email-validator

# Copy application code
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts

# Install the project itself
RUN pip install .
RUN chmod +x ./scripts/start.sh

EXPOSE 8000

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

CMD ["./scripts/start.sh"]
