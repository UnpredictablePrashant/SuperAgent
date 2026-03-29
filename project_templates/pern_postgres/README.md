# PERN Starter (Postgres + Express + React + Node)

This is a complete, runnable PERN template with:
- Express + TypeScript API
- Prisma ORM with Postgres
- Auth microservice (JWT)
- Vite + React + Tailwind frontend
- Dockerized Postgres

## Quick Start

```bash
# 1) Start Postgres
docker-compose up -d

# 2) Backend
cd app
npm install
npx prisma migrate dev --name init
npm run dev

# 3) Auth service (new terminal)
cd ../services/auth-service
npm install
npx prisma migrate dev --name init
npm run dev

# 4) Frontend (new terminal)
cd ../frontend
npm install
npm run dev
```

The API runs on `http://localhost:3000` by default.
The auth service runs on `http://localhost:4001`.
The frontend runs on `http://localhost:5173`.

## Environment

Copy `.env.example` to `.env` and update values if needed.
