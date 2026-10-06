# AI Travel Platform

The new full-stack platform being built **next to** the existing support assistant in
`customer_support_chat/`. It follows the product spec in phases; the existing assistant's
agents, RAG pipeline and knowledge base are ported in during phases 3–5, after which
`customer_support_chat/`, `vectorizer/` and the Streamlit UI are retired.

```text
browser ──► frontend/ (Next.js 16, React 19, TypeScript, Tailwind, shadcn/ui)
              │  /api/* route handler forwards to the backend (same origin, httpOnly cookies)
              ▼
            backend/ (FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2)
              ▼
            PostgreSQL 17 + pgvector
```

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Architecture, database, authentication, Docker, basic frontend/backend, health checks | **Done** |
| 2 | Document upload, object storage, text extraction, OCR, classification, structured extraction | Not started |
| 3 | Chunking, embeddings in pgvector, user-document RAG, knowledge-base RAG, hybrid retrieval | Not started |
| 4 | Gemini service, structured output, conversation memory, supervisor agent | Not started |
| 5 | Flight, hotel, car, excursion and document agents | Not started |
| 6 | Mock booking providers; flight/hotel/car booking and cancellation | Not started |
| 7 | Real provider adapter, price revalidation, confirmation tokens, idempotency, booking state machine | Not started |
| 8 | Chat UI, documents UI, bookings UI, flight cards, confirmation dialogs | Not started |
| 9 | Redis-backed rate limiting, PII protection, prompt-injection defences, admin panel | Partly (see below) |
| 10 | Unit/integration/E2E tests, CI/CD, production Docker builds | Partly (see below) |
| 11 | Deployment config, monitoring, full documentation | Not started |

### What phase 1 delivers

**Backend (`backend/`)**
- Email/password accounts: Argon2 hashing, JWT access tokens (httpOnly, SameSite=Lax cookie
  for the browser, `Authorization: Bearer` for API clients), CSRF double-submit check for
  cookie-authenticated writes, roles (`user` / `admin`).
- Sign-in protection: per-account temporary lockout after repeated failures, per-IP rate
  limit on auth endpoints, identical response for unknown email vs wrong password.
- Token revocation: "sign out everywhere" and password change invalidate all issued tokens.
- Profile and travel preferences (airports, airlines, cabin, seat, meal, frequent-flyer
  programmes). Frequent-flyer numbers are only ever returned masked (`****5566`).
- Audit log table recording sign-ups, sign-ins (success and failure), profile and
  preference changes, password changes. No secrets or PII in audit details.
- Structured logging (JSON in production) with a request ID and user ID on every line;
  `X-Request-ID` returned on every response; security headers.
- Errors always `{"error": {"code", "message"}}`; validation errors name the field but
  never echo the submitted value; no stack traces.
- `GET /health` (liveness), `GET /ready` (database + pgvector + config), OpenAPI at
  `/docs` and `/redoc`.
- Alembic migrations (the first one enables the `vector` extension on PostgreSQL).
- `python -m app.cli create-admin <email>` / `promote <email>`.

**Frontend (`frontend/`)**
- Sign-in and sign-up pages, signed-in shell with sidebar (desktop) and drawer (mobile),
  Home (account set-up checklist), Profile, Travel preferences and Settings (change
  password, theme, sign out everywhere). Light and dark themes.
- React Hook Form + Zod validation on every form; server field errors shown inline.
- `proxy.ts` redirects signed-out visitors to sign-in (authorization itself is always
  enforced by the backend).

**Already partly covering later phases:** auth rate limiting (in-memory, per process;
Redis comes in phase 9), audit logging, request IDs, CI (`.github/workflows/platform-ci.yml`:
lint, type check, tests on SQLite *and* PostgreSQL+pgvector, production build, Docker builds).

## Running it

### With Docker (recommended)

```bash
cp backend/.env.example backend/.env    # then set JWT_SECRET
docker compose -f docker-compose.platform.yml up -d --build
```

Frontend on http://localhost:3000, API docs on http://localhost:8000/docs. The backend
container runs `alembic upgrade head` on start.

Create an administrator:

```bash
docker compose -f docker-compose.platform.yml exec backend python -m app.cli create-admin admin@example.com
```

### Without Docker

Backend (Python 3.12):

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env     # point DATABASE_URL at PostgreSQL, or use the SQLite line for a quick start
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Frontend (Node 24):

```bash
cd frontend
npm install
cp .env.example .env.local     # BACKEND_URL, if the API isn't on 127.0.0.1:8000
npm run dev
```

### Checks

```bash
cd backend && ruff check . && mypy app && pytest -q
cd frontend && npm run lint && npm run typecheck && npm run build
```

Backend tests use a temporary SQLite database built by the real migrations. Set
`TEST_DATABASE_URL=postgresql+asyncpg://...` to run them against PostgreSQL (CI does both).

## API (phase 1)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/register` | – | Create account and sign in |
| POST | `/api/auth/login` | – | Sign in |
| POST | `/api/auth/logout` | – | Clear the session cookies |
| POST | `/api/auth/logout-all` | user | Revoke every token for this account |
| GET | `/api/users/me` | user | Current user, profile, preferences |
| PATCH | `/api/users/me/profile` | user | Update profile fields |
| PUT | `/api/users/me/preferences` | user | Replace travel preferences |
| POST | `/api/users/me/password` | user | Change password (signs out other devices) |
| GET | `/health`, `/api/health` | – | Liveness |
| GET | `/ready` | – | Readiness (database, pgvector, configuration) |

## Known limitations (phase 1)

- Rate limits are per process. With several workers or instances the effective limit is
  multiplied until the Redis-backed limiter lands in phase 9.
- There is no email verification or password reset yet (needs the notification service).
- Docker images and the PostgreSQL path are exercised in CI, not on this development
  machine (it has no Docker); local verification used SQLite.
