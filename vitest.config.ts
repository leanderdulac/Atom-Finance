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
      // Ratchet over the whole src tree (measured 2026-11-16 with 90 tests:
      // lines 24.1 / branches 20.1 / functions 18.1 / statements 27.5).
      // CI fails if coverage drops. Raise as suites grow.
      thresholds: { lines: 20, branches: 16, functions: 14, statements: 22 },
    },
  },
})
