/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 产物吐给现有 ThreadingHTTPServer（ata/http.py 静态分支）：
// outDir 指到 ../web/dist，install-service.sh 与服务端代码零改动。
// dev 时 API 走本机常驻服务，前端改动热更新不碰 Python。
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../web/dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:17877',
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: './src/test/setup.ts',
  },
})
