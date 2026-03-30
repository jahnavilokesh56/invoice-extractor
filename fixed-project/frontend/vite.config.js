import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/extract': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/extract-multiple': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/export-csv': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    }
  }
})
