import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import App from '../../app/App.vue'
import { createServices, servicesKey } from '../../app/services'
import { createAppRouter } from '../../app/router'
import { createApiClient } from '../../shared/api/client'
import { createLobbyApi } from '../../../testing/lobbyApi'

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
afterEach(() => wrappers.splice(0).forEach((wrapper) => wrapper.unmount()))
async function page(
  path = '/',
  authenticated = true,
  setup?: (api: ReturnType<typeof createLobbyApi>) => void,
) {
  const api = createLobbyApi(authenticated)
  setup?.(api)
  const fetcher = vi.fn<typeof fetch>(async (url, options) => {
    const result = api.handle(
      String(url),
      options?.method || 'GET',
      options?.body ? JSON.parse(String(options.body)) : {},
      new Headers(options?.headers).get('X-CSRF-Token'),
    )
    return Response.json(result.body, { status: result.status })
  })
  const services = createServices(createApiClient({ fetcher, origin: 'http://localhost' }))
  const router = createAppRouter(services, createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const navigate = vi.spyOn(router, 'push').mockResolvedValue(undefined)
  const wrapper = mount(App, {
    attachTo: document.body,
    global: { plugins: [router], provide: { [servicesKey as symbol]: services } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, api, services, router, fetcher, navigate }
}
function button(wrapper: VueWrapper, name: string) {
  const result = wrapper.findAll('button').find((button) => button.text() === name)
  if (!result) throw Error('Missing button: ' + name)
  return result
}

describe('lobby', () => {
  it('requires login without fetching private game lists', async () => {
    const { router, fetcher } = await page('/', false)
    expect(router.currentRoute.value.name).toBe('login')
    expect(fetcher.mock.calls.some(([url]) => String(url).startsWith('/api/game/'))).toBe(false)
  })
  it('uses server action flags, escapes names and pages/filter on the server', async () => {
    const { wrapper, api, fetcher } = await page('/', true, (api) => {
      for (let id = 6; id <= 28; id++) api.games.push(api.game(id))
      api.games.find((game) => game.id === 2)!.actions.start = false
    })
    expect(wrapper.findAll('article')).toHaveLength(20)
    expect(wrapper.find('article img').exists()).toBe(false)
    expect(wrapper.find('[onclick]').exists()).toBe(false)
    await button(wrapper, '下一页').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('article')).toHaveLength(5)
    expect(wrapper.findAll('button').some((button) => button.text() === '开始对局')).toBe(false)
    await button(wrapper, '已结束').trigger('click')
    await flushPromises()
    expect(wrapper.find('a[href="/game/4/detail/"]').exists()).toBe(true)
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).includes('page=1&per_page=20&q=&status=finished'),
      ),
    ).toBe(true)
    expect(api.writes).toHaveLength(0)
  })
  it('joins and leaves through confirmation dialogs without sending credentials', async () => {
    const { wrapper, api } = await page()
    await button(wrapper, '报名').trigger('click')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(api.writes[0]).toEqual({
      path: '/api/game/1/join',
      body: { request_id: expect.any(String), expected_version: 0 },
    })
    expect(wrapper.find('dialog').exists()).toBe(false)
    await button(wrapper, '撤销报名').trigger('click')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(api.writes[1]?.path).toBe('/api/game/1/leave')
  })
  it('keeps API failures retryable without replaying the command', async () => {
    const { wrapper, api } = await page()
    api.state.rejectWrites = true
    await button(wrapper, '报名').trigger('click')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('dialog').text()).toContain('没有执行此操作的权限')
    expect(api.writes).toHaveLength(1)
    expect(wrapper.get('dialog fieldset').attributes('disabled')).toBeUndefined()
    const first = api.writes[0]!.body
    api.state.rejectWrites = false
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(api.writes).toHaveLength(2)
    expect(api.writes[1]!.body).toEqual(first) // Explicit retry, same intent and version.
    expect(wrapper.find('dialog').exists()).toBe(false)
  })
  it('shows stale-version conflicts without replay and uses a new intent after refresh', async () => {
    const { wrapper, api } = await page()
    await button(wrapper, '报名').trigger('click')
    api.games.find((game) => game.id === 1)!.version++
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('dialog').text()).toContain('对局已变化')
    expect(api.writes).toHaveLength(1)
    await button(wrapper, '返回').trigger('click')
    await flushPromises()
    await button(wrapper, '报名').trigger('click')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(api.writes[1]!.body.expected_version).toBe(1)
    expect(api.writes[1]!.body.request_id).not.toBe(api.writes[0]!.body.request_id)
  })
  it('closes a committed operation even when its list refresh fails', async () => {
    const { wrapper, api } = await page()
    await button(wrapper, '报名').trigger('click')
    api.state.failList = true
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('dialog').exists()).toBe(false)
    expect(wrapper.text()).toContain('报名已完成')
    expect(wrapper.text()).toContain('服务暂时不可用')
    expect(wrapper.findAll('article')).toHaveLength(0)
    expect(api.writes).toHaveLength(1)
  })
  it('creates with a paginated dictionary picker and retains selection across pages', async () => {
    const { wrapper, api } = await page('/', true, (api) => {
      for (let id = 4; id <= 25; id++) {
        api.management.dicts.push({
          id,
          dictname: 'dictionary-' + id,
          ownerid: 2,
          multiplier: '1.00',
          config_version: 0,
        })
        api.management.words.push({ id: id + 50, dictid: id, english: 'a', chinese: '字' })
      }
    })
    await button(wrapper, '创建新对局').trigger('click')
    await flushPromises()
    expect(wrapper.get('dialog').findAll('tbody tr')).toHaveLength(20)
    await wrapper.get('dialog input[type="radio"]').setValue(true)
    await wrapper
      .get('dialog')
      .findAll('button')
      .find((button) => button.text() === '下一页')!
      .trigger('click')
    await flushPromises()
    expect(wrapper.get('dialog').findAll('tbody tr')).toHaveLength(5)
    expect(wrapper.get('dialog').text()).toContain('当前选择：dictionary-25 #25')
    await wrapper.get('dialog').findAll('form')[1]!.trigger('submit')
    await flushPromises()
    expect(api.writes[0]).toEqual({
      path: '/api/game/create',
      body: { dict_id: 25, request_id: expect.any(String) },
    })
    expect(wrapper.find('dialog').exists()).toBe(false)
  })
  it('keeps a creation ID on manual retry, but replaces it for another dictionary', async () => {
    const { wrapper, api } = await page('/', true, (api) => {
      api.management.words.push({ id: 12, dictid: 3, english: 'cat', chinese: '猫' })
    })
    await button(wrapper, '创建新对局').trigger('click')
    await flushPromises()
    const choices = wrapper.findAll('dialog input[type="radio"]:not(:disabled)')
    await choices[0]!.setValue(true)
    api.state.rejectWrites = true
    const submit = () => wrapper.get('dialog').findAll('form')[1]!.trigger('submit')
    await submit()
    await flushPromises()
    await submit()
    await flushPromises()
    expect(api.writes[1]!.body).toEqual(api.writes[0]!.body)
    await choices[1]!.setValue(true)
    api.state.rejectWrites = false
    await submit()
    await flushPromises()
    expect(api.writes[2]!.body.request_id).not.toBe(api.writes[0]!.body.request_id)
    expect(api.writes[2]!.body.dict_id).not.toBe(api.writes[0]!.body.dict_id)
    expect(wrapper.find('dialog').exists()).toBe(false)
  })
  it('shows dictionary-loading errors rather than pretending the list is empty', async () => {
    const { wrapper, services } = await page()
    vi.spyOn(services.dictionaries, 'list').mockRejectedValueOnce(Error('offline'))
    await button(wrapper, '创建新对局').trigger('click')
    await flushPromises()
    expect(wrapper.get('dialog').text()).toContain('网络异常')
    await button(wrapper, '重试词典加载').trigger('click')
    await flushPromises()
    expect(wrapper.get('dialog').findAll('tbody tr')).toHaveLength(3)
  })
  it('ignores late active-game responses after switching filters, even if abort is ignored', async () => {
    const { wrapper, api, navigate, fetcher } = await page()
    let finish!: (response: Response) => void
    let signal: AbortSignal | null | undefined
    fetcher.mockImplementationOnce(async (_url, options) => {
      signal = options?.signal
      return new Promise<Response>((resolve) => {
        finish = resolve
      })
    })
    await button(wrapper, '刷新列表').trigger('click')
    await button(wrapper, '已结束').trigger('click')
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    const old = api.handle('/api/game/list?status=waiting')
    finish(Response.json({ ...old.body, active_game_id: 777 }))
    await flushPromises()
    expect(wrapper.find('a[href="/game/4/detail/"]').exists()).toBe(true)
    expect(navigate).not.toHaveBeenCalled()
  })
  it('preserves a selected dictionary after server rejection and re-enables its controls', async () => {
    const { wrapper, api } = await page()
    await button(wrapper, '创建新对局').trigger('click')
    await flushPromises()
    expect(wrapper.get('dialog').find('img').exists()).toBe(false)
    await wrapper.get('dialog input[type="radio"]:not(:disabled)').setValue(true)
    api.management.words.splice(0)
    await wrapper.get('dialog').findAll('form')[1]!.trigger('submit')
    await flushPromises()
    expect(wrapper.get('dialog').text()).toContain('词典没有可用单词')
    expect(wrapper.get('dialog fieldset').attributes('disabled')).toBeUndefined()
    expect(api.writes).toHaveLength(1)
  })
  it('resuming after a dialog waits for fresh membership instead of navigating from cached data', async () => {
    const { wrapper, api, fetcher, navigate } = await page()
    let finish!: (response: Response) => void
    fetcher.mockImplementationOnce(
      async () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    await button(wrapper, '刷新列表').trigger('click')
    await button(wrapper, '创建新对局').trigger('click')
    await flushPromises()
    finish(
      Response.json({ ...api.handle('/api/game/list?status=waiting').body, active_game_id: 777 }),
    )
    await flushPromises()
    expect(navigate).not.toHaveBeenCalled()
    await wrapper.get('dialog [aria-label="关闭对话框"]').trigger('click')
    await flushPromises()
    expect(navigate).not.toHaveBeenCalled()
  })

  it('finds joined running games outside the current page and navigates only once', async () => {
    const { navigate } = await page('/', true, (api) => {
      api.state.activeGameId = 777
    })
    expect(navigate).toHaveBeenCalledExactlyOnceWith('/game/777/')
  })
  it('starting a game navigates to the Vue playing page once', async () => {
    const { wrapper, navigate, api } = await page()
    await button(wrapper, '开始对局').trigger('click')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(api.writes[0]?.path).toBe('/api/game/2/start')
    expect(navigate).toHaveBeenCalledExactlyOnceWith('/game/2/')
  })
})

describe('public people pages', () => {
  it('supports anonymous leaderboard paging with server ranks', async () => {
    const { wrapper, router } = await page('/leaderboard/', false)
    expect(router.currentRoute.value.name).toBe('leaderboard')
    expect(wrapper.findAll('tbody tr')).toHaveLength(20)
    expect(wrapper.find('tbody img').exists()).toBe(false)
    await button(wrapper, '下一页').trigger('click')
    await flushPromises()
    expect(wrapper.find('tbody tr td').text()).toBe('21')
  })
  it('shows public profile text, preserves null ratings and does not expose edit controls', async () => {
    const { wrapper } = await page('/user/2/', false, (api) => {
      api.users[1]!.rating = null
    })
    expect(wrapper.text()).toContain('<script>first</script>')
    expect(wrapper.text()).toContain('记录缺失')
    expect(wrapper.find('main script, main img').exists()).toBe(false)
    expect(wrapper.find('main a[href="/changepw/"]').exists()).toBe(false)
  })
  it('missing profiles show API errors instead of fabricating a user', async () => {
    const { wrapper } = await page('/user/999/', false)
    expect(wrapper.text()).toContain('记录不存在或已删除')
    expect(wrapper.find('dl').exists()).toBe(false)
  })
})
