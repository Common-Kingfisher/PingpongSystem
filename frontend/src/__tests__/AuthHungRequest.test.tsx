import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'

const HUNG_REQUEST_TIMEOUT_MS = 8000

function pendingFetch() {
  return vi.fn(() => new Promise<Response>(() => {}))
}

async function flushMicrotasks() {
  for (let index = 0; index < 6; index += 1) {
    await Promise.resolve()
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', pendingFetch())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('手机锁屏恢复后的悬挂鉴权请求', () => {
  it('受保护页的 /me 悬挂超时后必须离开加载态并进入登录页', async () => {
    render(
      <MemoryRouter initialEntries={['/players?tid=12']}>
        <App />
      </MemoryRouter>,
    )
    await act(async () => { await flushMicrotasks() })

    expect(screen.queryAllByRole('status').some(
      (element) => element.textContent === '正在检查登录状态…',
    )).toBe(true)

    await act(async () => {
      vi.advanceTimersByTime(HUNG_REQUEST_TIMEOUT_MS + 1)
      await flushMicrotasks()
    })

    expect(screen.getByText('管理端登录')).toBeTruthy()
    expect(screen.queryAllByRole('status').some(
      (element) => element.textContent === '正在检查登录状态…',
    )).toBe(false)
    expect(screen.getByRole('button').textContent).toBe('登录')
  })

  it('登录请求悬挂超时后必须释放按钮并显示网络错误', async () => {
    render(
      <MemoryRouter initialEntries={['/login?next=%2Fplayers%3Ftid%3D12']}>
        <App />
      </MemoryRouter>,
    )
    await act(async () => { await flushMicrotasks() })

    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'event-admin' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'original-password-123' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '登录' }))
      await flushMicrotasks()
    })

    expect(screen.getByRole('button').textContent).toBe('正在登录…')

    await act(async () => {
      vi.advanceTimersByTime(HUNG_REQUEST_TIMEOUT_MS + 1)
      await flushMicrotasks()
    })

    expect(screen.getByRole('alert').textContent).toBe('无法连接服务器，请检查服务器或本地网络')
    expect(screen.getByRole('button').textContent).toBe('登录')
  })
})
