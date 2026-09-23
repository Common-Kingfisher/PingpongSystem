/**
 * D 轨 Day3 验收：Node 侧共享的 Chrome DevTools Protocol 客户端 + **真实登录**辅助。
 *
 * ## 为什么需要真实登录
 *
 * master@81827b3 起 `/api/matches/{id}/score` 由 `require_tournament_write` 保护，
 * 因此浏览器验收必须建立**真实会话**（`pp_session` HttpOnly Cookie），
 * 而不是关掉鉴权或往 localStorage 塞 token。
 *
 * 本模块提供的 `loginInBrowser()` 让**浏览器自己**调用
 * `POST /api/v1/auth/login {mode:"browser"}`：这样 `Set-Cookie: pp_session`
 * 由浏览器按真实规则处理（HttpOnly 对页面脚本不可见，也不会被写进 localStorage）。
 */

export const CDP_PORT = process.env.CDP_PORT ?? '9333'

export async function connectCdp(port = CDP_PORT) {
  const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()
  const ws = new WebSocket(version.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  ws.addEventListener('message', (event) => {
    const msg = JSON.parse(event.data)
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg)
      pending.delete(msg.id)
    }
  })
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve)
    ws.addEventListener('error', reject)
  })

  const browserSend = (method, params = {}) =>
    new Promise((resolve) => {
      const i = ++id
      pending.set(i, resolve)
      ws.send(JSON.stringify({ id: i, method, params }))
    })

  const target = await browserSend('Target.createTarget', { url: 'about:blank' })
  const attached = await browserSend('Target.attachToTarget', {
    targetId: target.result.targetId,
    flatten: true,
  })
  const sessionId = attached.result.sessionId

  const send = (method, params = {}) =>
    new Promise((resolve) => {
      const i = ++id
      pending.set(i, resolve)
      ws.send(JSON.stringify({ id: i, method, params, sessionId }))
    })

  const evaluate = async (expression) => {
    const out = await send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    })
    if (out.result.exceptionDetails) {
      throw new Error(
        `eval error: ${out.result.exceptionDetails.text} ${JSON.stringify(
          out.result.exceptionDetails.exception ?? {},
        )}`,
      )
    }
    return out.result.result.value
  }

  return {
    ws,
    send,
    evaluate,
    targetId: target.result.targetId,
    async close() {
      await browserSend('Target.closeTarget', { targetId: target.result.targetId }).catch(() => {})
      ws.close()
    },
  }
}

/** 打开一个空白页并启用 Page/Runtime/Network（网络缓存关闭，避免拿到旧构建产物）。 */
export async function preparePage(cdp, { width = 390, height = 844 } = {}) {
  await cdp.send('Page.enable')
  await cdp.send('Runtime.enable')
  await cdp.send('Network.enable')
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true })
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: true,
  })
}

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * 在浏览器里执行真实登录，建立 `pp_session` Cookie。
 *
 * 先导航到同源页面（这样 fetch 发往当前服务器、Cookie 属于该 origin），
 * 由**页面自己**调用登录接口 —— 与真人打开登录页的效果一致。
 *
 * ⚠️ `getCookies` 必须传入与当前页面**同一个 CDP session** 绑定的 send：
 * `Network.getCookies` 是按 session 作用域查询的，用别的 session 查会永远拿不到 Cookie
 * （实测踩过：登录成功但读回 `cookie=false`）。
 */
export async function loginInBrowser(cdp, baseUrl, username, password, options = {}) {
  const getCookies = options.getCookies
    ?? ((urls) => cdp.send('Network.getCookies', { urls }))

  await cdp.send('Page.navigate', { url: `${baseUrl}/` })
  await sleep(600)

  const result = await cdp.evaluate(`(async () => {
    const resp = await fetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ username: ${JSON.stringify(username)}, password: ${JSON.stringify(password)}, mode: 'browser' })
    })
    const body = await resp.json().catch(() => null)
    return {
      status: resp.status,
      hasAccessTokenInBody: !!(body && body.access_token),
      user: body && body.user ? body.user.username : null,
      documentCookieVisible: document.cookie,
    }
  })()`)

  const cookies = await getCookies([`${baseUrl}/`])
  // 兼容两种 CDP 客户端约定：解析成整条消息（`.result.cookies`）或直接解析成 result（`.cookies`）。
  const cookieList = cookies?.result?.cookies ?? cookies?.cookies ?? []
  const session = cookieList.find((c) => c.name === 'pp_session')

  return {
    ...result,
    sessionCookiePresent: Boolean(session),
    sessionHttpOnly: session ? session.httpOnly === true : false,
  }
}

/** 清空 Cookie（用于匿名/未登录场景）。 */
export async function clearCookies(cdp, baseUrl) {
  await cdp.send('Network.clearBrowserCookies')
  const cookies = await cdp.send('Network.getCookies', { urls: [`${baseUrl}/`] })
  return (cookies.result?.cookies ?? []).length
}
