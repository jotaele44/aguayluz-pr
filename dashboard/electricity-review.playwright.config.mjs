import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

const frontend = path.dirname(fileURLToPath(import.meta.url))
const repository = path.dirname(frontend)
export default defineConfig({
  testDir: './tests', testMatch: 'electricity-review.spec.mjs', workers: 1,
  fullyParallel: false, retries: 0, reporter: 'line',
  outputDir: 'test-results/electricity-review',
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [{ name: 'electricity-review-chromium', use: {
    ...devices['Desktop Chrome'],
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } } : {}),
  } }],
  webServer: [
    { command: 'python tests/fixtures/electricity_review_server.py', cwd: repository,
      env: { ...process.env, PYTHONPATH: [path.join(repository, 'src'), repository, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) },
      url: 'http://127.0.0.1:8000/health', reuseExistingServer: false, timeout: 120000 },
    { command: 'npm run dev -- --host 127.0.0.1 --port 5173 --strictPort', cwd: frontend,
      env: { ...process.env, VITE_API_BASE: 'http://127.0.0.1:8000' },
      url: 'http://127.0.0.1:5173', reuseExistingServer: false, timeout: 120000 },
  ],
})
