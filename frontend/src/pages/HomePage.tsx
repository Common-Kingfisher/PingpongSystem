import { useEffect, useState } from 'react'
import { api } from '../api'

export default function HomePage() {
  const [backendStatus, setBackendStatus] = useState<'checking' | 'ok' | 'error'>('checking')

  useEffect(() => {
    api
      .health()
      .then(() => setBackendStatus('ok'))
      .catch(() => setBackendStatus('error'))
  }, [])

  return (
    <div className="page-placeholder">
      <h2>赛事首页</h2>
      <p>
        后端连接状态：
        {backendStatus === 'checking' && '检测中…'}
        {backendStatus === 'ok' && <span className="status-ok">正常 ✅</span>}
        {backendStatus === 'error' && <span className="status-error">失败 ❌（请确认后端已启动）</span>}
      </p>
      <p style={{ color: '#9aa5b1' }}>赛事创建与进度展示将在任务 7 实现。</p>
    </div>
  )
}
