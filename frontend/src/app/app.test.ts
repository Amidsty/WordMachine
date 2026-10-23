import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createApiClient } from '../shared/api/client'
import type { Session } from '../shared/api/contracts'
import App from './App.vue'
import { createServices, servicesKey } from './services'
import { createAppRouter } from './router'
import { afterLoginTarget } from './navigation'

const anonymous: Session = {
  success: true,
  authenticated: false,
  user: null,
  csrf_token: 'anonymous-token',
}
const active: Session = {
  success: true,
  authenticated: true,
  user: {
    id: 1,
    username: '<img src=x onerror=alert(1)>',
    introduction: 'old introduction',
    rating: 1500,
    type: 'normal',
  },
  csrf_token: 'session-token',
}
const wrappers: VueWrapper[] = []
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
})

async function page(path: string, initial: Session = anonymous) {
  let state = initial
  const fetcher = vi.fn<typeof fetch>(async (url, options) => {
    if (url === '/api/session') return Response.json(state)
    const body = options?.body ? JSON.parse(String(options.body)) : {}
    if (url === '/api/login') {
      state = active
      return Response.json(state)
    }
    if (String(url).startsWith('/api/game/list?'))
      return Response.json({
        success: true,
        games: [],
        pagination: { page: 1, per_page: 20, total: 0, pages: 1 },
        active_game_id: null,
      })
    if (url === '/api/register') return Response.json({ success: true, uid: 2 }, { status: 201 })
    if (url === '/api/logout') {
      state = anonymous
      return Response.json({ success: true })
    }
    if (url === '/api/user/1/update') {
      const user = { ...active.user!, introduction: body.introduction }
      state = body.new_password ? anonymous : { ...active, authenticated: true, user }
      return Response.json({ success: true, reauthenticate: !!body.new_password, user })
    }
    throw new Error(`Unexpected request: ${url}`)
  })
  const client = createApiClient({ fetcher, origin: 'http://localhost' })
  const services = createServices(client)
  const router = createAppRouter(services, createMemoryHistory())
  // jsdom has no layout/scrolling; browser tests exercise actual navigation.
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
  await router.push(path)
  await router.isReady()
  const wrapper = mount(App, {
    attachTo: document.body,
    global: { plugins: [router], provide: { [servicesKey as symbol]: services } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, router, services, fetcher }
}

describe('migrated pages', () => {
  it('guards profile navigation and rejects external next targets', async () => {
    const { wrapper, router } = await page('/changepw/')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.next).toBe('/changepw/')
    expect(wrapper.find('h1').text()).toBe('登录')
    for (const value of [
      'https://evil.test',
      '//evil.test',
      ['/changepw/'],
      '/admin/other/',
      '/admin/dicts/2147483648/',
      '/game/2147483648/detail/',
      '/game/0/detail/',
      '/game/01/detail/',
      '/game/1/detail/?next=https://evil.test',
      '/game/01/',
      '/game/2147483648/',
    ])
      expect(afterLoginTarget(value)).toBe('/')
    expect(afterLoginTarget('/changepw/')).toBe('/changepw/')
    expect(afterLoginTarget('/admin/')).toBe('/admin/')
    expect(afterLoginTarget('/admin/dicts/1/')).toBe('/admin/dicts/1/')
    expect(afterLoginTarget('/game/1/')).toBe('/game/1/')
    expect(afterLoginTarget('/game/1/detail/')).toBe('/game/1/detail/')
    expect(afterLoginTarget('/game/2147483647/detail/')).toBe('/game/2147483647/detail/')
  })

  it('logs in with exact password and navigates to the Vue lobby', async () => {
    const { wrapper, fetcher, router } = await page('/login/')
    await wrapper.get('#username').setValue(' user1 ')
    await wrapper.get('#password').setValue(' secret ')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const write = fetcher.mock.calls.find(([url]) => url === '/api/login')!
    expect(JSON.parse(String(write[1]?.body))).toEqual({ username: 'user1', password: ' secret ' })
    await vi.dynamicImportSettled()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('lobby')
    expect(wrapper.find('nav img').exists()).toBe(false)
  })

  it('does not accept a late login response after leaving its form', async () => {
    const { wrapper, router, services, fetcher } = await page('/login/')
    let finish!: (response: Response) => void
    fetcher.mockImplementationOnce(
      async () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    await wrapper.get('#username').setValue('user1')
    await wrapper.get('#password').setValue('secret')
    await wrapper.get('form').trigger('submit')
    await router.push('/register/')
    await flushPromises()
    finish(Response.json(active))
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('register')
    expect(services.client.session.value?.authenticated).toBe(false)
  })

  it('registers only after password confirmation and uses shared accessible fields', async () => {
    const { wrapper, router, fetcher } = await page('/register/')
    await wrapper.get('#username').setValue('new-user')
    await wrapper.get('#password').setValue('secret1')
    await wrapper.get('#confirmation').setValue('different')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('#confirmation').attributes('aria-invalid')).toBe('true')
    expect(fetcher.mock.calls.some(([url]) => url === '/api/register')).toBe(false)
    await wrapper.get('#confirmation').setValue('secret1')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')
    expect(wrapper.text()).toContain('注册成功，请登录')
  })

  it('updates introduction without transmitting password or credential fields', async () => {
    const { wrapper, fetcher } = await page('/changepw/', active)
    await wrapper.get('#introduction').setValue('<script>not executable</script>')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const write = fetcher.mock.calls.find(([url]) => url === '/api/user/1/update')!
    expect(JSON.parse(String(write[1]?.body))).toEqual({
      introduction: '<script>not executable</script>',
    })
    expect(wrapper.text()).toContain('资料已保存')
    expect(wrapper.find('script').exists()).toBe(false)
  })

  it('changing password clears identity and returns to login', async () => {
    const { wrapper, router, services } = await page('/changepw/', active)
    await wrapper.get('#currentPassword').setValue('old-secret')
    await wrapper.get('#newPassword').setValue('new-secret')
    await wrapper.get('#confirmation').setValue('new-secret')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')
    expect(services.client.session.value?.authenticated).not.toBe(true)
    expect(wrapper.text()).toContain('密码已更新')
  })

  it('logs out through CSRF-protected API and clears the profile view', async () => {
    const { wrapper, router, services, fetcher } = await page('/changepw/', active)
    await wrapper.get('nav button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')
    expect(services.client.session.value?.authenticated).not.toBe(true)
    expect(wrapper.find('#introduction').exists()).toBe(false)
    const write = fetcher.mock.calls.find(([url]) => url === '/api/logout')!
    expect(new Headers(write[1]?.headers).get('X-CSRF-Token')).toBe('session-token')
  })

  it('uses router links for migrated navigation destinations', async () => {
    const { wrapper } = await page('/login/')
    for (const path of ['/', '/leaderboard/']) {
      expect(wrapper.find(`nav a[href="${path}"]`).exists()).toBe(true)
    }
  })
})
