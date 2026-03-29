# FastAPI + Postgres Template

This template includes:
- FastAPI app with JWT auth scaffolding
- SQLAlchemy async + Alembic
- Dockerized Postgres

## Quick Start

```bash
# 1) Start Postgres
docker-compose up -d

# 2) Create venv + install deps
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3) Run migrations
alembic upgrade head

# 4) Start API
uvicorn app.main:app --reload
```

Health check: `GET http://localhost:8000/health`

## Environment
Copy `.env.example` to `.env` and update values if needed.
