# 🚀 Glimmora Aegis Aerospace — Backend

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![PostgreSQL](https://img.shields.io/badge/postgres-%23316192.svg?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/redis-%23DD0031.svg?style=for-the-badge&logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)

The **Aegis Backend** is the foundational service for the Glimmora Aegis Aerospace training platform. It provides a robust, scalable, and secure API for managing pilot training, content ingestion, AI-driven RAG (Retrieval-Augmented Generation), and VR telemetry analytics.

---

## 🛠 Tech Stack

| Layer | Choice |
| :--- | :--- |
| **Language** | Python 3.11+ |
| **Framework** | FastAPI (Async) |
| **Database** | PostgreSQL 16 + `pgvector` |
| **Cache / Task Queue** | Redis 7 + Celery |
| **ORM** | SQLAlchemy 2.0 (Async) + Alembic |
| **Auth** | JWT (RS256) + bcrypt |
| **Search** | Meilisearch |
| **Storage** | MinIO (S3-compatible) |
| **Container** | Docker + Docker Compose |

---

## ✨ Key Features

- **🛡️ Secure Auth & RBAC**: Stateless JWT authentication with refresh token rotation and granular role-based access control.
- **📄 Content Ingestion**: Automated parsing of aviation manuals (FCOM, QRH, AMM, SOP) with high-fidelity citation mapping.
- **🤖 AI Integration**: Gateway to Gemini and OpenAI with built-in PII filtering and response caching.
- **✈️ Training Engines**: Specialized engines for checklists, normal/emergency procedures, and high-risk scenarios.
- **📊 Analytics & Compliance**: In-depth tracking of training sessions, deviations, and competency evidence.
- **🥽 VR Telemetry**: High-volume ingestion of VR telemetry data for performance evaluation.
- **📜 Audit Log**: Tamper-evident audit logging with hash chaining for regulatory compliance.

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.11+
- Docker & Docker Compose
- PostgreSQL, Redis (if running locally without Docker)

### 2. Local Environment Setup
```bash
# Clone the repository
git clone https://github.com/sachinglimmora/airforce-training-backend.git
cd airforce-training-backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .
```

### 3. Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

### 4. Running with Docker (Recommended)
```bash
docker-compose up --build
```
The API will be available at `http://localhost:8000`.

---

## 📖 Documentation

- **Interactive API Docs**: Once running, visit `/api/v1/docs` (Swagger UI) or `/api/v1/redoc` (ReDoc).
- **Full Specification**: See [BACKEND_API_DOCUMENTATION.md](./BACKEND_API_DOCUMENTATION.md) for detailed design specs.
- **Deployment Guide**: See [DEPLOYMENT_RENDER.md](./DEPLOYMENT_RENDER.md) for Render.com setup.

---

## 📂 Project Structure

```text
app/
├── core/           # Security, Permissions, Exceptions
├── middleware/     # Auth, RBAC, Audit, Rate Limiting
├── modules/        # Domain-driven modules (Auth, AI, Training, etc.)
├── database.py     # Database configuration
├── config.py       # Pydantic settings
└── main.py         # FastAPI application entry point
alembic/            # Database migrations
docker/             # Dockerfile and entrypoint scripts
scripts/            # Utility scripts (seed_db, generate_keys)
tests/              # Unit and integration tests
```

---

## 🤝 Contributing
Owner: **Sachin (Backend)**
Collaborators: Harish (Frontend), Shreyansh (AI/RAG), Subhash (VR), Chinmay (Assets).

---

## ⚖️ License
Internal Use Only - Glimmora Aerospace.
