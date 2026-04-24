FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if needed (e.g., libpq for postgres)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# Copy application code
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
