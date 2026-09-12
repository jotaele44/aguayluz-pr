import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

function findRepositoryRoot(start) {
  let current = start;
  while (current !== path.dirname(current)) {
    if (fs.existsSync(path.join(current, ".federation", "gui-capabilities.json"))) {
      return current;
    }
    current = path.dirname(current);
  }
  throw new Error("Could not locate .federation/gui-capabilities.json");
}

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = findRepositoryRoot(frontendRoot);
const frontendPort = process.env.GUI_FRONTEND_PORT || "5173";
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const backendPort = process.env.GUI_BACKEND_PORT || "8000";
const backendUrl = `http://127.0.0.1:${backendPort}`;
// Browser mutations must never write the operator's normal saved state.
// Keep the temporary SQLite file as a test artifact; it is never served by a
// normal backend startup and cannot hide review fixtures in later test runs.
const operatorStateDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "aguayluz-gui-state-"));
const seedScript = path.join(repositoryRoot, "server", "ingestion", "seed_demo.py");
const backendCommand = fs.existsSync(seedScript)
  ? `python server/ingestion/seed_demo.py && python -m uvicorn server.backend.app:app --host 127.0.0.1 --port ${backendPort}`
  : `python -m uvicorn server.backend.app:app --host 127.0.0.1 --port ${backendPort}`;

export default defineConfig({
  testDir: "./tests",
  // Removes the seeded review-queue fixture, and only ever a fixture — the
  // teardown refuses to delete anything that seed_demo.py did not create.
  globalTeardown: path.join(repositoryRoot, "server", "ingestion", "playwright.teardown.mjs"),
  testMatch: "gui-parity.spec.mjs",
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [["line"], ["html", { outputFolder: "playwright-report/gui-parity", open: "never" }]]
    : "line",
  use: {
    baseURL: frontendUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium-gui-parity",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: backendCommand,
      cwd: repositoryRoot,
      env: {
        ...process.env,
        AGUAYLUZ_OPERATOR_STATE_PATH: path.join(operatorStateDirectory, "operator.sqlite"),
        API_SECRET_KEY: "",
        ALLOWED_ORIGINS: frontendUrl,
        MONEYSWEEP_CORS_ORIGINS: frontendUrl,
        PYTHONPATH: [
          path.join(repositoryRoot, "src"),
          repositoryRoot,
          process.env.PYTHONPATH,
        ]
          .filter(Boolean)
          .join(path.delimiter),
      },
      url: `${backendUrl}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort} --strictPort`,
      cwd: frontendRoot,
      env: {
        ...process.env,
        VITE_API_BASE: backendUrl,
        VITE_FEDERATION_API_BASE_URL: `${backendUrl}/api`,
        VITE_HUB_API_BASE_URL: `${backendUrl}/api`,
        VITE_SKYWATCHER_API_BASE_URL: `${backendUrl}/api`,
      },
      url: frontendUrl,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
