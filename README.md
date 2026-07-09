# Agentic Calling Platform

Production AI outbound sales-calling platform — the first module of a larger
sales-engagement product. Places human-like AI phone calls (Plivo) with
streaming speech (Sarvam STT/TTS) and reasoning (OpenRouter), records to
Cloudflare R2, and manages campaigns, contacts, CRM, and analytics.

## Architecture

Clean architecture. Business logic depends on **provider interfaces (ports)**,
never on vendors directly, so any vendor can be swapped without refactoring:

| Port (`app/providers/base.py`) | Adapter (added later) |
|--------------------------------|-----------------------|
| `TelephonyProvider`            | Plivo                 |
| `SpeechToTextProvider` / `TextToSpeechProvider` | Sarvam |
| `LLMProvider`                  | OpenRouter            |
| `StorageProvider`              | Cloudflare R2         |

**Stack:** FastAPI · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · Supabase
Postgres · Upstash Redis · Docker. Frontend (Next.js 15) arrives in Feature 7.

```
backend/app/
  core/        config, logging, database, redis, exceptions
  models/      SQLAlchemy models (Base + mixins)
  providers/   vendor-agnostic ports + adapters
  api/         routers, deps, routes/
  schemas/     Pydantic request/response models
  repositories/ data-access layer
  services/    business logic
```

## Local development

```bash
cd backend
cp .env.example .env          # fill in secrets
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt

alembic upgrade head          # apply migrations (none yet in Feature 1)
uvicorn app.main:app --reload
```

Then open:
- http://localhost:8000/docs — Swagger UI
- http://localhost:8000/api/v1/health — liveness
- http://localhost:8000/api/v1/health/ready — checks Postgres + Redis

Or with Docker:

```bash
docker compose up --build      # uses backend/.env (cloud Supabase + Upstash)
```

## Configuration notes

`config.py` normalizes two things automatically so the provided `.env` works:
- `DATABASE_URL` `postgresql://` → `postgresql+asyncpg://` with SSL for Supabase.
- `REDIS_URL` shell command (`redis-cli --tls -u redis://…`) → clean `rediss://`.

Still, prefer clean values in `.env` (see `.env.example`). Set a strong
`JWT_SECRET` and add R2 keys before Feature 5.

## Deployment

- **Backend** → Railway (`railway.json`, Dockerfile, healthcheck on `/api/v1/health`).
- **Frontend** → Vercel (Feature 7).

## Build roadmap

1. **Foundation** ✅ — scaffold, config, async DB + Redis, provider ports, health, Alembic, Docker
2. Auth & tenancy — orgs, users, JWT + refresh, RBAC, API keys
3. AI agents + concrete providers (Plivo/Sarvam/OpenRouter/R2)
4. Contacts & campaigns (CSV, scheduling, concurrency)
5. Call engine — streaming STT→LLM→TTS, recordings
6. Post-call — transcripts, AI summaries, CRM, analytics
7. Frontend dashboard (Next.js)
```
