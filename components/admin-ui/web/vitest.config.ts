import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  root: new URL('../../..', import.meta.url).pathname,
  plugins: [react()],
  resolve: { alias: {
    '@': new URL('./src', import.meta.url).pathname,
    '@testing-library/react': new URL('./node_modules/@testing-library/react', import.meta.url).pathname,
    '@testing-library/user-event': new URL('./node_modules/@testing-library/user-event', import.meta.url).pathname,
    'react': new URL('./node_modules/react', import.meta.url).pathname,
  } },
  test: {
    include: ['tests/unit/ui/**/*.test.tsx'],
    environment: 'jsdom',
    setupFiles: ['tests/unit/ui/setup.ts'],
  },
})
