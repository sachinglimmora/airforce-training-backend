# 🚀 Aegis Backend - Execution Guide

This guide contains the exact commands and steps required to run the Aegis Aerospace Training Backend.

---

## 1. Local Development Setup

### Prerequisites
* Python 3.11+
* Docker Desktop (for Postgres/Redis/Meilisearch)

### Initial Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file (if not exists)
# Copy from .env.example or use the values provided below
```

### Running Infrastructure (Docker)
```bash
docker-compose up -d
```

### Starting the Server
```bash
# Run with auto-reload for development
python -m uvicorn app.main:app --reload
```
The API will be available at: `http://localhost:8000`
Swagger Docs: `http://localhost:8000/api/v1/docs`

---

## 2. Database Management

### Run Migrations (Apply Schema)
Use this command whenever models are changed or when setting up a new database.
```bash
python -m alembic upgrade head
```

### Seed Database (Create Admin & Roles)
Populates the database with default roles, aircraft types, and the initial admin user.
```bash
python scripts/seed_db.py
```
**Default Admin Credentials:**
* **Email:** `admin@aegis.internal`
* **Password:** `Aegis@Admin2026!`

---

## 3. Production Deployment (Render)

### Environment Variables
Ensure these are set in the Render Dashboard:
* `ENV`: `production` (hides docs) or `development` (shows docs)
* `DATABASE_URL`: Your Render Postgres External URL
* `REDIS_URL`: Your Render Redis URL
* `GEMINI_API_KEY`: Your Google AI API Key

### Deployment Commands
Render uses the `docker/Dockerfile` automatically. The startup script is `scripts/start.sh`, which performs:
1. `python -m alembic upgrade head` (Auto-migrations)
2. `gunicorn` (Production server)

---

## 4. Troubleshooting

### "ModuleNotFoundError: No module named 'alembic'"
If you see this during deployment, ensure you are using `python -m alembic` instead of just `alembic`. This forces the use of the project's installed packages.

### Connecting with pgAdmin 4
1. **Host:** [From Render External URL]
2. **Maintenance DB:** `aegisair`
3. **User:** `aegisdbuser`
4. **SSL Mode:** `Require`

---

## 5. Useful API Endpoints
* **Health Check:** `GET /health`
* **Auth Login:** `POST /api/v1/auth/login`
* **User Info:** `GET /api/v1/auth/me`
