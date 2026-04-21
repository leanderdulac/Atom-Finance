import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/perplexity-api': {
        target: 'https://api.perplexity.ai',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/perplexity-api/, ''),
      },
      '/anthropic-api': {
        target: 'https://api.anthropic.com',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/anthropic-api/, ''),
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    watch: {
      ignored: ['**/backend/**', '**/node_modules/**'],
    },
  },
})
