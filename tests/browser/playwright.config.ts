import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  timeout: 30_000,
  expect: { timeout: 5_000, toHaveScreenshot: { animations: 'disabled' } },
  use: {
    baseURL: process.env.KEEPLANE_BASE_URL ?? 'http://127.0.0.1:3000',
    ...devices['Desktop Chrome'],
  },
  reporter: 'list',
})
