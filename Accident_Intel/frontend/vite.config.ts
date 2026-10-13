import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Allow any host: covers localhost, container hosts and hosted preview
    // domains (e.g. *.e2b.app). Without this the dev server answers 403 for
    // proxied preview URLs.
    allowedHosts: true,
    proxy: {
      // Browser-facing code uses relative /api URLs, so the same build works
      // on localhost and behind any preview/proxy host.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
