import { expect, test } from '@playwright/test'
import { backendOrigin } from './servers'

// Real browser and Vite -> Flask transport; authentication mutations below are
// explicitly mocked. These do NOT stand in for the MySQL acceptance suite.
test('Flask serves the built app and hashed assets on explicit migrated URLs', async ({ page }) => {
  const requests: string[] = []
  page.on('request', (request) => requests.push(new URL(request.url()).pathname))
  await page.goto(`${backendOrigin}/login/`)
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible()
  expect(requests.some((path) => path.startsWith('/ui/assets/') && path.endsWith('.js'))).toBe(true)
  await page.getByRole('link', { name: '注册账号', exact: true }).click()
  await expect(page).toHaveURL(`${backendOrigin}/register/`)
  await page.reload()
  await expect(page.getByRole('heading', { name: '注册账号', exact: true })).toBeVisible()
  expect((await page.request.get(`${backendOrigin}/ui/assets/missing.js`)).status()).toBe(404)
  expect((await page.request.get(`${backendOrigin}/unknown/`)).status()).toBe(404)
  for (const path of ['/', '/admin/', '/admin/dicts/2/', '/admin/users/']) {
    const response = await page.request.get(`${backendOrigin}${path}`, { maxRedirects: 0 })
    expect(response.status()).toBe(302)
    const location = new URL(response.headers().location!, backendOrigin)
    expect(location.pathname).toBe('/login/')
    expect(location.searchParams.get('next')).toBe(path)
  }
  expect((await page.request.get(`${backendOrigin}/admin/unknown/`)).status()).toBe(404)
})

test('development proxy preserves Origin for the real anonymous CSRF flow', async ({ page }) => {
  await page.goto('/login/')
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible()
  const result = await page.evaluate(async () => {
    const state = await (await fetch('/api/session')).json()
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf_token },
      body: JSON.stringify({ username: '', password: 'secret' }),
    })
    return { status: response.status, body: await response.json() }
  })
  // Invalid input fails before DB access; 400, not an Origin/CSRF 403.
  expect(result.status).toBe(400)
  expect(result.body.code).not.toBe('csrf_failed')
  expect(await page.evaluate(() => document.cookie)).not.toContain('wm_csrf')
  const api404 = await page.request.get('/api/not-a-route')
  expect(api404.status()).toBe(404)
  expect(api404.headers()['content-type']).toContain('application/json')
})

test('login, introduction update, password change and deep-link refresh (mock API)', async ({
  page,
}) => {
  let authenticated = false
  let introduction = 'initial'
  const writes: { url: string; body: Record<string, string> }[] = []
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    async (route) => {
      const request = route.request()
      const url = new URL(request.url()).pathname
      const user = () => ({
        id: 1,
        username: '<img src=x onerror=alert(1)>',
        introduction,
        rating: 1500,
        type: 'normal',
      })
      if (url === '/api/session') {
        await route.fulfill({
          json: {
            success: true,
            authenticated,
            user: authenticated ? user() : null,
            csrf_token: authenticated ? 'user-token' : 'anon-token',
          },
        })
        return
      }
      expect(request.headers()['x-csrf-token']).toBe(authenticated ? 'user-token' : 'anon-token')
      const body = request.postDataJSON()
      writes.push({ url, body })
      if (url === '/api/login') {
        authenticated = true
        await route.fulfill({
          json: { success: true, authenticated: true, user: user(), csrf_token: 'user-token' },
        })
      } else if (url === '/api/user/1/update') {
        introduction = body.introduction
        const changed = !!body.new_password
        if (changed) authenticated = false
        await route.fulfill({ json: { success: true, user: user(), reauthenticate: changed } })
      } else throw new Error(`Unexpected request ${url}`)
    },
  )
  await page.goto('/changepw/')
  await expect(page).toHaveURL(/\/login\/\?next=/)
  await page.getByLabel('用户名', { exact: true }).fill('user1')
  await page.getByLabel('密码', { exact: true }).fill(' secret ')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '修改资料', exact: true })).toBeVisible()
  expect(writes[0]?.body.password).toBe(' secret ')
  await page.reload()
  await expect(page.getByLabel('个人简介', { exact: true })).toHaveValue('initial')
  await expect(page.locator('nav img')).toHaveCount(0)
  await page.getByLabel('个人简介', { exact: true }).fill('updated')
  await page.getByRole('button', { name: '保存修改' }).click()
  await expect(page.getByRole('status')).toHaveText('资料已保存。')
  expect(writes[1]?.body).toEqual({ introduction: 'updated' })
  await page.getByLabel('当前密码', { exact: true }).fill(' secret ')
  await page.getByLabel('新密码', { exact: true }).fill('new-secret')
  await page.getByLabel('确认新密码', { exact: true }).fill('new-secret')
  await page.getByRole('button', { name: '保存修改' }).click()
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible()
  await expect(page.getByRole('status')).toContainText('密码已更新')
})

test('registration confirmation, throttling feedback and no automatic write retry (mock API)', async ({
  page,
}) => {
  let attempts = 0
  await page.route('**/api/session', (route) =>
    route.fulfill({
      json: { success: true, authenticated: false, user: null, csrf_token: 'anon-token' },
    }),
  )
  await page.route('**/api/register', async (route) => {
    attempts += 1
    await route.fulfill({
      status: 429,
      headers: { 'Retry-After': '30' },
      json: { success: false, code: 'rate_limited', message: 'Too many attempts' },
    })
  })
  await page.goto('/register/')
  await page.getByLabel('用户名', { exact: true }).fill('new-user')
  await page.getByLabel('密码', { exact: true }).fill('secret1')
  await page.getByLabel('确认密码', { exact: true }).fill('different')
  await page.getByRole('button', { name: '注册', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('两次输入的密码不一致')
  expect(attempts).toBe(0)
  await page.getByLabel('确认密码', { exact: true }).fill('secret1')
  await page.getByRole('button', { name: '注册', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('30 秒')
  expect(attempts).toBe(1)
})
