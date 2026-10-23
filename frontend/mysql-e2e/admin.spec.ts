import { api, enterCredentials, expect, login, logout, rejected, test } from './support'

test('admin reset, ban and restore revoke real HTTP/Socket sessions without reviving old cookies', async ({
  newActor,
}) => {
  const admin = await newActor()
  const first = await newActor()
  const second = await newActor()
  const ordinary = await newActor()
  const replay = await newActor()
  await login(admin, 'user3')
  await login(first, 'user1')
  await login(second, 'user1')
  await login(ordinary, 'user2')
  await replay.goto('/login/')
  await rejected(replay, '/api/admin/users', 'GET', undefined, 401, 'unauthenticated')
  await rejected(ordinary, '/api/admin/users', 'GET', undefined, 403, 'forbidden')
  for (const action of ['reset-password', 'delete', 'restore']) {
    const forged = { new_password: 'unauthorized-password', uid: 3, type: 'root', pwhash: 'fake' }
    await rejected(ordinary, `/api/admin/user/1/${action}`, 'POST', forged, 403, 'forbidden')
    await rejected(admin, `/api/admin/user/3/${action}`, 'POST', forged, 400, 'invalid_parameters')
  }
  const denied = await ordinary.goto('/admin/users/')
  expect(denied?.status()).toBe(403) // Real HTML guard, not just a hidden Vue link.
  await ordinary.goto('/admin/')
  await expect(ordinary.getByRole('link', { name: '用户管理', exact: true })).toHaveCount(0)

  await admin.getByRole('link', { name: '管理', exact: true }).click()
  await admin.getByRole('link', { name: '用户管理', exact: true }).click()
  const self = admin
    .getByRole('row')
    .filter({ has: admin.getByRole('link', { name: 'user3', exact: true }) })
  await expect(self).toContainText('当前账号')
  await expect(self.getByRole('button', { name: '编辑资料', exact: true })).toHaveCount(1)
  await expect(self.getByRole('button', { name: '调整 Rating / 流水', exact: true })).toHaveCount(1)
  await expect(self.getByRole('button')).toHaveCount(2)
  await admin.getByLabel('按用户名搜索', { exact: true }).fill('user1')
  await admin.getByRole('button', { name: '搜索用户', exact: true }).click()
  const target = admin
    .getByRole('row')
    .filter({ has: admin.getByRole('link', { name: 'user1', exact: true }) })
  await expect(target).toHaveCount(1)
  await expect(target.locator('.user-name')).toHaveCSS('color', 'rgb(3, 168, 158)')
  await first.goto('/changepw/')
  await second.goto('/game/1/')
  await second.getByLabel('自动刷新（5 秒）', { exact: true }).uncheck()
  await expect(second.getByText('实时连接已订阅', { exact: false })).toBeVisible()
  const oldCookies = [
    (await first.context().cookies()).find((cookie) => cookie.name === 'wm_session')!,
    (await second.context().cookies()).find((cookie) => cookie.name === 'wm_session')!,
  ]
  const resetPassword = ' admin reset secret '
  await target.getByRole('button', { name: '重置密码', exact: true }).click()
  await expect(admin.locator('dialog .user-name')).toHaveCSS('color', 'rgb(3, 168, 158)')
  await admin.getByLabel('新密码', { exact: true }).fill(resetPassword)
  await admin.getByLabel('确认新密码', { exact: true }).fill('mismatch')
  await admin.getByRole('button', { name: '确认重置密码', exact: true }).click()
  await expect(admin.getByRole('alert')).toContainText('两次输入的密码不一致')
  expect((await api(first, '/api/session')).body.authenticated).toBe(true)
  await admin.getByLabel('确认新密码', { exact: true }).fill(resetPassword)
  await admin.getByRole('button', { name: '确认重置密码', exact: true }).click()
  await expect(admin.getByRole('dialog')).toHaveCount(0)
  // Polling is disabled: the real Socket disconnect/read path must retire this page.
  await expect(second).toHaveURL(/\/login\/\?next=/)
  await first.getByLabel('个人简介', { exact: true }).fill('revoked by reset')
  await first.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect(first).toHaveURL(/\/login\/\?next=/)
  for (const cookie of oldCookies) {
    await replay.context().addCookies([cookie])
    await rejected(replay, '/api/dicts', 'GET', undefined, 401, 'unauthenticated')
  }
  await enterCredentials(first, 'user1', 'test-password')
  await expect(first.getByRole('alert')).toContainText('用户名或密码不正确')
  await login(first, 'user1', resetPassword)
  await login(second, 'user1', resetPassword)
  oldCookies.push(
    (await first.context().cookies()).find((cookie) => cookie.name === 'wm_session')!,
    (await second.context().cookies()).find((cookie) => cookie.name === 'wm_session')!,
  )
  await second.goto('/game/1/')
  await second.getByLabel('自动刷新（5 秒）', { exact: true }).uncheck()
  await expect(second.getByText('实时连接已订阅', { exact: false })).toBeVisible()
  await target.getByRole('button', { name: '封禁用户', exact: true }).click()
  await admin.getByRole('button', { name: '确认封禁用户', exact: true }).click()
  await expect(target).toHaveCount(0)
  await expect(second).toHaveURL(/\/login\/\?next=/)
  await rejected(first, '/api/dicts', 'GET', undefined, 401, 'unauthenticated')
  await rejected(replay, '/api/user/1', 'GET', undefined, 404, 'not_found')
  expect((await replay.goto('/user/1/'))?.status()).toBe(404)
  await enterCredentials(first, 'user1', resetPassword)
  await expect(first.getByRole('alert')).toContainText('用户名或密码不正确')
  await admin.getByLabel('包含已封禁用户', { exact: true }).check()
  await expect(target).toContainText('已封禁')
  await target.getByRole('button', { name: '恢复用户', exact: true }).click()
  await admin.getByRole('button', { name: '确认恢复用户', exact: true }).click()
  await expect(target).toContainText('正常')
  for (const cookie of oldCookies) {
    await replay.context().addCookies([cookie])
    await rejected(replay, '/api/dicts', 'GET', undefined, 401, 'unauthenticated')
  }
  await login(first, 'user1', resetPassword)
  expect((await replay.goto('/user/1/'))?.status()).toBe(200)
  await expect(replay.getByRole('heading', { name: 'user1 #1', exact: true })).toBeVisible()
  await logout(first)
  await logout(ordinary)
  await logout(admin)
})
