import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ command }) => {
  const target = process.env.WM_API_PROXY || 'http://127.0.0.1:5000'
  // Preserve the browser's Host and Origin so Flask can enforce SAME origin.
  const proxy = { target, changeOrigin: false }
  return {
    plugins: [vue()],
    base: command === 'build' ? '/ui/' : '/',
    server: {
      host: '127.0.0.1',
      strictPort: true,
      proxy: {
        '/api': proxy,
        '/health': proxy,
        '/socket.io': { ...proxy, ws: true },
      },
    },
    build: { outDir: 'dist', assetsDir: 'assets', sourcemap: false },
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.ts'],
      restoreMocks: true,
      clearMocks: true,
    },
  }
})
