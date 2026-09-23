import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type Match, type ScorePayload } from '../api'
import ScoreSheet from '../components/ScoreSheet'
import { consoleErrorFeedback } from '../pages/ConsolePage'

const finishedMatch: Match = {
  id: 88,
  tournament_id: 12,
  stage: 'GROUP',
  group_id: 3,
  round: 1,
  match_index: null,
  player_a_id: 10,
  player_b_id: 11,
  player_a_score: 2,
  player_b_score: 1,
  winner_id: 10,
  table_id: 2,
  status: 'FINISHED',
  prev_match_a_id: null,
  prev_match_b_id: null,
  entry_a_id: 10,
  entry_b_id: 11,
  entry_a_name: '甲方',
  entry_b_name: '乙方',
  result_type: 'NORMAL',
  result_note: null,
  bracket: 'MAIN',
  games: [],
}

beforeEach(() => localStorage.clear())
afterEach(cleanup)

describe('桌面端比分修改保护', () => {
  it('修改已结束比赛时先显示风险确认，再提交修改', async () => {
    const onSave = vi.fn(async (_payload: ScorePayload) => undefined)
    render(<ScoreSheet
      match={finishedMatch}
      sideA="甲方"
      sideB="乙方"
      gamesToWin={3}
      pointsToWin={11}
      busy={false}
      auditMode="revise"
      onClose={() => undefined}
      onSave={onSave}
    />)

    fireEvent.change(screen.getByLabelText('甲方大比分'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('操作人'), { target: { value: '主裁王老师' } })
    fireEvent.change(screen.getByLabelText('修改理由'), { target: { value: '现场复核记录有误' } })
    fireEvent.click(screen.getByRole('button', { name: '检查并修改' }))

    expect(onSave).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog', { name: '确认修改已结束比赛' })).toBeTruthy()
    expect(screen.getByText(/当前记录为 甲方 2 : 1 乙方/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '确认并保存修改' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1))
    expect(onSave.mock.calls[0][0]).toMatchObject({
      player_a_score: 3,
      player_b_score: 1,
      operator_name: '主裁王老师',
      change_reason: '现场复核记录有误',
    })
  })

  it('提交失败提示出现后保留裁判已经填写的内容', () => {
    const onSave = vi.fn(async (_payload: ScorePayload) => undefined)
    const view = render(<ScoreSheet
      match={{ ...finishedMatch, status: 'PLAYING', player_a_score: null, player_b_score: null }}
      sideA="甲方"
      sideB="乙方"
      gamesToWin={2}
      pointsToWin={11}
      busy={false}
      onClose={() => undefined}
      onSave={onSave}
    />)

    fireEvent.change(screen.getByLabelText('甲方大比分'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('乙方大比分'), { target: { value: '0' } })
    fireEvent.change(screen.getByLabelText('操作人'), { target: { value: '李裁判' } })

    view.rerender(<ScoreSheet
      match={{ ...finishedMatch, status: 'PLAYING', player_a_score: null, player_b_score: null }}
      sideA="甲方"
      sideB="乙方"
      gamesToWin={2}
      pointsToWin={11}
      busy={false}
      submitError={{ title: '提交内容未通过校验', message: '比分与比赛规则不一致' }}
      onClose={() => undefined}
      onSave={onSave}
    />)

    expect(screen.getByRole('alert').textContent).toContain('已填写内容仍保留')
    expect((screen.getByLabelText('甲方大比分') as HTMLInputElement).value).toBe('2')
    expect((screen.getByLabelText('乙方大比分') as HTMLInputElement).value).toBe('0')
    expect((screen.getByLabelText('操作人') as HTMLInputElement).value).toBe('李裁判')
  })
})

describe('控制台错误分层', () => {
  it.each([
    [409, '比赛状态已变化', 'warning'],
    [422, '提交内容未通过校验', 'warning'],
    [403, '当前账号不能执行此操作', 'danger'],
    [503, '服务暂时不可用', 'danger'],
  ] as const)('HTTP %i 使用对应的现场提示层', (status, title, tone) => {
    expect(consoleErrorFeedback(new ApiError(status, '服务端原始文案'))).toEqual({
      title,
      tone,
      message: '服务端原始文案',
    })
  })
})
