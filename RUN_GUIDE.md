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


<!-- Dcoker things 

1. Verify Configuration Files
Ensure the following files exist and are correctly configured:

server/docker/Dockerfile: This builds your API image. It should install dependencies, copy the app code, and set the entrypoint.
server/docker-compose.yml: This orchestrates all services (API, DB, Redis, etc.).
server/scripts/start.sh: This script usually handles database migrations (alembic upgrade head) and starts the server.
.env file: Ensure your server/.env contains the correct connection strings for Docker services (e.g., DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/db).
2. Run Validation Commands
Open a terminal in the server directory and run these commands:

A. Build the Images
Check for any syntax errors in your Dockerfile or dependency issues.

powershell
cd server
docker-compose build
B. Start the Services
Verify that all services (DB, Redis, API) can start and communicate with each other.

powershell
docker-compose up -d
C. Check Container Status
Ensure all services are "Up" and healthy.

powershell
docker-compose ps
D. Inspect Logs
Check the API logs to ensure migrations were applied successfully and the server is listening.

powershell
docker-compose logs -f api
3. Functional Verification
Once the containers are running:

API Health: Open http://localhost:8000/docs in your browser. If it loads, the API is properly Dockerized and reachable.
Database Connection: Check the logs to ensure the API successfully connected to the postgres container. 



python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

$env:ENV="production"; python -m uvicorn app.main:app --reload





-->