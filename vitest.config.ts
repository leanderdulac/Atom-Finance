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
      // Ratchet over the whole src tree (measured 2026-11-16 with 100 tests:
      // lines 26.3 / branches 22.8 / functions 20.4 / statements 29.9).
      // CI fails if coverage drops. Raise as suites grow.
      thresholds: { lines: 24, branches: 20, functions: 18, statements: 26 },
    },
  },
})
