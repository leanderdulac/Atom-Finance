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
      // Ratchet over the whole src tree (measured 2026-11-16 with 40 tests:
      // lines 22.7 / branches 15.4 / functions 13.7 / statements 19.6).
      // CI fails if coverage drops. Raise as suites grow.
      thresholds: { lines: 18, branches: 12, functions: 11, statements: 16 },
    },
  },
})
