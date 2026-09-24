/**
 * Public 报名的静态契约回归（D 轨 Day5D）。
 *
 * 这里测的不是“页面长什么样”，而是两条**以后很容易被改回去**的硬约束：
 *
 * 1. **legacy 报名路径不得复活**：`RegisterPage` / `PublicRoutes` 不得再调用
 *    `api.addPlayer()`（V0.2 语义：公开报名直接创建正式 Player）；
 * 2. **报名地址不得硬编码**：二维码与文本地址只能由 `window.location.origin` 派生，
 *    不允许出现 `localhost` / `127.0.0.1` / 固定局域网 IP / 固定端口 / 固定公网域名，
 *    否则换部署环境（局域网 → 公网域名）就必须改业务代码。
 *
 * 源码通过 Vite 的 `?raw` / `import.meta.glob` 读取（不引入 `node:fs`，
 * 因此不需要 `@types/node`，也不会影响 `tsc` 与 `vite build`）。
 */

/// <reference types="vitest/globals" />
import { describe, expect, it } from 'vitest'
import { buildPublicRegistrationUrl, publicRegistrationPath } from '../publicUrls'
import registerPageSource from '../pages/RegisterPage.tsx?raw'
import publicRoutesSource from '../PublicRoutes.tsx?raw'
import registrationQrSource from '../components/RegistrationQr.tsx?raw'
import publicUrlsSource from '../publicUrls.ts?raw'

/**
 * 去掉注释后再做文本断言。
 *
 * 这些文件里大量注释**故意**举例说明了被禁止的写法（`localhost`、`http://192.168.…`），
 * 直接扫原始文本会把“文档”误判成“实现”。
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
}

/** 所有非测试源码（key 形如 `../pages/RegisterPage.tsx`） */
const rawSources = import.meta.glob('../**/*.{ts,tsx}', {
  eager: true,
  import: 'default',
  query: '?raw',
}) as Record<string, unknown>

describe('legacy 报名路径不得复活（场景 8）', () => {
  it('RegisterPage 不再调用 api.addPlayer', () => {
    expect(stripComments(registerPageSource)).not.toMatch(/addPlayer/)
  })

  it('PublicRoutes 的报名 adapter 不再引用 addPlayer', () => {
    expect(stripComments(publicRoutesSource)).not.toMatch(/addPlayer/)
  })

  it('RegisterPage 改为消费正式 Registration 契约', () => {
    const code = stripComments(registerPageSource)
    expect(code).toMatch(/api\.submitRegistration/)
    // 报名开闭只读后端 registration_enabled，不自己发明第二套判断
    expect(code).toMatch(/registration_enabled/)
  })

  it('全仓（除 api.ts 定义与管理端手工添加选手外）不得使用 addPlayer', () => {
    const allowed = new Set(['../api.ts', '../pages/PlayersPage.tsx'])
    const users: string[] = []
    for (const [file, content] of Object.entries(rawSources)) {
      // 排除测试自身与 generated 契约快照（它们本来就会提到 addPlayer / 其它关键字）
      if (file.includes('__tests__') || /\.test\.tsx?$/.test(file) || file.includes('/generated/')) continue
      if (/addPlayer/.test(stripComments(String(content)))) users.push(file)
    }
    expect(users.sort()).toEqual([...allowed].sort())
  })
})

describe('报名地址只能由当前访问 origin 派生（场景 7）', () => {
  it('Public 报名路径是 /public/t/:tid/register', () => {
    expect(publicRegistrationPath(12)).toBe('/public/t/12/register')
  })

  it('同一份代码在局域网与公网域名下产出各自的地址', () => {
    expect(buildPublicRegistrationUrl(12, 'http://192.168.50.10:8000')).toBe(
      'http://192.168.50.10:8000/public/t/12/register',
    )
    expect(buildPublicRegistrationUrl(12, 'https://example.com')).toBe(
      'https://example.com/public/t/12/register',
    )
  })

  it('origin 结尾斜杠不会产生双斜杠', () => {
    expect(buildPublicRegistrationUrl(12, 'https://example.com/')).toBe(
      'https://example.com/public/t/12/register',
    )
  })

  it('未显式传入 origin 时使用当前浏览器的 window.location.origin', () => {
    expect(buildPublicRegistrationUrl(12)).toBe(`${window.location.origin}/public/t/12/register`)
  })

  it('构造地址的源码里没有回环 / RFC1918 硬编码地址', () => {
    // 口径与 backend/tests/test_deployment_address_policy.py 一致：扫**原始文本**（含注释），
    // 这样“把现场地址写进注释当文档”也不会被放行。
    const deploymentHost =
      /localhost|127\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}/i
    for (const [name, source] of [
      ['publicUrls.ts', publicUrlsSource],
      ['RegistrationQr.tsx', registrationQrSource],
      ['RegisterPage.tsx', registerPageSource],
    ] as const) {
      expect(source, `${name} 出现硬编码部署地址`).not.toMatch(deploymentHost)
    }
  })

  it('地址构造模块里没有任何绝对 URL 字面量', () => {
    expect(publicUrlsSource).not.toMatch(/https?:\/\//i)
  })

  it('地址由 window.location.origin 派生，而不是任何常量', () => {
    expect(stripComments(publicUrlsSource)).toMatch(/window\.location/)
  })
})
