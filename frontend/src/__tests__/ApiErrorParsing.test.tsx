/**
 * 共享 transport 层错误解析测试（`frontend/src/api.ts::request()`）。
 *
 * ## 背景
 *
 * A 轨认证契约（`docs/openapi-v0.2.json` 的 `ApiErrorResponse`）把错误体从
 * 「字符串 detail」扩展成两种形态：
 *
 * ```jsonc
 * { "detail": "逐局小比分与大比分不一致" }                    // V0.2 旧式业务错误
 * { "detail": { "code": "AUTH_REQUIRED", "message": "请先登录" } }  // A 轨结构化错误
 * ```
 *
 * 旧解析只认字符串 detail，因此 401 之类结构化错误在页面上退化成
 * 「请求失败 (401)」，裁判看不到真实原因。
 *
 * ## 为什么测这一层
 *
 * 解析必须**只做一次**、放在 transport 层，所有页面复用；
 * 任何页面自己解析 response 都等于复制 transport contract。
 * 因此这里直接对 `api.*` 调用断言 `ApiError`，不经过页面。
 */

/// <reference types="vitest/globals" />
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '../api'

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stubResponse(response: Response) {
  vi.stubGlobal('fetch', () => Promise.resolve(response))
}

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('transport 层错误解析：兼容字符串 detail 与结构化 detail', () => {
  it('字符串 detail（旧式业务错误）→ message=detail，code 为 undefined', async () => {
    stubResponse(jsonResponse({ detail: '逐局小比分与大比分不一致' }, 422))

    const error = await api.getTournament(1).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.status).toBe(422)
    expect(apiError.message).toBe('逐局小比分与大比分不一致')
    expect(apiError.code).toBeUndefined()
  })

  it('结构化 detail（AUTH_REQUIRED）→ message 取 message，code 取 code', async () => {
    stubResponse(jsonResponse({ detail: { code: 'AUTH_REQUIRED', message: '请先登录' } }, 401))

    const error = (await api.getTournament(1).catch((e: unknown) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(401)
    expect(error.message).toBe('请先登录')
    expect(error.code).toBe('AUTH_REQUIRED')
  })

  it('结构化 detail（RESOURCE_NOT_FOUND）→ 保留“资源不存在”语义', async () => {
    stubResponse(jsonResponse({ detail: { code: 'RESOURCE_NOT_FOUND', message: '资源不存在' } }, 404))

    const error = (await api.getTournament(1).catch((e: unknown) => e)) as ApiError
    expect(error.status).toBe(404)
    expect(error.message).toBe('资源不存在')
    expect(error.code).toBe('RESOURCE_NOT_FOUND')
  })

  it('结构化 detail（FORBIDDEN）→ 保留 code', async () => {
    stubResponse(jsonResponse({ detail: { code: 'FORBIDDEN', message: '需要系统管理员权限' } }, 403))

    const error = (await api.getTournament(1).catch((e: unknown) => e)) as ApiError
    expect(error.status).toBe(403)
    expect(error.message).toBe('需要系统管理员权限')
    expect(error.code).toBe('FORBIDDEN')
  })

  it('非 JSON 错误体 → 退回“请求失败 (status)”且不抛解析异常', async () => {
    stubResponse(new Response('<html>boom</html>', { status: 502, headers: { 'Content-Type': 'text/html' } }))

    const error = (await api.getTournament(1).catch((e: unknown) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(502)
    expect(error.message).toBe('请求失败 (502)')
    expect(error.code).toBeUndefined()
  })

  it('结构化 detail 缺少 message 时退回默认文案，但 code 仍然保留', async () => {
    stubResponse(jsonResponse({ detail: { code: 'AUTH_REQUIRED' } }, 401))

    const error = (await api.getTournament(1).catch((e: unknown) => e)) as ApiError
    expect(error.message).toBe('请求失败 (401)')
    expect(error.code).toBe('AUTH_REQUIRED')
  })
})
