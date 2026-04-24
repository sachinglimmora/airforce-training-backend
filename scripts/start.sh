#!/usr/bin/env bash
# Exit on error
set -o errexit

# Run database migrations
echo "Running migrations..."
alembic upgrade head

# Start the application
echo "Starting Gunicorn..."
gunicorn -k uvicorn.workers.UvicornWorker app.main:app \
    -b 0.0.0.0:8000 \
    --workers 4 \
    --timeout 120
