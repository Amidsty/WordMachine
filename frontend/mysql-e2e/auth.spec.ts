import { api, enterCredentials, expect, login, logout, rejected, test } from './support'

test('registration, profile edits and password rotation use real sessions and revoke all old tokens', async ({
  newActor,
}) => {
  const first = await newActor()
  const second = await newActor()
  const replay = await newActor()
  const username = 'browser-account'
  const initialPassword = ' register secret '
  const newPassword = ' changed secret '
  await replay.goto('/login/')
  await replay.context().addCookies([
    { name: 'uid', value: '3', url: new URL(replay.url()).origin },
    {
      name: 'pwhash',
      value: 'legacy-credential-is-not-an-identity',
      url: new URL(replay.url()).origin,
    },
  ])
  await rejected(replay, '/api/admin/users', 'GET', undefined, 401, 'unauthenticated')
  expect(
    (await replay.context().cookies()).some((cookie) => ['uid', 'pwhash'].includes(cookie.name)),
  ).toBe(false)
  await first.goto('/register/')
  const anonymous = (await api(first, '/api/session')).body
  let registrations = 0
  await first.route('**/api/register', async (route) => {
    registrations++
    // Send forged authority to the REAL registration endpoint, never fulfill a stub.
    await route.continue({
      postData: JSON.stringify({
        ...route.request().postDataJSON(),
        type: 'root',
        rating: 9999,
        uid: 3,
      }),
    })
  })
  await first.getByLabel('用户名', { exact: true }).fill(username)
  await first.getByLabel('密码', { exact: true }).fill(initialPassword)
  await first.getByLabel('确认密码', { exact: true }).fill('not-the-same')
  await first.getByLabel('个人简介（可选）', { exact: true }).fill('registered introduction')
  await first.getByRole('button', { name: '注册', exact: true }).click()
  await expect(first.getByRole('alert')).toContainText('两次输入的密码不一致')
  expect(registrations).toBe(0)
  await first.getByLabel('确认密码', { exact: true }).fill(initialPassword)
  await first.getByRole('button', { name: '注册', exact: true }).click()
  await expect(first).toHaveURL(/\/login\/\?registered=1$/)
  expect(registrations).toBe(1)
  expect((await api(first, '/api/session')).body.authenticated).toBe(false)
  await rejected(
    first,
    '/api/register',
    'POST',
    {
      username: username.toUpperCase(),
      password: initialPassword,
    },
    409,
    'username_exists',
  )
  await enterCredentials(first, username, initialPassword.trim())
  await expect(first.getByRole('alert')).toContainText('用户名或密码不正确')
  await login(first, username, initialPassword)
  const session = (await api(first, '/api/session')).body
  const id = session.user.id as number
  expect(session.user).toMatchObject({ username, type: 'normal', rating: 0 })
  expect(session.csrf_token).not.toBe(anonymous.csrf_token)
  expect(JSON.stringify(session)).not.toMatch(/pwhash|token_hash|scrypt:/)
  const firstCookie = (await first.context().cookies()).find(
    (cookie) => cookie.name === 'wm_session',
  )!
  expect(firstCookie).toMatchObject({ httpOnly: true, sameSite: 'Lax', path: '/' })
  expect(await first.evaluate(() => document.cookie)).not.toContain('wm_session')
  await rejected(
    first,
    `/api/user/${id}/update`,
    'POST',
    { introduction: 'csrf-forged' },
    403,
    'csrf_failed',
    anonymous.csrf_token,
  )
  await rejected(
    first,
    `/api/user/${id}/update`,
    'POST',
    { introduction: 'csrf-missing' },
    403,
    'csrf_failed',
    null,
  )
  await rejected(
    first,
    '/api/user/1/update',
    'POST',
    { introduction: 'forged', uid: 1, type: 'root' },
    403,
    'forbidden',
  )

  await login(second, username, initialPassword)
  await second.getByRole('link', { name: '修改资料', exact: true }).click()
  const live = await second.context().newPage()
  await live.goto('/game/1/')
  await live.getByLabel('自动刷新（5 秒）', { exact: true }).uncheck()
  await expect(live.getByText('实时连接已订阅', { exact: false })).toBeVisible()
  const secondCookie = (await second.context().cookies()).find(
    (cookie) => cookie.name === 'wm_session',
  )!
  await first.getByRole('link', { name: '修改资料', exact: true }).click()
  const introduction = '<img src=x onerror="window.injected=1"> saved profile'
  await first.getByLabel('个人简介', { exact: true }).fill(introduction)
  await first.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect(first.getByText('资料已保存。', { exact: true })).toBeVisible()
  expect((await api(second, '/api/session')).body.authenticated).toBe(true)
  await first.getByLabel('个人简介', { exact: true }).fill('must roll back with wrong password')
  await first.getByLabel('当前密码', { exact: true }).fill('wrong-password')
  await first.getByLabel('新密码', { exact: true }).fill(newPassword)
  await first.getByLabel('确认新密码', { exact: true }).fill(newPassword)
  await first.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect(first.getByRole('alert')).toContainText('用户名或密码不正确')
  await expect(first).toHaveURL(/\/changepw\/$/)
  expect((await api(second, `/api/user/${id}`)).body.user.introduction).toBe(introduction)
  expect((await api(first, '/api/session')).body.authenticated).toBe(true)
  await first.getByLabel('个人简介', { exact: true }).fill(introduction)
  await first.getByLabel('当前密码', { exact: true }).fill(initialPassword)
  await first.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect(first).toHaveURL(/\/login\/\?reason=password_changed$/)
  await expect(
    first.getByText('密码已更新，所有会话已退出，请重新登录。', { exact: true }),
  ).toBeVisible()
  await expect(live).toHaveURL(/\/login\/\?next=/) // Socket revocation, polling disabled.
  // A stale second browser is not trusted just because it still renders a private form.
  await second.getByLabel('个人简介', { exact: true }).fill('revoked write')
  await second.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect(second).toHaveURL(/\/login\/\?next=/)
  await replay.goto('/login/')
  for (const cookie of [firstCookie, secondCookie]) {
    await replay.context().addCookies([cookie])
    await rejected(replay, '/api/dicts', 'GET', undefined, 401, 'unauthenticated')
  }
  await enterCredentials(first, username, initialPassword)
  await expect(first.getByRole('alert')).toContainText('用户名或密码不正确')
  await enterCredentials(first, username, newPassword.trim())
  await expect(first.getByRole('alert')).toContainText('用户名或密码不正确')
  await login(first, username, newPassword)
  await first.goto(`/user/${id}/`)
  await expect(first.getByText(introduction, { exact: true })).toBeVisible()
  await expect(first.locator('main img')).toHaveCount(0)
  await first.reload()
  await expect(first.getByText(introduction, { exact: true })).toBeVisible()
  const logoutCookie = (await first.context().cookies()).find(
    (cookie) => cookie.name === 'wm_session',
  )!
  await login(second, username, newPassword)
  await logout(first)
  await replay.context().addCookies([logoutCookie])
  await rejected(replay, '/api/dicts', 'GET', undefined, 401, 'unauthenticated')
  expect((await api(second, '/api/session')).body.authenticated).toBe(true)
  await logout(second)
})
