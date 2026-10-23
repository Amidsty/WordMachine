import { expect, test, type Page } from '@playwright/test'
import { createLobbyApi } from '../testing/lobbyApi'
import { backendOrigin } from './servers'
import { gameState } from '../testing/gameApi'

async function mockApi(page: Page, authenticated = true) {
  const api = createLobbyApi(authenticated)
  const requests: string[] = []
  await page.route('**/socket.io/**', (route) => route.abort())
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    async (route) => {
      const request = route.request()
      requests.push(new URL(request.url()).pathname)
      const gameMatch = /^\/api\/game\/(\d+)$/.exec(new URL(request.url()).pathname)
      if (gameMatch) {
        await route.fulfill({
          json: { success: true, game: gameState(Number(gameMatch[1]), 0, 0) },
        })
        return
      }
      const result = api.handle(
        request.url(),
        request.method(),
        request.postData() ? request.postDataJSON() : {},
        request.headers()['x-csrf-token'],
      )
      await route.fulfill({ status: result.status, json: result.body })
    },
  )
  return { api, requests }
}

test('anonymous leaderboard/profile use public Vue routes and preserve text/null values (mock API)', async ({
  page,
}) => {
  const { api } = await mockApi(page, false)
  api.users[1]!.rating = null
  await page.goto(`${backendOrigin}/leaderboard/`)
  await expect(page.getByRole('heading', { name: '排行榜', exact: true })).toBeVisible()
  await expect(page.locator('tbody tr')).toHaveCount(20)
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(page.locator('tbody tr').first().locator('td').first()).toHaveText('21')
  await page.getByRole('button', { name: '上一页', exact: true }).click()
  await page.getByRole('link', { name: '<img src=x>', exact: true }).click()
  await expect(page).toHaveURL(/\/user\/2\/$/)
  await expect(page.getByText('记录缺失', { exact: true })).toBeVisible()
  await expect(page.getByText('<script>first</script>', { exact: false })).toBeVisible()
  await expect(page.locator('main img, main script')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '修改我的资料' })).toHaveCount(0)
  // Vite deep-link refresh; the production HTML existence check requires a real DB.
  await page.goto('/user/2/')
  await page.reload()
  await expect(page.getByRole('heading', { name: '公开资料', exact: true })).toBeVisible()
  await page.goto('/user/999/')
  await expect(page.getByRole('alert')).toContainText('记录不存在或已删除')
})

test('built name colors use Rating tiers, survive links/navigation and keep names as text (mock API)', async ({
  page,
}) => {
  const { api, requests } = await mockApi(page)
  const samples = [
    [1500, 'rgb(3, 168, 158)'],
    [1199, 'rgb(128, 128, 128)'],
    [1200, 'rgb(0, 128, 0)'],
    [1400, 'rgb(3, 168, 158)'],
    [1600, 'rgb(0, 0, 255)'],
    [1900, 'rgb(170, 0, 170)'],
    [2100, 'rgb(255, 140, 0)'],
    [2400, 'rgb(255, 0, 0)'],
    [3000, 'rgb(255, 0, 0)'],
    [null, 'rgb(81, 96, 120)'],
  ] as const
  samples.forEach(([rating], index) => {
    api.users[index]!.rating = rating
  })
  api.users[8]!.username = '👩‍💻 e\u0301 <img src=x>'
  await page.goto(`${backendOrigin}/leaderboard/`)
  await expect(page.locator('nav .user-name')).toHaveCSS('color', 'rgb(3, 168, 158)')
  for (const [index, [, color]] of samples.entries()) {
    const name = page.locator(`tbody a[href="/user/${index + 1}/"] .user-name`)
    await expect(name).toHaveCSS('color', color)
    await name.hover()
    await expect(name).toHaveCSS('color', color)
  }
  const legendary = page.locator('tbody a[href="/user/9/"] .user-name')
  await expect(legendary).toHaveText(api.users[8]!.username)
  await expect(legendary).toHaveCSS('display', 'inline-block')
  expect(await legendary.evaluate((node) => getComputedStyle(node, '::first-letter').color)).toBe(
    'rgb(0, 0, 0)',
  )
  expect(requests.filter((path) => /^\/api\/user\//.test(path))).toHaveLength(0)
  await legendary.click()
  await expect(page.locator('h2 .user-name')).toHaveCSS('color', 'rgb(255, 0, 0)')
  await expect(page.locator('main img')).toHaveCount(0)
  await page.getByRole('link', { name: '修改资料', exact: true }).click()
  await expect(page.locator('main .user-name')).toHaveCSS('color', 'rgb(3, 168, 158)')
})

test('built lobby creates, joins, leaves, cancels and starts using shared dialogs (mock API/Vue playing)', async ({
  page,
}) => {
  const { api } = await mockApi(page)
  await page.goto(`${backendOrigin}/login/`)
  await page.getByRole('link', { name: '主页', exact: true }).click()
  await expect(page.getByRole('heading', { name: '对局大厅', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '创建新对局', exact: true }).click()
  await page.getByRole('radio', { name: /Owned/ }).check()
  await expect(page.locator('main img')).toHaveCount(0)
  await page.getByRole('button', { name: '创建对局', exact: true }).click()
  await expect(page.getByRole('article', { name: '对局 #6', exact: true })).toBeVisible()
  const joining = page.getByRole('article', { name: '对局 #1', exact: true })
  await joining.getByRole('button', { name: '报名', exact: true }).click()
  await page.getByRole('button', { name: '确认报名', exact: true }).click()
  await expect(joining.getByRole('button', { name: '撤销报名', exact: true })).toBeVisible()
  await joining.getByRole('button', { name: '撤销报名', exact: true }).click()
  await page.getByRole('button', { name: '确认撤销报名', exact: true }).click()
  await expect(joining.getByRole('button', { name: '报名', exact: true })).toBeVisible()
  await page
    .getByRole('article', { name: '对局 #6', exact: true })
    .getByRole('button', { name: '取消对局', exact: true })
    .click()
  await page.getByRole('button', { name: '确认取消对局', exact: true }).click()
  await page.getByRole('button', { name: '已取消', exact: true }).click()
  await expect(page.getByRole('article', { name: '对局 #6', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '待开始', exact: true }).click()
  await page.getByRole('button', { name: '开始对局', exact: true }).click()
  await page.getByRole('button', { name: '确认开始对局', exact: true }).click()
  await expect(page).toHaveURL(`${backendOrigin}/game/2/`)
  await expect(page.getByRole('heading', { name: '对局 #2', exact: true })).toBeVisible()
  await expect(page.getByLabel('英文答案', { exact: true })).toBeEnabled()
  expect(api.writes.map((write) => write.path)).toEqual([
    '/api/game/create',
    '/api/game/1/join',
    '/api/game/1/leave',
    '/api/game/6/cancel',
    '/api/game/2/start',
  ])
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
  expect(api.writes[0]?.body).toEqual({ dict_id: 2, request_id: expect.stringMatching(uuid) })
  expect(api.writes.slice(1).map((write) => write.body)).toEqual(
    [0, 1, 0, 0].map((version) => ({
      expected_version: version,
      request_id: expect.stringMatching(uuid),
    })),
  )
  expect(new Set(api.writes.map((write) => write.body.request_id)).size).toBe(5)
})

test('lobby polling stops on route leave, pauses in dialogs and enters off-page running games (mock API/landing)', async ({
  page,
}) => {
  const { api, requests } = await mockApi(page)
  await page.clock.install()
  await page.goto('/')
  await expect(page.getByRole('article')).toHaveCount(2)
  const count = () => requests.filter((path) => path === '/api/game/list').length
  await page.clock.fastForward(5000)
  await expect.poll(count).toBe(2)
  await page.getByRole('link', { name: '排行榜', exact: true }).click()
  await expect(page.locator('tbody tr')).toHaveCount(20)
  const left = count()
  await page.clock.fastForward(20000)
  expect(count()).toBe(left)
  await page.getByRole('link', { name: '主页', exact: true }).click()
  await expect(page.getByRole('article')).toHaveCount(2)
  await page.getByRole('button', { name: '创建新对局', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  const paused = count()
  api.state.activeGameId = 777
  await page.clock.fastForward(20000)
  expect(count()).toBe(paused)
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page).toHaveURL(/\/game\/777\/$/)
  expect(api.writes).toHaveLength(0)
})
