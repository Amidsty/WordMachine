import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createApiClient } from './client'
import { createSocketService } from './socket'
import { successSchema, type Session } from './contracts'
import { gameCommandSchema } from './gameCommand'
import { FakeSocket } from '../../../testing/socket'

const session: Session = {
  success: true,
  authenticated: true,
  csrf_token: 'csrf-1',
  user: { id: 1, username: 'first', type: 'normal', rating: 1500, introduction: '' },
}
const id = '11111111-1111-4111-8111-111111111111'
afterEach(() => vi.useRealTimers())
async function setup() {
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => Response.json(session))
  const client = createApiClient({ fetcher, origin: 'http://localhost' })
  client.acceptSession(session)
  const wire = new FakeSocket()
  const update = vi.fn(),
    connected = vi.fn()
  const channel = createSocketService(client, wire.factory).open(1, update, connected)
  channel.connect()
  await flushPromises()
  return { client, fetcher, wire, channel, update, connected }
}
describe('private same-origin socket channel', () => {
  it('a busy handshake does not drop the read subscription, but writes remain volatile', async () => {
    vi.useFakeTimers()
    const { wire, channel } = await setup()
    wire.writable = false
    const subscription = channel.request('game.subscribe', { game_id: 7 }, successSchema)
    expect(wire.sent[0]!.volatile).toBe(false)
    wire.sent[0]!.ack({ success: true })
    await subscription
    const command = channel.request('game.end', {}, successSchema)
    const rejected = expect(command).rejects.toMatchObject({ code: 'socket_unconfirmed' })
    await vi.advanceTimersByTimeAsync(10000)
    await rejected
    expect(wire.sent).toHaveLength(1)
    channel.close()
  })
  it('revalidates session on each handshake, separates updates from acknowledgements and cleans listeners', async () => {
    const { wire, channel, update, fetcher, connected } = await setup()
    expect(wire.handshakes).toEqual([{ csrf_token: 'csrf-1' }])
    wire.server('game.update', { id: 4 })
    expect(update).toHaveBeenCalledExactlyOnceWith({ id: 4 })
    wire.server('game.error', { success: false, code: 'old', message: 'old' })
    wire.server('game.answer_result', { success: true })
    wire.disconnect()
    channel.connect()
    await flushPromises()
    expect(connected).toHaveBeenCalledTimes(2)
    expect(fetcher).toHaveBeenCalledTimes(2)
    channel.close()
    expect(channel.online.value).toBe(false)
    expect([...wire.listeners.values()].every((listeners) => listeners.size === 0)).toBe(true)
    wire.server('game.update', { id: 5 })
    expect(update).toHaveBeenCalledTimes(1)
  })
  it('uses csrf and validates the per-emission request ID without consuming unsolicited receipts', async () => {
    const { wire, channel } = await setup()
    const promise = channel.request(
      'game.answer',
      { request_id: id, csrf_token: 'forged' },
      gameCommandSchema(id),
    )
    expect(wire.sent[0]!.data.csrf_token).toBe('csrf-1')
    wire.server('game.answer_result', { success: true, request_id: id, version: 9 })
    wire.sent[0]!.ack({ success: true, request_id: 'wrong', version: 9 })
    await expect(promise).rejects.toMatchObject({ code: 'invalid_response' })
    channel.close()
  })
  it('does not buffer disconnected sends or resend after reconnect', async () => {
    const { wire, channel } = await setup()
    wire.disconnect()
    await expect(channel.request('game.end', {}, successSchema)).rejects.toMatchObject({
      code: 'socket_unconfirmed',
    })
    channel.connect()
    await flushPromises()
    expect(wire.sent).toHaveLength(0)
    channel.close()
  })
  it('times out once without retrying and ignores late acknowledgements', async () => {
    vi.useFakeTimers()
    const { wire, channel } = await setup()
    const promise = channel.request('game.answer', {}, successSchema)
    const rejected = expect(promise).rejects.toMatchObject({ code: 'socket_unconfirmed' })
    await vi.advanceTimersByTimeAsync(10000)
    await rejected
    wire.sent[0]!.ack({ success: true })
    await vi.advanceTimersByTimeAsync(30000)
    expect(wire.sent).toHaveLength(1)
    channel.close()
    expect(vi.getTimerCount()).toBe(0)
  })
  it.each(['disconnect', 'abort', 'close'] as const)(
    'settles an in-flight request on %s without treating it as rolled back',
    async (action) => {
      const { wire, channel } = await setup()
      const controller = new AbortController()
      const promise = channel.request('game.end', {}, successSchema, controller.signal)
      const rejection = expect(promise).rejects.toMatchObject({
        name: action === 'abort' ? 'AbortError' : 'ApiError',
      })
      if (action === 'disconnect') wire.disconnect()
      if (action === 'abort') controller.abort()
      if (action === 'close') channel.close()
      await rejection
      wire.sent[0]!.ack({ success: true })
      channel.close()
    },
  )
  it('rejects actor changes before sending and ignores old-session authentication failures', async () => {
    const { client, wire, channel } = await setup()
    const promise = channel.request('game.end', {}, successSchema)
    client.acceptSession({ ...session, csrf_token: 'different-session' })
    wire.sent[0]!.ack({ success: false, code: 'unauthenticated', message: 'expired' })
    await expect(promise).rejects.toMatchObject({ code: 'unauthenticated' })
    expect(client.session.value?.authenticated).toBe(true)
    client.acceptSession(null)
    await expect(channel.request('game.end', {}, successSchema)).rejects.toMatchObject({
      code: 'session_changed',
    })
    expect(wire.sent).toHaveLength(1)
    channel.close()
  })
  it.each(['unauthenticated', 'csrf_failed'])(
    'handles %s through shared session state without replay',
    async (code) => {
      const { client, fetcher, wire, channel } = await setup()
      fetcher.mockResolvedValue(Response.json({ ...session, csrf_token: 'new-csrf' }))
      const promise = channel.request('game.end', {}, successSchema)
      wire.sent[0]!.ack({ success: false, code, message: code })
      await expect(promise).rejects.toMatchObject({ code })
      if (code === 'unauthenticated') expect(client.session.value).toBe(null)
      else expect(client.session.value?.csrf_token).toBe('new-csrf')
      expect(wire.sent).toHaveLength(1)
      channel.close()
    },
  )
  it('does not finish a handshake after the page was closed', async () => {
    let finish!: (response: Response) => void
    const client = createApiClient({
      origin: 'http://localhost',
      fetcher: () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    })
    const wire = new FakeSocket()
    const channel = createSocketService(client, wire.factory).open(1, vi.fn(), vi.fn())
    channel.connect()
    channel.close()
    finish(Response.json(session))
    await flushPromises()
    expect(wire.handshakes).toHaveLength(0)
  })
})
