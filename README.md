# AI Travel Platform

An AI travel assistant: upload your travel documents (passport, tickets, hotel bookings),
ask questions about them and about the company's travel policies, and search, book, change
or cancel flights, hotels, cars and excursions in chat. Every booking action needs your
explicit confirmation.

- **Backend:** FastAPI, SQLAlchemy 2 (async), Alembic, PostgreSQL + pgvector (SQLite works
  for local development), Google Gemini for document analysis, embeddings and the assistant.
- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind, shadcn/ui.
- **Bookings:** a built-in mock provider (test bookings), or [Duffel](https://duffel.com)'s
  sandbox for real airline data.

What each phase delivers, the full API list and known limitations are in
[PLATFORM.md](PLATFORM.md). The build plan is in
[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

Everything lives in `backend/` and `frontend/`. The earlier LangGraph + Streamlit support
assistant it replaced has been removed.

---

## 1. What you need

| Tool | Version | Needed for |
|---|---|---|
| Git | any | cloning the repository |
| Python | 3.12 | the backend |
| Node.js | 24 (npm included) | the frontend |
| Docker Desktop | recent | only for the Docker setup (option A) |

Accounts and keys (all free for development):

| Key | Required? | Where to get it |
|---|---|---|
| Google Gemini API key | Recommended | [Google AI Studio](https://aistudio.google.com/apikey) → *Create API key*. Without it the app still runs, but documents are read by simpler built-in rules, search is keyword-only and the chat assistant replies that it isn't available. To try the whole app without a key, set `LLM_PROVIDER=fake` in `backend/.env`: a scripted test assistant that only understands the demo questions in section 5. |
| Duffel test key | Optional | Sign up at [duffel.com](https://duffel.com), then Dashboard → **More** → **Developers** → **Access tokens** → *Create access token* in **test** mode. It starts with `duffel_test_`. Without it, flights use the built-in mock. |

Never commit keys. `backend/.env` and `frontend/.env.local` are git-ignored; the
`.env.example` files are templates and must stay without real values.

## 2. Get the code

```bash
git clone https://github.com/Suryadeepsinh-Jadeja/my-customer-support-rag.git
cd my-customer-support-rag
git checkout rebuild
```

## 3. Option A: run everything with Docker

This starts PostgreSQL (with pgvector), MinIO (file storage), Redis (shared rate limits),
the backend, a background worker and the frontend.

1. Create the backend settings file:

   ```bash
   cp backend/.env.example backend/.env
   ```

2. Open `backend/.env` and set:
   - `JWT_SECRET`: generate one with
     `python -c "import secrets; print(secrets.token_urlsafe(48))"`
   - `STORAGE_ENCRYPTION_KEY`: generate one with
     `python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"`.
     Back it up: without it, uploaded files can't be decrypted.
   - `GEMINI_API_KEY`: your Gemini key (recommended).

3. Start it:

   ```bash
   docker compose up -d --build
   ```

   The backend applies the database migrations and loads the knowledge base on start-up.

4. Open http://localhost:3000 and create an account. API docs are at
   http://localhost:8000/docs, and the MinIO console at http://localhost:9001.

To also run the ClamAV virus scanner, set `MALWARE_SCANNER=clamav` in `backend/.env` and
add `--profile scan` to the `docker compose` command.

## 4. Option B: run without Docker (SQLite)

Use this when Docker isn't available. It uses SQLite and stores encrypted files on disk.
Run the backend and frontend in two separate terminals.

### 4.1 Backend

All commands are run inside `backend/`.

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment:

| Shell | Command |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows Git Bash | `source .venv/Scripts/activate` |
| macOS / Linux | `source .venv/bin/activate` |

Then install and configure:

```bash
pip install -e ".[dev]"
cp .env.example .env
```

Edit `backend/.env`. These are the only lines you need to change; everything else has
working defaults:

```text
APP_ENV=development
DATABASE_URL=sqlite+aiosqlite:///./dev.db
JWT_SECRET=<generate: python -c "import secrets; print(secrets.token_urlsafe(48))">
STORAGE_ENCRYPTION_KEY=<generate: python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())">
GEMINI_API_KEY=<your Gemini key>
```

- `./dev.db` is relative to the folder you start the backend from. Always start it from
  `backend/`, or use an absolute path such as
  `sqlite+aiosqlite:///C:/path/to/repo/backend/dev.db`.
- The default `GEMINI_MODEL` is `gemini-3.5-flash`. If your key's free tier rate-limits
  quickly, `GEMINI_MODEL=gemini-3.5-flash-lite` is lighter.
- Optional, for flights through Duffel's sandbox instead of the mock:

  ```text
  FLIGHT_PROVIDER=duffel
  DUFFEL_API_KEY=duffel_test_...
  ```

  Real (sandbox) flight orders need the traveller's passport uploaded (for date of birth
  and gender) and a phone number in your profile in international format, e.g.
  `+44 20 8016 0508`.

Create the database and load the travel-policy knowledge base:

```bash
alembic upgrade head
python -m app.rag.ingest ../knowledge_base
```

Run the ingest command again whenever `knowledge_base/` changes; unchanged files are
skipped. If you add a Gemini key later, run it once more to add the embeddings.

**Embedding quota.** Search embeddings use `gemini-embedding-2`, hard-coded as
`EMBEDDING_MODEL` in `backend/app/services/llm_service.py`. That model embeds **one text per
request** and ignores batching, so embedding costs one request per chunk — a five-page
document is roughly fifty requests. The free tier allows 1000 requests per day, per project,
**per model**, so hitting the limit on one embedding model does not affect the other, and the
chat model is unaffected. While the embedding quota is spent, search falls back to
keyword-only BM25 for anything embedded afterwards; if a *document* cannot be embedded its
upload fails with `indexing_failed` and can be retried with **Try again**. Changing the model
means clearing the existing vectors first, because vectors from two models are not comparable:

```bash
# in backend/, after editing EMBEDDING_MODEL
.venv/bin/python -c "import sqlite3; c=sqlite3.connect('dev.db'); c.execute('update knowledge_chunks set embedding=null'); c.commit()"
python -m app.rag.ingest ../knowledge_base
```

Start the API:

```bash
uvicorn app.main:app --reload --port 8000
```

Check http://localhost:8000/health (should say ok) and http://localhost:8000/docs.

Optional: OCR for scanned PDFs and photos uses [Tesseract](https://github.com/tesseract-ocr/tesseract)
if it's installed, otherwise Gemini vision.

### 4.2 Frontend

In a second terminal, from the repository root:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

`frontend/.env.local` has one setting, `BACKEND_URL`, which defaults to
`http://127.0.0.1:8000`. Change it if your API runs on another port (for example 8100 when
port 8000 is already taken).

Open http://localhost:3000 and create an account.

## 5. Try it

1. Register, then fill in **Profile** (name as on your passport, home airport, phone) and
   **Travel preferences**. The chat page shows a banner until these are done.
2. Upload a passport, a flight ticket and a hotel booking under **Documents** (or with the
   paperclip in the chat) and wait until each shows *Ready for AI*.
3. On the chat page (the home page), ask:
   - "What is my flight number?" / "What time do I arrive?" / "What is my baggage
     allowance?" Answers show source chips such as "Based on your ticket.pdf, p.1".
   - "Are my documents in order for my trip?"
   - "Book my flight to London for October 20". Pick an option with **Select**, then
     press **Review & confirm** and **Confirm** on the confirmation card.
   - "Cancel my flight", then confirm the same way.
4. Open **Bookings** to see upcoming, completed and cancelled bookings. A booking's page
   lets you change its dates or cancel it, always with a confirmation step first.

Every action is also available in the API docs at http://localhost:8000/docs.

Bookings made with the mock provider (or a Duffel test key) are test bookings: nothing is
ticketed or charged. Mock prices are invented and quoted in **USD**, whatever the route; a
Duffel booking instead uses the amount and currency the airline returns. The cancellation
fees in `knowledge_base/` are still written in CHF, so the assistant may quote a policy fee in
a different currency from the booking it applies to.

## 6. Create an administrator

```bash
cd backend
python -m app.cli create-admin admin@example.com     # prompts for a password (10+ characters)
python -m app.cli promote someone@example.com        # make an existing user an admin
```

With Docker:
`docker compose exec backend python -m app.cli create-admin admin@example.com`

Sign in as that user and open **Admin** in the sidebar. It shows system health, users,
document processing, bookings, assistant tool usage and recent errors, but never document
contents or unmasked identifiers.

Users can delete their own account under **Settings → Delete account**. They need their
password and must cancel upcoming bookings first. Their files and data are removed; the
audit log is kept with the user reference cleared.

## 7. Run the checks

```bash
cd backend
ruff check . && mypy app && pytest -q

cd ../frontend
npm run lint && npm run typecheck && npm run build
```

- Backend tests use a temporary SQLite database built by the real migrations, a scripted
  fake LLM and the mock booking provider. They never call Gemini or Duffel, whatever
  `backend/.env` says.
- To run them against PostgreSQL, set
  `TEST_DATABASE_URL=postgresql+asyncpg://...` (CI does both).
- Coverage report: `pytest --cov --cov-report=term` (about 83% of `app/`).

### End-to-end test (browser)

`frontend/e2e/demo.spec.ts` runs the whole demo in a real browser: register, upload a
passport, ticket and hotel booking, ask the three questions, book a flight, confirm,
cancel and confirm. It starts its own API on port 8200 (fresh SQLite database, a
rule-based fake LLM, the mock provider; nothing calls Gemini or Duffel) and a production
build of the frontend on port 3100. It needs the backend installed in `backend/.venv` (or
set `E2E_PYTHON` to a Python that has it).

```bash
cd frontend
npm run test:e2e
```

Locally it drives **Microsoft Edge**, so no browser download is needed. Use
`E2E_CHANNEL=chrome npm run test:e2e` for Google Chrome. Playwright's own browsers are only
needed in CI (`npx playwright install --only-shell chromium`, about 100 MB).

### Continuous integration

`.github/workflows/platform-ci.yml` runs on pushes to `main` and `rebuild` and on pull
requests:
- backend lint, type check, and tests on SQLite (with a coverage report) and on
  PostgreSQL + pgvector;
- frontend lint, type check and build;
- the browser E2E demo against PostgreSQL;
- Docker image builds.

## 8. Configuration reference

`backend/.env.example` lists every backend setting with comments. The ones you're most
likely to change:

| Setting | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | local PostgreSQL | `postgresql+asyncpg://...` or `sqlite+aiosqlite:///./dev.db` |
| `JWT_SECRET` | none | Signs sign-in tokens. Required in production (32+ characters) |
| `STORAGE_ENCRYPTION_KEY` | none | Encrypts uploaded files. Required in production; keep a backup |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | none / `gemini-3.5-flash` | AI document analysis, embeddings and the assistant. Embeddings always use `gemini-embedding-2` (a code constant, not a setting) |
| `LLM_PROVIDER` | `gemini` | `fake` = a rule-based stand-in for tests and keyless demos (refused in production) |
| `FLIGHT_PROVIDER` / `DUFFEL_API_KEY` | `mock` / none | `duffel` + a test key for Duffel's sandbox |
| `STORAGE_BACKEND` | `local` | `s3` for any S3-compatible store (set the `OBJECT_STORAGE_*` values) |
| `WORKER_MODE` | `inline` | `external` to process documents with `python -m app.worker` |
| `MALWARE_SCANNER` | `none` | `clamav` to scan uploads with ClamAV |
| `REDIS_URL` | none | e.g. `redis://localhost:6379/0` to share rate limits between API processes (Docker sets it). Without it, limits are per process |
| `CHAT_RATE_LIMIT_PER_HOUR` | `200` | Chat messages per user per hour (there's also a fixed 30 per minute) |
| `AUTH_RATE_LIMIT_PER_MINUTE` / `UPLOAD_RATE_LIMIT_PER_HOUR` | `10` / `30` | Sign-in attempts per IP, uploads per user |

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| Chat answers "The assistant isn't available right now" | `GEMINI_API_KEY` is missing from `backend/.env`; add it and restart the API. |
| Chat answers "The assistant is busy right now" | Gemini's rate limit; wait a minute, or use `GEMINI_MODEL=gemini-3.5-flash-lite`. |
| Policy answers find nothing | The knowledge base wasn't loaded: run `python -m app.rag.ingest ../knowledge_base` in `backend/`. |
| `no such table` errors | Run `alembic upgrade head` in `backend/` (and check `DATABASE_URL` points at the same file). |
| Frontend shows network errors | Check the API is running and `BACKEND_URL` in `frontend/.env.local` matches its port. |
| `429 Too many requests` | A rate limit was hit; wait for the `Retry-After` seconds, or raise the limit in `backend/.env` for local testing. |
| Port 8000 already in use | Start the API with `--port 8100` and set `BACKEND_URL=http://127.0.0.1:8100`. |
| `Another next dev server is already running` | Only one `npm run dev` can run per `frontend/` folder. Stop the other one, or use `npx next build && npx next start -p 3001` for a second copy. |
| Flight booking fails: "needs each traveller's date of birth and gender" | You're using Duffel: upload the traveller's passport, and add a phone number to your profile. |
| Uploaded files can't be opened after changing settings | `STORAGE_ENCRYPTION_KEY` changed; restore the original key. |
| Upload or ingest fails with `429 RESOURCE_EXHAUSTED` / `embedding failed: ClientError` | The **daily** embedding quota for `gemini-embedding-2` is spent (1000 requests/day, resets in hours, not minutes). Chat keeps working. Wait for the reset and press **Try again** on the document, or re-run the ingest. See *Embedding quota* in section 4.1. |
| A document stays "Failed" after the quota resets | Press **Try again** on the document page; it re-runs the pipeline with the embedding call now succeeding. |

## 10. Project layout

```text
backend/            FastAPI app (app/), migrations (alembic/), tests (tests/)
  app/agents/       assistant: supervisor, specialist prompts, tools, document checks
  app/providers/    booking providers: mock, Duffel
  app/rag/          chunking, hybrid retrieval, knowledge-base ingestion
  app/services/     auth, documents, chat, bookings, payments, LLM
frontend/           Next.js app
  e2e/              Playwright end-to-end demo test and its fixtures
knowledge_base/     travel-policy Markdown loaded into the assistant's search
docs/               implementation plan
docker-compose.yml  the full stack in Docker
```
