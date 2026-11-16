import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // NOTE: no direct vendor proxies — the browser must only reach AI
      // providers through the backend (/api/ai/*), which holds the keys.
      '/api': {
        target: process.env.ATOM_API_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
    watch: {
      ignored: ['**/backend/**', '**/node_modules/**', '**/venv/**', '**/.venv/**', '**/venv_test/**', '**/venv_test2/**'],
    },
  },
})
