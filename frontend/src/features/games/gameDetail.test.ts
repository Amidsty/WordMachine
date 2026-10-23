import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import App from '../../app/App.vue'
import { createServices, servicesKey } from '../../app/services'
import { createAppRouter } from '../../app/router'
import { createApiClient } from '../../shared/api/client'
import { createGameApi, gameState } from '../../../testing/gameApi'

const wrappers: VueWrapper[] = []
beforeEach(() => {
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
})
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.useRealTimers()
})
async function page(
  path = '/game/4/detail/',
  authenticated = true,
  setup?: (api: ReturnType<typeof createGameApi>) => void,
) {
  const api = createGameApi(authenticated)
  setup?.(api)
  const fetcher = vi.fn<typeof fetch>(async (url, options) => {
    const result = api.handle(String(url), options?.method || 'GET')
    return Response.json(result.body, { status: result.status })
  })
  const services = createServices(createApiClient({ fetcher, origin: 'http://localhost' }))
  const router = createAppRouter(services, createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(App, {
    attachTo: document.body,
    global: { plugins: [router], provide: { [servicesKey as symbol]: services } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, services, router, api, fetcher }
}
function button(wrapper: VueWrapper, label: string) {
  return wrapper.findAll('button').find((node) => node.text() === label)!
}
function scores(wrapper: VueWrapper) {
  return wrapper.get('section[aria-labelledby="game-scores-title"]')
}
function answers(wrapper: VueWrapper) {
  return wrapper.get('section[aria-labelledby="game-answers-title"]')
}

describe('Vue game history', () => {
  it('preserves the guarded deep link and never fetches private records anonymously', async () => {
    const { router, fetcher } = await page('/game/4/detail/', false)
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.next).toBe('/game/4/detail/')
    expect(fetcher.mock.calls.every(([url]) => url === '/api/session')).toBe(true)
  })
  it('rejects out-of-range IDs without sending an API game request', async () => {
    const { wrapper, fetcher } = await page('/game/2147483648/detail/')
    expect(wrapper.text()).toContain('无效的对局编号')
    expect(fetcher.mock.calls.every(([url]) => url === '/api/session')).toBe(true)
  })
  it('renders rounded Perf, unchanged per-game ratings and escaped text without future English', async () => {
    const { wrapper, fetcher } = await page()
    expect(wrapper.get('h1').text()).toBe('对局详情 #4')
    expect(wrapper.text()).toContain('创建时快照')
    expect(wrapper.find('main img, main script, main svg, [onclick]').exists()).toBe(false)
    expect(wrapper.text()).toContain('<svg onload=alert(1)>旧词典')
    expect(wrapper.text()).toContain('<script>x</script>')
    expect(wrapper.text()).not.toContain('standard-2')
    const rows = scores(wrapper).findAll('tbody tr')
    expect(rows[0]!.findAll('td')[2]!.text()).toBe('1511.1')
    expect(wrapper.text()).not.toContain('1511.1234567890124')
    expect(answers(wrapper).findAll('tbody tr')[0]!.findAll('td')[6]!.text()).toBe('1511.1 / +11.1')
    expect(rows[0]!.text()).toContain('+7')
    expect(rows[0]!.text()).toContain('1507')
    expect(rows[0]!.text()).not.toContain('1707')
    expect(
      rows[1]!
        .findAll('td')
        .slice(-3)
        .map((cell) => cell.text()),
    ).toEqual(['0.0', '0', '0'])
    expect(rows[2]!.findAll('td')[2]!.text()).toBe('无答题记录')
    expect(rows[2]!.text()).toContain('无本局评分记录')
    expect(answers(wrapper).findAll('tbody tr')).toHaveLength(2)
    expect(fetcher.mock.calls.every(([, options]) => options?.method === 'GET')).toBe(true)
  })
  it('shows the frozen multiplier while legacy games do not claim a snapshot', async () => {
    const old = await page()
    expect(old.wrapper.text()).toContain('旧规则（无倍率快照）')
    const { wrapper } = await page('/game/4/detail/', true, (api) => {
      Object.assign(api.games.get(4)!, {
        perf_rule_version: 'dict-perf-v1',
        multiplier_snapshot: '1.25',
      })
    })
    expect(wrapper.text()).toContain('×1.25（创建时固定）')
  })

  it('marks incomplete legacy results and missing users instead of guessing values', async () => {
    const { wrapper } = await page('/game/4/detail/', true, (api) => {
      const game = gameState(4, 1, 3)
      game.question_source = 'legacy_live'
      game.dictname = null
      game.users = game.users.filter((user) => user.id !== 2)
      game.result[2] = { uid: 1 }
      api.games.set(4, game)
    })
    expect(wrapper.text()).toContain('可能与原题不同')
    const first = scores(wrapper).findAll('tbody tr')[0]!
    expect(first.text()).toContain('1 / 0 / 1')
    expect(first.text()).toContain('记录缺失')
    expect(first.text()).not.toContain('1511')
    expect(scores(wrapper).text()).toContain('用户 #2（资料缺失）')
    expect(wrapper.get('section[aria-labelledby="game-overview-title"]').text()).toContain('3 人')
    const last = answers(wrapper).findAll('tbody tr')[2]!
    expect(last.text()).toContain('题目引用缺失或不一致')
    expect(last.text()).toContain('未记录')
    expect(last.text()).not.toContain('standard-2')
  })
  it.each([
    [5, '已取消'],
    [6, '待开始'],
    [7, '进行中'],
  ] as const)('shows state #%s without inventing a settlement', async (id, label) => {
    const { wrapper } = await page(`/game/${id}/detail/`)
    expect(wrapper.text()).toContain(label)
    expect(scores(wrapper).text()).toContain(id === 5 ? '未结算' : '尚未结算')
    expect(wrapper.find('a[href="/game/7/"]').exists()).toBe(id === 7)
    if (id !== 7) expect(answers(wrapper).text()).toContain('暂无答题记录')
  })
  it.each([
    [404, 'not_found'],
    [503, 'database_unavailable'],
    [409, 'invalid_game_answers'],
  ] as const)(
    'clears stale data on %s and recovers through read-only retry',
    async (status, code) => {
      const { wrapper, api, fetcher } = await page()
      api.state.failure = { status, code }
      await button(wrapper, '刷新详情').trigger('click')
      await flushPromises()
      expect(wrapper.find('[role="alert"]').exists()).toBe(true)
      expect(wrapper.find('table').exists()).toBe(false)
      api.state.failure = null
      await button(wrapper, '刷新详情').trigger('click')
      await flushPromises()
      expect(answers(wrapper).findAll('tbody tr')).toHaveLength(2)
      expect(fetcher.mock.calls.every(([, options]) => options?.method === 'GET')).toBe(true)
    },
  )
  it('keeps local history page and visible rows through a slow refresh without another fetch for paging', async () => {
    const { wrapper, fetcher } = await page('/game/4/detail/', true, (api) => {
      api.games.set(4, gameState(4, 1, 25))
    })
    await button(wrapper, '下一页').trigger('click')
    expect(answers(wrapper).findAll('tbody tr')).toHaveLength(5)
    expect(fetcher.mock.calls.filter(([url]) => url === '/api/game/4')).toHaveLength(1)
    let finish!: (response: Response) => void
    fetcher.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    await button(wrapper, '刷新详情').trigger('click')
    await flushPromises()
    expect(answers(wrapper).findAll('tbody tr')).toHaveLength(5)
    finish(Response.json({ success: true, game: { ...gameState(4, 1, 26), version: 6 } }))
    await flushPromises()
    expect(answers(wrapper).text()).toContain('第 2 / 2 页')
    expect(answers(wrapper).findAll('tbody tr')).toHaveLength(6)
  })
  it('does not let a late response for a previous route overwrite the new game', async () => {
    const { wrapper, router, fetcher } = await page()
    let finish!: (response: Response) => void
    let signal: AbortSignal | null | undefined
    fetcher.mockImplementationOnce((_url, options) => {
      signal = options?.signal
      return new Promise((resolve) => {
        finish = resolve
      })
    })
    await button(wrapper, '刷新详情').trigger('click')
    await flushPromises()
    await router.push('/game/5/detail/')
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    finish(Response.json({ success: true, game: gameState(4) }))
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('对局详情 #5')
  })
  it('aborts old-account reads on identity change and ignores their late responses', async () => {
    const { wrapper, services, api, fetcher } = await page()
    let finish!: (response: Response) => void
    let signal: AbortSignal | null | undefined
    fetcher.mockImplementationOnce((_url, options) => {
      signal = options?.signal
      return new Promise((resolve) => {
        finish = resolve
      })
    })
    await button(wrapper, '刷新详情').trigger('click')
    await flushPromises()
    const session = services.client.session.value!
    if (!session.authenticated) throw new Error('Expected authenticated fixture')
    api.games.get(4)!.dictname = 'fresh account read'
    services.client.acceptSession({ ...session, user: { ...session.user!, id: 2 } })
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    finish(Response.json({ success: true, game: gameState() }))
    await flushPromises()
    expect(wrapper.text()).toContain('fresh account read')
    expect(wrapper.text()).not.toContain('<svg onload=alert(1)>旧词典')
  })
  it('redirects an expired session with the detail target and discards private state', async () => {
    const { wrapper, api, router } = await page()
    api.lobby.state.authenticated = false
    await button(wrapper, '刷新详情').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.next).toBe('/game/4/detail/')
    expect(wrapper.find('table').exists()).toBe(false)
  })
  it('polls only reads, pauses manually/offline/hidden, and cleans up on leaving', async () => {
    vi.useFakeTimers()
    const { wrapper, fetcher, router } = await page()
    const reads = () => fetcher.mock.calls.filter(([url]) => url === '/api/game/4').length
    await vi.advanceTimersByTimeAsync(5000)
    expect(reads()).toBe(2)
    await wrapper.get('input[type="checkbox"]').setValue(false)
    await vi.advanceTimersByTimeAsync(15000)
    expect(reads()).toBe(2)
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await flushPromises()
    expect(reads()).toBe(3)
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(15000)
    expect(reads()).toBe(3)
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(reads()).toBe(4)
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    window.dispatchEvent(new Event('offline'))
    await vi.advanceTimersByTimeAsync(15000)
    expect(reads()).toBe(4)
    await router.push('/leaderboard/')
    await flushPromises()
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
    window.dispatchEvent(new Event('online'))
    await vi.advanceTimersByTimeAsync(15000)
    expect(reads()).toBe(4)
  })
})
