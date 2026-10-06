import { defineConfig, devices } from "@playwright/test";

// End-to-end tests of the §84 demo. Starts its own API (port 8200; fake LLM, mock
// provider, fresh database) and a production build of the frontend (port 3100), so it
// doesn't clash with dev servers on 8000/3000.
const API = "http://127.0.0.1:8200";
const WEB = "http://localhost:3100";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: WEB,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Locally, drive an installed browser (Edge by default) so nothing is downloaded;
        // set E2E_CHANNEL=chrome for Google Chrome. CI installs Playwright's headless shell.
        channel: process.env.CI ? undefined : (process.env.E2E_CHANNEL ?? "msedge"),
      },
    },
  ],
  webServer: [
    {
      command: "node e2e/start-backend.mjs",
      url: `${API}/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "pipe",
    },
    {
      command: "npx next build && npx next start -p 3100",
      url: `${WEB}/login`,
      timeout: 300_000,
      reuseExistingServer: false,
      env: { BACKEND_URL: API },
    },
  ],
});
