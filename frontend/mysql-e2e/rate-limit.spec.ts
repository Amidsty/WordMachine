import { api, expect, logout, test } from './support'

test('real 429 Retry-After is displayed and login is never automatically replayed', async ({
  newActor,
}) => {
  const page = await newActor()
  await page.goto('/login/')
  const anonymous = (await api(page, '/api/session')).body
  let attempts = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/login') attempts++
  })
  await page.getByLabel('用户名', { exact: true }).fill('user1')
  await page.getByLabel('密码', { exact: true }).fill('wrong-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('用户名或密码不正确')
  await page.getByLabel('密码', { exact: true }).fill('test-password')
  const response = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === '/api/login' && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '登录', exact: true }).click()
  const blocked = await response
  expect(blocked.status()).toBe(429)
  const retry = Number(await blocked.headerValue('Retry-After'))
  // The 4-second fixture window uses whole-second MySQL DATETIME storage,
  // so rounding forward can add one second to the advertised wait.
  expect(Number.isInteger(retry) && retry >= 1 && retry <= 5).toBe(true)
  expect(await blocked.json()).toMatchObject({
    success: false,
    code: 'rate_limited',
    details: { retry_after: retry },
  })
  await expect(page.getByRole('alert')).toHaveText(`操作过于频繁，请在 ${retry} 秒后重试。`)
  expect((await api(page, '/api/session')).body).toMatchObject({
    authenticated: false,
    csrf_token: anonymous.csrf_token,
  })
  // Intentionally observe the whole server-provided cooldown, not a latency gate
  // or a mocked time jump. There must be no timer-based resubmission after it.
  await page.waitForTimeout((retry + 0.1) * 1000)
  expect(attempts).toBe(2)
  await expect(page).toHaveURL(/\/login\/$/)
  await expect(page.getByRole('alert')).toContainText('操作过于频繁')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '对局大厅', exact: true })).toBeVisible()
  await page.getByLabel('自动刷新并进入已开局对局（5 秒）').uncheck()
  expect(attempts).toBe(3)
  const loggedIn = (await api(page, '/api/session')).body
  expect(loggedIn.user.id).toBe(1)
  expect(loggedIn.csrf_token).not.toBe(anonymous.csrf_token)
  await logout(page)
})
