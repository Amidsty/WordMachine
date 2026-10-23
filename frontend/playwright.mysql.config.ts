import { defineConfig } from '@playwright/test'

// Only the Python disposable-database harness should invoke this configuration.
const origin = process.env.WM_BROWSER_MYSQL_ORIGIN
if (!origin || !/^http:\/\/127\.0\.0\.1:[1-9][0-9]*$/.test(origin))
  throw new Error('Run make test-browser-mysql; an isolated loopback server is required')
export default defineConfig({
  testDir: './mysql-e2e',
  workers: 1,
  retries: 0,
  timeout: 90000,
  expect: { timeout: 10000 },
  use: {
    baseURL: origin,
    actionTimeout: 15000,
    navigationTimeout: 15000,
    trace: 'retain-on-failure',
    launchOptions: { executablePath: process.env.WM_BROWSER_EXECUTABLE || undefined },
  },
  outputDir: 'test-results/mysql',
})
