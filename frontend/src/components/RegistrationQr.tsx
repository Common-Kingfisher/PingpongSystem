/**
 * Public 报名二维码组件（D 轨 Day5D）。
 *
 * ## 职责（刻意很窄）
 *
 * “组织者展示二维码 → 现场手机扫码打开 Public 报名页”。因此这里只做三件事：
 *
 * 1. 用 `publicUrls.buildPublicRegistrationUrl()` 拿到**当前访问 origin** 下的报名地址；
 * 2. 渲染二维码（`qrcode.react` 的 SVG 版本，随页面缩放、不依赖 canvas）；
 * 3. 同屏给出**文本地址 + 复制链接**（只有二维码对口头沟通 / 打印有损的场景不友好）。
 *
 * ## 明确不做
 *
 * - 不做扫码器 / 摄像头权限 / 二维码识别 / 短链服务；
 * - 不新建页面、不做 PWA；
 * - 不硬编码回环地址 / 现场网段 IP / 端口 / 公网域名（统一由 `publicUrls.ts` 从
 *   `window.location.origin` 派生，换部署环境不改业务代码）。
 *
 * ## 可复用性
 *
 * 本组件不依赖 PublicLayout、不读路由，只吃一个 `tournamentId`，因此后续 C5 若要把它
 * 放到管理端「赛事设置 / 赛事总览」，直接 `import` 即可，无需 D 轨改动。
 */

import { useCallback, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
import { buildPublicRegistrationUrl } from '../publicUrls'
import './RegistrationQr.css'

type CopyState = 'idle' | 'copied' | 'failed'

export interface RegistrationQrProps {
  /** 赛事 id（来自 URL path param，不由本组件推断） */
  tournamentId: number
}

export default function RegistrationQr({ tournamentId }: RegistrationQrProps) {
  const url = buildPublicRegistrationUrl(tournamentId)
  const [copyState, setCopyState] = useState<CopyState>('idle')

  const copyLink = useCallback(async () => {
    try {
      // 局域网 HTTP 访问不是 secure context，`navigator.clipboard` 可能不存在；
      // 这里必须显式判空并降级为「手动复制」提示，而不是让页面崩掉 / 白屏。
      if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
        throw new Error('clipboard-unavailable')
      }
      await navigator.clipboard.writeText(url)
      setCopyState('copied')
    } catch {
      setCopyState('failed')
    }
  }, [url])

  return (
    <section className="reg-qr" aria-label="报名二维码">
      <div className="reg-qr-frame">
        <QRCodeSVG
          level="M"
          marginSize={2}
          size={148}
          title={`报名二维码：${url}`}
          value={url}
        />
      </div>
      <div className="reg-qr-meta">
        <p className="reg-qr-label">报名地址</p>
        {/* 文本地址与二维码同源：同一个 url 变量，不存在两套地址 */}
        <code className="reg-qr-url">{url}</code>
        <button className="reg-qr-copy" onClick={copyLink} type="button">
          复制链接
        </button>
        <p className="reg-qr-hint" role="status">
          {copyState === 'copied' && '已复制报名链接'}
          {copyState === 'failed' && '复制失败，请长按上方地址手动复制'}
          {copyState === 'idle' && '手机扫码即可打开报名页面'}
        </p>
      </div>
    </section>
  )
}
