import { api, expect, login, logout, rejected, test } from './support'

test('manual Rating review, password rejection, committed lost confirmation and original retry', async ({
  newActor,
}) => {
  const admin = await newActor()
  const ordinary = await newActor()
  await login(admin, 'user3')
  await login(ordinary, 'user2')
  await rejected(ordinary, '/api/admin/user/1/rating', 'GET', undefined, 403, 'forbidden')
  await admin.goto('/admin/users/')
  const target = admin.locator('tr[data-user-id="1"]')
  const writes: Record<string, unknown>[] = []
  admin.on('request', (request) => {
    if (
      new URL(request.url()).pathname === '/api/admin/user/1/rating' &&
      request.method() === 'POST'
    )
      writes.push(request.postDataJSON())
  })
  await target.getByRole('button', { name: '调整 Rating / 流水', exact: true }).click()
  await admin.getByLabel('新的 Rating（不是增减量）', { exact: true }).fill('1700')
  await admin
    .getByLabel('调整原因（管理流水可见，请勿填写密码）', { exact: true })
    .fill('<img src=x onerror=alert(1)> approved')
  await admin.getByRole('button', { name: '审查修改', exact: true }).click()
  expect(writes).toHaveLength(0)
  await expect(admin.getByRole('dialog')).toContainText('1500 → 1700')
  await admin.getByLabel('本人当前密码（不是目标用户密码）', { exact: true }).fill('wrong')
  await admin.getByRole('button', { name: '确认修改 Rating', exact: true }).click()
  await expect(admin.getByRole('alert').filter({ hasText: '用户名或密码不正确' })).toBeVisible()
  expect((await api(admin, '/api/admin/user/1/rating')).body.rating).toBe(1500)
  await admin.getByLabel('本人当前密码（不是目标用户密码）', { exact: true }).fill('test-password')
  await admin.getByRole('button', { name: '重试原请求', exact: true }).click()
  await expect(admin.getByRole('dialog')).toHaveCount(0)
  await expect(target.getByRole('cell', { name: '1700', exact: true })).toBeVisible()
  expect(writes).toHaveLength(2)
  expect(writes[0]?.request_id).toBe(writes[1]?.request_id)
  expect((await api(admin, '/api/session')).body.authenticated).toBe(true)

  let loseOnce = true
  await admin.route('**/api/admin/user/1/rating', async (route) => {
    if (route.request().method() === 'POST' && loseOnce) {
      loseOnce = false
      const committed = await route.fetch()
      expect(committed.status()).toBe(200)
      await route.abort('failed') // Real server already committed; only discard the browser's reply.
    } else await route.continue()
  })
  await target.getByRole('button', { name: '调整 Rating / 流水', exact: true }).click()
  await expect(admin.getByRole('dialog')).toContainText('人工调整')
  await expect(admin.getByRole('dialog').locator('img')).toHaveCount(0)
  await admin.getByLabel('新的 Rating（不是增减量）', { exact: true }).fill('1800')
  await admin
    .getByLabel('调整原因（管理流水可见，请勿填写密码）', { exact: true })
    .fill('lost confirmation check')
  await admin.getByRole('button', { name: '审查修改', exact: true }).click()
  await admin.getByLabel('本人当前密码（不是目标用户密码）', { exact: true }).fill('test-password')
  await admin.getByRole('button', { name: '确认修改 Rating', exact: true }).click()
  await expect(admin.getByRole('alert').filter({ hasText: '网络异常' })).toBeVisible()
  expect((await api(admin, '/api/admin/user/1/rating')).body.rating).toBe(1800)
  expect(writes).toHaveLength(3)
  await expect(admin.getByLabel('本人当前密码（不是目标用户密码）', { exact: true })).toHaveValue(
    '',
  )
  await admin.getByLabel('本人当前密码（不是目标用户密码）', { exact: true }).fill('test-password')
  await admin.getByRole('button', { name: '重试原请求', exact: true }).click()
  await expect(admin.getByRole('dialog')).toHaveCount(0)
  expect(writes).toHaveLength(4)
  expect(writes[3]).toEqual(writes[2])
  await expect(target.getByRole('cell', { name: '1800', exact: true })).toBeVisible()
  const review = (await api(admin, '/api/admin/user/1/rating')).body
  expect(review.events).toHaveLength(2)
  expect(review.events.map((entry: { kind: string }) => entry.kind)).toEqual(['manual', 'manual'])
  expect(review.events.map((entry: { game_id: number | null }) => entry.game_id)).toEqual([
    null,
    null,
  ])
  await rejected(
    admin,
    '/api/admin/user/1/update',
    'POST',
    { rating: 9000 },
    400,
    'invalid_parameters',
  )
  await logout(ordinary)
  await logout(admin)
})
