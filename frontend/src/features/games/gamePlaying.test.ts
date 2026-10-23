import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import App from '../../app/App.vue'
import { createServices, servicesKey } from '../../app/services'
import { createAppRouter } from '../../app/router'
import { createApiClient } from '../../shared/api/client'
import { createGameApi, gameState } from '../../../testing/gameApi'
import { FakeSocket } from '../../../testing/socket'
const wrappers: VueWrapper[] = []
beforeEach(() => {
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
})
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.useRealTimers()
})
async function page(
  options: {
    socket?: boolean
    authenticated?: boolean
    path?: string
    uid?: number
    status?: -1 | 0 | 2
  } = {},
) {
  const api = createGameApi(options.authenticated ?? true)
  api.games.set(7, gameState(7, options.status ?? 0, 0))
  if (options.uid) api.lobby.management.actor.id = options.uid
  const wire = new FakeSocket()
  wire.autoConnect = options.socket ?? false
  const writes: { path: string; body: Record<string, unknown> }[] = []
  const behavior = { fail: false, readFail: false }
  const fetcher = vi.fn<typeof fetch>(async (url, config) => {
    const path = String(url)
    if (config?.method === 'POST' && path.startsWith('/api/game/')) {
      const body = JSON.parse(String(config.body))
      writes.push({ path, body })
      if (behavior.fail) throw Error('confirmation lost')
      return Response.json({ success: true, version: 99, request_id: body.request_id })
    }
    if (path === '/api/game/7' && behavior.readFail) throw Error('read failed')
    const response = api.handle(path, config?.method ?? 'GET')
    return Response.json(response.body, { status: response.status })
  })
  const services = createServices(
    createApiClient({ fetcher, origin: 'http://localhost' }),
    wire.factory,
  )
  const router = createAppRouter(services, createMemoryHistory())
  await router.push(options.path ?? '/game/7/')
  await router.isReady()
  const wrapper = mount(App, {
    attachTo: document.body,
    global: { plugins: [router], provide: { [servicesKey as symbol]: services } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  if (options.socket) {
    wire.sent[0]?.ack({ success: true })
    await flushPromises()
  }
  return { wrapper, api, wire, writes, behavior, fetcher, services, router }
}
function button(wrapper: VueWrapper, label: string) {
  return wrapper.findAll('button').find((item) => item.text() === label)!
}
async function answer(wrapper: VueWrapper, value = ' Apple ') {
  await wrapper.get('#game-answer').setValue(value)
  await wrapper.get('section[aria-labelledby="game-turn-title"] form').trigger('submit')
  await flushPromises()
}
describe('Vue playing page', () => {
  it('shows the newest answers first without changing positional question correspondence', async () => {
    const { wrapper, api } = await page()
    api.games.set(7, { ...gameState(7, 0, 25), version: 6 })
    await button(wrapper, '刷新对局').trigger('click')
    await flushPromises()
    const history = wrapper.get('[aria-labelledby="game-answers-title"]')
    expect(history.findAll('tbody tr')).toHaveLength(20)
    expect(history.find('tbody tr td').text()).toBe('25')
    expect(history.find('tbody tr').text()).toContain('standard-24')
    expect(history.text()).not.toContain('standard-25')
    await history
      .findAll('button')
      .find((button) => button.text() === '下一页')!
      .trigger('click')
    expect(history.findAll('tbody tr')).toHaveLength(5)
    expect(history.find('tbody tr td').text()).toBe('5')
    expect(history.find('tbody tr').text()).toContain('standard-4')
  })
  it('same-user session replacement discards pending intents and the old connection', async () => {
    const { wrapper, wire, services } = await page({ socket: true })
    await answer(wrapper)
    const original = wire.sent.find((packet) => packet.event === 'game.answer')!
    const next = { ...services.client.session.value!, csrf_token: 'replacement-session' }
    vi.spyOn(services.client, 'loadSession').mockResolvedValue(next)
    services.client.acceptSession(next)
    await flushPromises()
    original.ack({ success: false, code: 'unauthenticated', message: 'old session' })
    await flushPromises()
    expect(services.client.session.value?.csrf_token).toBe('replacement-session')
    expect(wrapper.find('[aria-label="原请求确认"]').exists()).toBe(false)
    expect((wrapper.get('#game-answer').element as HTMLInputElement).value).toBe('')
    expect(wire.handshakes.at(-1)).toEqual({ csrf_token: 'replacement-session' })
  })
  it('manual Socket disable closes the channel and selects HTTP for the next intent', async () => {
    const { wrapper, wire, writes } = await page({ socket: true })
    const checkbox = wrapper.findAll('input[type="checkbox"]')[0]!
    await checkbox.setValue(false)
    await flushPromises()
    expect(wire.connected).toBe(false)
    await answer(wrapper)
    expect(writes).toHaveLength(1)
    expect(wire.sent.some((packet) => packet.event === 'game.answer')).toBe(false)
  })
  it('preserves guarded login target and avoids anonymous state/socket access', async () => {
    const { router, fetcher, wire } = await page({ authenticated: false })
    expect(router.currentRoute.value.query.next).toBe('/game/7/')
    expect(fetcher.mock.calls.every(([url]) => url === '/api/session')).toBe(true)
    expect(wire.handshakes).toHaveLength(0)
  })
  it('invalid IDs do not open sockets or send game reads', async () => {
    const { wrapper, wire, fetcher } = await page({ path: '/game/2147483648/' })
    expect(wrapper.text()).toContain('无效的对局编号')
    expect(wire.sent).toHaveLength(0)
    expect(fetcher.mock.calls.every(([url]) => url === '/api/session')).toBe(true)
  })
  it.each([-1, 2] as const)('shows status %s without answer/end controls', async (status) => {
    const { wrapper } = await page({ status })
    expect(wrapper.find('#game-answer').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('提前结束对局')
  })
  it('spectators see escaped prompts but cannot answer or end', async () => {
    const { wrapper, writes } = await page({ uid: 9 })
    expect(wrapper.get('#game-answer').element.matches(':disabled')).toBe(true)
    expect(wrapper.find('main img, main svg, main script').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('提前结束对局')
    await answer(wrapper)
    expect(writes).toHaveLength(0)
  })
  it('HTTP confirmation alone neither increments scores nor navigates, and equal reads keep the draft', async () => {
    const { wrapper, writes, router } = await page()
    expect(document.activeElement?.id).toBe('game-answer')
    await answer(wrapper)
    expect(writes[0]?.body).toMatchObject({
      word_id: 11,
      answer: ' Apple ',
      expected_version: 5,
      request_id: expect.any(String),
    })
    expect(wrapper.text()).toContain('回执已确认')
    expect(wrapper.text()).toContain('0 / 3')
    expect((wrapper.get('#game-answer').element as HTMLInputElement).value).toBe(' Apple ')
    expect(router.currentRoute.value.name).toBe('game-playing')
  })
  it('failed HTTP retries preserve the ID even after state advances; no automatic retry', async () => {
    const { wrapper, writes, behavior, api } = await page()
    behavior.fail = true
    await answer(wrapper)
    api.games.set(7, { ...gameState(7, 0, 1), version: 6 })
    await button(wrapper, '刷新对局').trigger('click')
    await flushPromises()
    expect(wrapper.get('#game-answer').element.matches(':disabled')).toBe(true)
    expect(writes).toHaveLength(1)
    behavior.fail = false
    await button(wrapper, '重试原请求').trigger('click')
    await flushPromises()
    expect(writes[1]!.body).toEqual(writes[0]!.body)
    expect((wrapper.get('#game-answer').element as HTMLInputElement).value).toBe('')
  })
  it('refresh failure after commit is displayed separately from the successful write', async () => {
    const { wrapper, behavior } = await page()
    behavior.readFail = true
    await answer(wrapper)
    expect(wrapper.text()).toContain('回执已确认')
    expect(wrapper.text()).toContain('无法读取对局')
    expect(wrapper.text()).not.toContain('原请求未确认')
  })
  it('Socket writes use acknowledgements, not duplicate notifications; lost confirmation is manually retried over HTTP', async () => {
    const { wrapper, wire, writes } = await page({ socket: true })
    await answer(wrapper)
    const packet = wire.sent.find((item) => item.event === 'game.answer')!
    expect(packet.data).toMatchObject({
      game_id: 7,
      csrf_token: expect.any(String),
      expected_version: 5,
    })
    wire.server('game.answer_result', {
      success: true,
      request_id: packet.data.request_id,
      version: 6,
    })
    wire.server('game.error', { success: false, code: 'old', message: 'old' })
    await flushPromises()
    expect(button(wrapper, '重试原请求').attributes('disabled')).toBeDefined()
    wire.disconnect()
    await flushPromises()
    expect(writes).toHaveLength(0)
    await button(wrapper, '重试原请求').trigger('click')
    await flushPromises()
    expect(writes[0]!.body).toEqual({
      word_id: 11,
      answer: ' Apple ',
      expected_version: 5,
      request_id: packet.data.request_id,
    })
    packet.ack({ success: true, request_id: packet.data.request_id, version: 6 })
    expect(writes).toHaveLength(1)
  })
  it('validates pushes and room IDs, resubscribes on reconnect and never sends writes on reconnect', async () => {
    const { wrapper, wire, api, writes } = await page({ socket: true })
    wire.server('game.update', gameState(99, 1))
    wire.server('game.update', { ...gameState(7, 0, 0), question_source: 'unknown' })
    await flushPromises()
    expect(wrapper.text()).toContain('实时状态格式异常')
    expect(wrapper.text()).toContain('0 / 3')
    const next = { ...gameState(7, 0, 1), version: 6 }
    api.games.set(7, next)
    wire.server('game.update', next)
    await flushPromises()
    expect(wrapper.text()).toContain('1 / 3')
    expect(wrapper.get('#game-answer').element.matches(':disabled')).toBe(true)
    wire.disconnect()
    wire.connect()
    await flushPromises()
    expect(wire.sent.filter((item) => item.event === 'game.subscribe')).toHaveLength(2)
    wire.sent.at(-1)!.ack({ success: true })
    await flushPromises()
    expect(wrapper.text()).toContain('实时连接已订阅')
    expect(writes).toHaveLength(0)
  })
  it('end confirmation freezes the reviewed version despite a subsequent push', async () => {
    const { wrapper, wire } = await page({ socket: true })
    await button(wrapper, '提前结束对局').trigger('click')
    wire.server('game.update', { ...gameState(7, 0, 1), version: 6 })
    await flushPromises()
    await button(wrapper, '确认结束').trigger('click')
    await flushPromises()
    const packet = wire.sent.find((item) => item.event === 'game.end')!
    expect(packet.data.expected_version).toBe(5)
    packet.ack({ success: false, code: 'stale_game_version', message: 'stale' })
    await flushPromises()
    expect(wrapper.text()).toContain('对局已变化')
    expect(wrapper.find('dialog').exists()).toBe(false)
  })
  it('accepted terminal state navigates to Vue history and disposes socket subscriptions', async () => {
    const { wire, api, router } = await page({ socket: true })
    const finished = { ...gameState(7, 1, 1), version: 6 }
    api.games.set(7, finished)
    wire.server('game.update', finished)
    await flushPromises()
    await vi.dynamicImportSettled()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('game-detail')
    expect(wire.connected).toBe(false)
    expect([...wire.listeners.values()].every((listeners) => listeners.size === 0)).toBe(true)
  })
  it('leaving cancels a pending command and late success cannot navigate back', async () => {
    const { wrapper, wire, router } = await page({ socket: true })
    await answer(wrapper)
    const packet = wire.sent.find((item) => item.event === 'game.answer')!
    await router.push('/leaderboard/')
    await flushPromises()
    packet.ack({ success: true, request_id: packet.data.request_id, version: 6 })
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('leaderboard')
    expect(wire.connected).toBe(false)
  })
  it('losing the authenticated session via socket acknowledgement returns to the guarded playing target', async () => {
    const { wrapper, wire, api, router } = await page({ socket: true })
    await answer(wrapper)
    api.lobby.state.authenticated = false
    wire.sent
      .find((item) => item.event === 'game.answer')!
      .ack({ success: false, code: 'unauthenticated', message: 'expired' })
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.next).toBe('/game/7/')
    expect(wire.connected).toBe(false)
  })
})
