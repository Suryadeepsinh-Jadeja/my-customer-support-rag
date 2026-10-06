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

> The repository also still contains the previous support assistant
> (`customer_support_chat/`, Streamlit). It's documented in
> [docs/LEGACY_SUPPORT_ASSISTANT.md](docs/LEGACY_SUPPORT_ASSISTANT.md) and will be removed.
> Everything below is about the new platform in `backend/` and `frontend/`.

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
| Google Gemini API key | Recommended | [Google AI Studio](https://aistudio.google.com/apikey) → *Create API key*. Without it the app still runs, but documents are read by simpler built-in rules, search is keyword-only and the chat assistant replies that it isn't available. |
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

This starts PostgreSQL (with pgvector), MinIO (file storage), the backend, a background
worker and the frontend.

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
   docker compose -f docker-compose.platform.yml up -d --build
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

1. Register, then fill in **Profile** (name, home airport, phone) and **Travel
   preferences**.
2. Upload a passport, a flight ticket and a hotel booking under **Documents** and wait until
   each shows *Ready for AI*.
3. Ask the assistant (`POST /api/chat`, or the chat page once phase 8 lands):
   - "What is my flight number?" / "What time do I arrive?" / "What is my baggage
     allowance?"
   - "Are my documents in order for my trip?"
   - "Book my flight to London for October 20", then pick an option and press **Confirm**
     (`POST /api/chat/confirm`).
   - "Cancel my flight" and confirm.

   Until the chat UI exists, use the interactive API docs at http://localhost:8000/docs:
   sign in with `POST /api/auth/login`, then call `POST /api/chat`.

Bookings made with the mock provider (or a Duffel test key) are test bookings: nothing is
ticketed or charged.

## 6. Create an administrator

```bash
cd backend
python -m app.cli create-admin admin@example.com     # prompts for a password (10+ characters)
python -m app.cli promote someone@example.com        # make an existing user an admin
```

With Docker:
`docker compose -f docker-compose.platform.yml exec backend python -m app.cli create-admin admin@example.com`

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

## 8. Configuration reference

`backend/.env.example` lists every backend setting with comments. The ones you're most
likely to change:

| Setting | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | local PostgreSQL | `postgresql+asyncpg://...` or `sqlite+aiosqlite:///./dev.db` |
| `JWT_SECRET` | none | Signs sign-in tokens. Required in production (32+ characters) |
| `STORAGE_ENCRYPTION_KEY` | none | Encrypts uploaded files. Required in production; keep a backup |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | none / `gemini-3.5-flash` | AI document analysis, embeddings and the assistant |
| `FLIGHT_PROVIDER` / `DUFFEL_API_KEY` | `mock` / none | `duffel` + a test key for Duffel's sandbox |
| `STORAGE_BACKEND` | `local` | `s3` for any S3-compatible store (set the `OBJECT_STORAGE_*` values) |
| `WORKER_MODE` | `inline` | `external` to process documents with `python -m app.worker` |
| `MALWARE_SCANNER` | `none` | `clamav` to scan uploads with ClamAV |

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| Chat answers "The assistant isn't available right now" | `GEMINI_API_KEY` is missing from `backend/.env`; add it and restart the API. |
| Chat answers "The assistant is busy right now" | Gemini's rate limit; wait a minute, or use `GEMINI_MODEL=gemini-3.5-flash-lite`. |
| Policy answers find nothing | The knowledge base wasn't loaded: run `python -m app.rag.ingest ../knowledge_base` in `backend/`. |
| `no such table` errors | Run `alembic upgrade head` in `backend/` (and check `DATABASE_URL` points at the same file). |
| Frontend shows network errors | Check the API is running and `BACKEND_URL` in `frontend/.env.local` matches its port. |
| Port 8000 already in use | Start the API with `--port 8100` and set `BACKEND_URL=http://127.0.0.1:8100`. |
| Flight booking fails: "needs each traveller's date of birth and gender" | You're using Duffel: upload the traveller's passport, and add a phone number to your profile. |
| Uploaded files can't be opened after changing settings | `STORAGE_ENCRYPTION_KEY` changed; restore the original key. |

## 10. Project layout

```text
backend/            FastAPI app (app/), migrations (alembic/), tests (tests/)
  app/agents/       assistant: supervisor, specialist prompts, tools, document checks
  app/providers/    booking providers: mock, Duffel
  app/rag/          chunking, hybrid retrieval, knowledge-base ingestion
  app/services/     auth, documents, chat, bookings, payments, LLM
frontend/           Next.js app
knowledge_base/     travel-policy Markdown loaded into the assistant's search
docs/               implementation plan, legacy app documentation
docker-compose.platform.yml   the full stack in Docker
```
