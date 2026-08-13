import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // Docker 容器内通过 VITE_PROXY_TARGET=http://host.docker.internal:8010 指向宿主 API
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8010',
        changeOrigin: true,
      }
    }
  }
})
