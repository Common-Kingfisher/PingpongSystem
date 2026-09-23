/**
 * Public 端 URL 的唯一构造点（D 轨 Day5D）。
 *
 * ## 为什么必须有这个文件
 *
 * 报名二维码 / “报名地址”文本链接必须是**当前访问地址**下的绝对 URL：
 *
 * ```text
 * <现场 origin>/public/t/12/register     ← 局域网现场（协议 + 主机 + 端口来自浏览器）
 * <正式域名>/public/t/12/register         ← 未来公网部署
 * ```
 *
 * 这两者必须是**同一份业务代码**产出的结果，只因为访问 origin 不同而不同。
 * 因此这里禁止任何形式的地址硬编码：
 *
 * - ❌ 回环地址（本机主机名 / 本机回环 IP）
 * - ❌ 固定局域网 IP（现场网段）
 * - ❌ 固定端口（把端口号写进前端字符串）
 * - ❌ 固定公网域名
 *
 * origin 只来自浏览器当前的 `window.location.origin`（Vite dev 的代理、FastAPI
 * 单服务静态托管、未来的反向代理 / 域名都自动适配），因此换部署环境**不需要改业务代码**。
 * 这条约束与 `backend/tests/test_deployment_address_policy.py` 的部署地址策略同源。
 *
 * ## 边界
 *
 * 本模块只回答“Public 页面地址长什么样”，不做任何跳转、不做可达性探测、不读
 * `localStorage`、不读 `?tid=`。赛事 id 一律由调用方从 URL path param 传入。
 */

/** Public 报名页的**相对**路径（同源导航用）。 */
export function publicRegistrationPath(tournamentId: number): string {
  return `/public/t/${tournamentId}/register`
}

/**
 * 当前页面的 origin（协议 + 主机 + 端口）。
 *
 * 取不到时返回空串：此时调用方会退化为同源相对地址，而不是拼出 `undefined/...`。
 */
export function currentOrigin(): string {
  if (typeof window === 'undefined') return ''
  const origin = window.location?.origin
  return typeof origin === 'string' ? origin : ''
}

/**
 * Public 报名页的绝对地址（二维码 / 文本链接唯一来源）。
 *
 * @param tournamentId 赛事 id（来自 URL path param）
 * @param origin 访问 origin；默认取 `window.location.origin`（测试可显式注入）
 */
export function buildPublicRegistrationUrl(tournamentId: number, origin: string = currentOrigin()): string {
  // 去掉可能的结尾斜杠，避免出现 `origin//public/...`
  return `${origin.replace(/\/+$/, '')}${publicRegistrationPath(tournamentId)}`
}
