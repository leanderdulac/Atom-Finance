import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    css: false,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/vite-env.d.ts'],
      // Ratchet over the whole src tree (measured 2026-11-15 with 34 tests:
      // lines 15.9 / branches 11.4 / functions 11.4 / statements 18.1).
      // CI fails if coverage drops. Raise as suites grow.
      thresholds: { lines: 14, branches: 10, functions: 10, statements: 15 },
    },
  },
})
