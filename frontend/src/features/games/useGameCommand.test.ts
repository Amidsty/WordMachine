import { effectScope } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { useGameCommand } from './useGameCommand'
import { newIntent, commandPayload, type GameIntent } from './commands'
import { createGameService } from './service'
import { createApiClient, ApiError } from '../../shared/api/client'
import { createGameApi } from '../../../testing/gameApi'
const input = {
  gameId: 7,
  actorId: 1,
  action: 'answer' as const,
  word_id: 11,
  answer: ' Apple ',
  expected_version: 5,
}
afterEach(() => vi.useRealTimers())
function setup(
  send = vi
    .fn<(intent: GameIntent, signal: AbortSignal) => Promise<unknown>>()
    .mockResolvedValue({}),
  refresh = vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
) {
  const scope = effectScope()
  const command = scope.run(() => useGameCommand(send, refresh))!
  return { command, send, refresh, stop: () => scope.stop() }
}
describe('frozen game intents', () => {
  it('retains exact parameters and UUID for a manual retry, blocks other commands, and never replays automatically', async () => {
    const { command, send, refresh, stop } = setup()
    send.mockRejectedValueOnce(new Error('lost confirmation'))
    await command.submit(input)
    const intent = command.intent.value!
    expect(Object.isFrozen(intent)).toBe(true)
    expect(intent).toMatchObject({ answer: input.answer })
    expect(command.error.value).toContain('未自动重发')
    expect(refresh).toHaveBeenCalledTimes(1)
    await command.submit({ gameId: 7, actorId: 1, action: 'end', expected_version: 9 })
    expect(send).toHaveBeenCalledTimes(1)
    await command.retry()
    expect(send.mock.calls[1]![0]).toBe(intent)
    expect(command.intent.value).toBe(null)
    stop()
  })
  it('dismissal is not rollback; a new explicit intent has a new UUID', async () => {
    const { command, send, stop } = setup()
    send.mockRejectedValue(new Error('offline'))
    await command.submit(input)
    const original = command.intent.value!.request_id
    command.dismiss()
    expect(command.notice.value).toContain('不代表撤销或回滚')
    await command.submit({ ...input, answer: 'other', expected_version: 6 })
    expect(command.intent.value!.request_id).not.toBe(original)
    expect(command.intent.value!.expected_version).toBe(6)
    stop()
  })
  it('a confirmed commit remains successful when the refresh fails', async () => {
    const { command, refresh, stop } = setup()
    refresh.mockRejectedValueOnce(new Error('read failed'))
    await command.submit(input)
    expect(command.error.value).toBe('')
    expect(command.notice.value).toContain('回执已确认')
    expect(command.intent.value).toBe(null)
    stop()
  })
  it('blocks duplicate submissions and dismissal until confirmation/reconciliation finishes', async () => {
    let done!: () => void
    const { command, send, stop } = setup()
    send.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          done = () => resolve({})
        }),
    )
    const running = command.submit(input)
    await command.submit(input)
    command.dismiss()
    expect(send).toHaveBeenCalledTimes(1)
    expect(command.intent.value).not.toBe(null)
    done()
    await running
    expect(command.pending.value).toBe(false)
    stop()
  })
  it('aborts a timed-out HTTP attempt without retry and preserves its original intent', async () => {
    vi.useFakeTimers()
    const { command, send, stop } = setup()
    send.mockImplementationOnce(
      (_intent, signal) =>
        new Promise((_resolve, reject) =>
          signal.addEventListener('abort', () => reject(Error('aborted'))),
        ),
    )
    const running = command.submit(input)
    await vi.advanceTimersByTimeAsync(10000)
    await running
    expect(command.pending.value).toBe(false)
    expect(command.intent.value).not.toBe(null)
    expect(send).toHaveBeenCalledTimes(1)
    stop()
    expect(vi.getTimerCount()).toBe(0)
  })
  it('aborts on identity/page disposal and ignores late success without refreshing or navigating', async () => {
    let done!: () => void
    const { command, send, refresh, stop } = setup()
    send.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          done = () => resolve({})
        }),
    )
    const running = command.submit(input)
    stop()
    expect(send.mock.calls[0]![1].aborted).toBe(true)
    done()
    await running
    expect(command.notice.value).toBe('')
    expect(refresh).not.toHaveBeenCalled()
  })
  it('invalid intent fails before transport', async () => {
    const { command, send, stop } = setup()
    await command.submit({ ...input, word_id: 0 })
    expect(send).not.toHaveBeenCalled()
    expect(command.error.value).toContain('未提交')
    stop()
  })
  it('HTTP uses the same frozen payload and binds the success ID and session actor', async () => {
    const api = createGameApi()
    const fetcher = vi.fn<typeof fetch>(async (url, options) => {
      if (String(url) === '/api/session') return Response.json(api.handle(String(url)).body)
      const body = JSON.parse(String(options?.body))
      return Response.json({ success: true, request_id: body.request_id, version: 6 })
    })
    const client = createApiClient({ fetcher, origin: 'http://localhost' })
    const games = createGameService(client)
    const intent = newIntent(input)
    await games.command(intent)
    expect(fetcher.mock.calls[1]![0]).toBe('/api/game/7/answer')
    expect(JSON.parse(String(fetcher.mock.calls[1]![1]!.body))).toEqual(commandPayload(intent))
    await expect(games.command({ ...intent, actorId: 123 })).rejects.toBeInstanceOf(ApiError)
    expect(fetcher).toHaveBeenCalledTimes(2)
    fetcher.mockResolvedValueOnce(
      Response.json({ success: true, version: 7, request_id: 'different' }),
    )
    await expect(games.command(intent)).rejects.toMatchObject({ code: 'invalid_response' })
    await flushPromises()
  })
})
