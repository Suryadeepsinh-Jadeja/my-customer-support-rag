// Starts the API for the end-to-end tests: a fresh database, the knowledge base loaded,
// the rule-based fake LLM and the mock booking provider, so runs are deterministic and
// never call Gemini or Duffel (whatever backend/.env contains).
//
// E2E_PYTHON        python with the backend installed (default: backend/.venv, else python)
// E2E_DATABASE_URL  database to use (default: a fresh SQLite file); CI passes PostgreSQL
// E2E_API_PORT      default 8200

import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const backend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../backend");
const venv = path.join(backend, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.E2E_PYTHON || (existsSync(venv) ? venv : "python");
const work = mkdtempSync(path.join(tmpdir(), "travel-e2e-"));
const port = process.env.E2E_API_PORT || "8200";

const env = {
  ...process.env,
  APP_ENV: "test",
  DATABASE_URL:
    process.env.E2E_DATABASE_URL ||
    `sqlite+aiosqlite:///${path.join(work, "e2e.db").replaceAll("\\", "/")}`,
  JWT_SECRET: "e2e-secret-" + "x".repeat(40),
  STORAGE_BACKEND: "local",
  STORAGE_LOCAL_PATH: path.join(work, "storage"),
  STORAGE_ENCRYPTION_KEY: "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
  LLM_PROVIDER: "fake",
  GEMINI_API_KEY: "",
  FLIGHT_PROVIDER: "mock",
  DUFFEL_API_KEY: "",
  REDIS_URL: "",
  DOCUMENT_AI_PROVIDER: "rules",
  OCR_PROVIDER: "none",
  MALWARE_SCANNER: "none",
  WORKER_MODE: "inline",
  AUTH_RATE_LIMIT_PER_MINUTE: "1000",
  UPLOAD_RATE_LIMIT_PER_HOUR: "1000",
  CORS_ORIGINS: "http://localhost:3100,http://127.0.0.1:3100",
  FRONTEND_URL: "http://localhost:3100",
  LOG_LEVEL: "WARNING",
};

function run(args) {
  const result = spawnSync(python, args, { cwd: backend, env, stdio: "inherit" });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

run(["-m", "alembic", "upgrade", "head"]);
run(["-m", "app.rag.ingest", "../knowledge_base"]);

const server = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port],
  { cwd: backend, env, stdio: "inherit" },
);
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.kill(signal));
server.on("exit", (code) => process.exit(code ?? 0));
