import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    allowedHosts: ['host.docker.internal'],
    proxy: {
      '/api/': {
        target: 'http://127.0.0.1:8912',
        changeOrigin: true,
      },
      '/media': {
        target: 'http://127.0.0.1:8912',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8912',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
