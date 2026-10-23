import { existsSync } from 'node:fs'
import { defineConfig } from '@playwright/test'
import { backendOrigin, backendPort, frontendOrigin, frontendPort } from './e2e/servers'

const python =
  process.env.WM_TEST_PYTHON || (existsSync('../.venv/bin/python') ? '.venv/bin/python' : 'python')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: frontendOrigin,
    trace: 'retain-on-failure',
    launchOptions: { executablePath: process.env.WM_BROWSER_EXECUTABLE || undefined },
  },
  webServer: [
    {
      command: `${python} app.py`,
      cwd: '..',
      url: `${backendOrigin}/health/live`,
      reuseExistingServer: false,
      env: {
        PYTHONDONTWRITEBYTECODE: '1',
        WM_ENV: 'development',
        WM_HOST: '127.0.0.1',
        WM_PORT: String(backendPort),
        WM_DEBUG: 'false',
        WM_SECRET_KEY: 'browser-test-only-secret',
        WM_DB_HOST: '127.0.0.1',
        WM_DB_PORT: '1',
      },
    },
    {
      command: `npm run dev -- --port ${frontendPort}`,
      url: `${frontendOrigin}/login/`,
      reuseExistingServer: false,
      env: { WM_API_PROXY: backendOrigin },
    },
  ],
})
