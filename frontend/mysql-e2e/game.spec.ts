import { expect, test, type Page, type WebSocketRoute } from '@playwright/test'

import { login } from './support'

async function start(first: Page, second: Page, dictionary: string) {
  await first.getByRole('link', { name: '主页', exact: true }).click()
  await first.getByLabel('自动刷新并进入已开局对局（5 秒）').uncheck()
  await first.getByRole('button', { name: '创建新对局', exact: true }).click()
  await first.getByRole('radio', { name: new RegExp(dictionary) }).check()
  await first.getByRole('button', { name: '创建对局', exact: true }).click()
  const card = first.getByRole('article').filter({ hasText: dictionary })
  await expect(card).toHaveCount(1)
  await expect(card.locator('.user-name').first()).toHaveCSS('color', 'rgb(3, 168, 158)')
  const title = await card.getByRole('heading').innerText()
  const id = Number(title.match(/#(\d+)/)![1])
  await second.getByRole('link', { name: '主页', exact: true }).click()
  await second.getByLabel('自动刷新并进入已开局对局（5 秒）').uncheck()
  await second.getByRole('button', { name: '刷新列表', exact: true }).click()
  await second
    .getByRole('article', { name: title, exact: true })
    .getByRole('button', { name: '报名', exact: true })
    .click()
  await second.getByRole('button', { name: '确认报名', exact: true }).click()
  await expect(second.getByRole('dialog')).toHaveCount(0)
  await first.getByRole('button', { name: '刷新列表', exact: true }).click()
  await card.getByRole('button', { name: '开始对局', exact: true }).click()
  await first.getByRole('button', { name: '确认开始对局', exact: true }).click()
  await expect(first).toHaveURL(new RegExp(`/game/${id}/$`))
  await second.goto(`/game/${id}/`)
  await expect(second.getByRole('heading', { name: title, exact: true })).toBeVisible()
  return id
}
const answers: Record<string, string> = { 苹果: 'apple', 香蕉: 'banana', 猫: 'cat' }
async function current(first: Page, second: Page) {
  await expect
    .poll(
      async () =>
        (await first.getByLabel('英文答案', { exact: true }).isEnabled()) ||
        (await second.getByLabel('英文答案', { exact: true }).isEnabled()),
    )
    .toBe(true)
  return (await first.getByLabel('英文答案', { exact: true }).isEnabled()) ? first : second
}
async function submit(page: Page) {
  const chinese = (await page.locator('.game-prompt').innerText()).trim()
  expect(answers[chinese]).toBeTruthy()
  await page.getByLabel('英文答案', { exact: true }).fill(answers[chinese]!)
  await page.getByRole('button', { name: '提交答案', exact: true }).click()
}

test('real users maintain a dictionary, play over Socket/HTTP, reconnect and settle once', async ({
  browser,
}) => {
  const options = { baseURL: process.env.WM_BROWSER_MYSQL_ORIGIN }
  const firstContext = await browser.newContext(options),
    secondContext = await browser.newContext(options)
  const first = await firstContext.newPage(),
    second = await secondContext.newPage()
  const sockets: WebSocketRoute[] = []
  await first.routeWebSocket(/\/socket.io\//, (route) => {
    sockets.push(route)
    route.connectToServer()
  })
  let socketAnswers = 0
  second.on('websocket', (socket) =>
    socket.on('framesent', (frame) => {
      if (String(frame.payload).includes('"game.answer"')) socketAnswers++
    }),
  )
  try {
    await login(first, 'user1')
    await login(second, 'user2')
    await first.getByRole('link', { name: '管理', exact: true }).click()
    await first.getByRole('button', { name: '新建词典', exact: true }).click()
    await first.getByLabel('词典名称', { exact: true }).fill('浏览器词典')
    await first.getByRole('button', { name: '保存词典' }).click()
    await first.getByLabel('CSV 文本', { exact: true }).fill('apple,苹果\nbanana,香蕉\ncat,猫')
    await first.getByRole('button', { name: '导入 CSV', exact: true }).click()
    await expect(first.getByText('成功导入 3 个单词。', { exact: true })).toBeVisible()
    const id = await start(first, second, '浏览器词典')
    await expect(first.locator('nav .user-name')).toHaveCSS('color', 'rgb(3, 168, 158)')
    await expect(
      first.locator('section[aria-labelledby="game-overview-title"] .user-name'),
    ).toHaveCSS('color', 'rgb(3, 168, 158)')
    await expect(
      second.locator('section[aria-labelledby="game-scores-title"] .user-name').first(),
    ).toHaveCSS('color', 'rgb(3, 168, 158)')
    await expect(first.getByText('实时连接已订阅', { exact: false })).toBeVisible()
    await expect(second.getByText('实时连接已订阅', { exact: false })).toBeVisible()
    await expect.poll(() => sockets.length).toBeGreaterThan(0)
    // Close a real proxied WebSocket, not a mocked game API. The manager must reconnect.
    await sockets[0]!.close({ code: 1001, reason: 'test disconnect' })
    await expect.poll(() => sockets.length).toBeGreaterThan(1)
    await expect(first.getByText('实时连接已订阅', { exact: false })).toBeVisible()
    // First participant deliberately uses HTTP; second uses the real Socket acknowledgement.
    await first.getByLabel('启用实时连接').uncheck()
    for (let index = 0; index < 3; index++) {
      const player = await current(first, second)
      await submit(player)
      if (index < 2) {
        await expect(first.getByText(`${index + 1} / 3`, { exact: false })).toBeVisible()
        await expect(second.getByText(`${index + 1} / 3`, { exact: false })).toBeVisible()
        await expect(player.getByRole('region', { name: '原请求确认' })).toHaveCount(0)
      }
    }
    await expect(first).toHaveURL(new RegExp(`/game/${id}/detail/$`))
    await expect(second).toHaveURL(new RegExp(`/game/${id}/detail/$`))
    expect(socketAnswers).toBeGreaterThan(0)
    const state = (await (await first.request.get(`/api/game/${id}`)).json()).game
    expect(state.result).toHaveLength(3)
    expect(state.version).toBe(5)
    expect(state.result.every((row: { result: boolean }) => row.result)).toBe(true)
    await first.reload()
    await expect(first.getByRole('heading', { name: `对局详情 #${id}`, exact: true })).toBeVisible()
    const scoreTable = first.locator('section[aria-labelledby="game-scores-title"]')
    for (const history of state.userrating) {
      const entry = history.ratinghistory.find((row: { game_id: number }) => row.game_id === id)
      if (entry) await expect(scoreTable).toContainText(String(entry.new_rating))
    }
  } finally {
    await firstContext.close()
    await secondContext.close()
  }
})

test('a real committed HTTP response lost in transit is retried with its original ID, then early end settles once', async ({
  browser,
}) => {
  const options = { baseURL: process.env.WM_BROWSER_MYSQL_ORIGIN }
  const c1 = await browser.newContext(options),
    c2 = await browser.newContext(options)
  const first = await c1.newPage(),
    second = await c2.newPage()
  try {
    await login(first, 'user1')
    await login(second, 'user2')
    const id = await start(first, second, 'test dictionary')
    await first.getByLabel('启用实时连接').uncheck()
    await second.getByLabel('启用实时连接').uncheck()
    const player = await current(first, second)
    const payloads: unknown[] = []
    await player.route(`**/api/game/${id}/answer`, async (route) => {
      payloads.push(route.request().postDataJSON())
      if (payloads.length === 1) {
        const committed = await route.fetch()
        expect(committed.ok()).toBe(true)
        await route.abort('connectionreset') // Actual transaction committed; only confirmation is lost.
      } else await route.continue()
    })
    await submit(player)
    await expect(player.getByRole('button', { name: '重试原请求', exact: true })).toBeEnabled()
    expect(payloads).toHaveLength(1)
    await player.getByRole('button', { name: '重试原请求', exact: true }).click()
    await expect(player.getByRole('region', { name: '原请求确认' })).toHaveCount(0)
    expect(payloads).toHaveLength(2)
    expect(payloads[1]).toEqual(payloads[0])
    await first.getByRole('button', { name: '刷新对局', exact: true }).click()
    await expect(first.getByText('1 / 3', { exact: false })).toBeVisible()
    await first.getByRole('button', { name: '提前结束对局', exact: true }).click()
    await first.getByRole('button', { name: '确认结束', exact: true }).click()
    await expect(first).toHaveURL(new RegExp(`/game/${id}/detail/$`))
    await second.goto(`/game/${id}/`)
    await expect(second).toHaveURL(new RegExp(`/game/${id}/detail/$`))
    const state = (await (await first.request.get(`/api/game/${id}`)).json()).game
    expect(state.result).toHaveLength(1)
    expect(state.version).toBe(4)
    expect(state.words.slice(1).every((word: object) => !('english' in word))).toBe(true)
    // Server-side logout revokes the cookie and old token, not only a client guard.
    await first.getByRole('button', { name: '登出', exact: true }).click()
    await expect(first).toHaveURL(/\/login\/$/)
    expect((await first.request.get(`/api/game/${id}`)).status()).toBe(401)
  } finally {
    await c1.close()
    await c2.close()
  }
})
