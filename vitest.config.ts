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
      // Ratchet over the whole src tree (measured 2026-11-16 with 96 tests:
      // lines 25.2 / branches 22.2 / functions 19.6 / statements 28.7).
      // CI fails if coverage drops. Raise as suites grow.
      thresholds: { lines: 22, branches: 18, functions: 16, statements: 24 },
    },
  },
})
