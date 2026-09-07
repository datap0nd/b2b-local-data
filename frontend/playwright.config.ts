import {defineConfig, devices} from '@playwright/test';

// End-to-end smoke tests against a running app (default: the local server with fictional data, `python run.py`).
// Set B2B_E2E_URL to point at another instance. These tests never call the model: they use the sample previews.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  // A portable backend has one query lane. Parallel browser samples would correctly receive 429.
  workers: 1,
  reporter: [['list']],
  use: {baseURL: process.env.B2B_E2E_URL ?? 'http://127.0.0.1:8765', trace: 'retain-on-failure', ...devices['Desktop Chrome']},
  projects: [
    {name: 'desktop', use: {viewport: {width: 1440, height: 900}}},
    {name: 'phone', use: {...devices['Pixel 7']}},
  ],
});
