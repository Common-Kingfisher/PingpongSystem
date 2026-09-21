import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// 最小前端测试配置（PR #44 review 要求为 Public 路由加回归保护）。
// 只负责 jsdom 环境；不引入 E2E 框架，也不改 build 行为（build 仍走 vite.config.ts）。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
