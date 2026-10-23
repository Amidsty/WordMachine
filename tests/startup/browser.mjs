// Real HTTP/Cookie/CSS/WebSocket smoke for the dedicated local launcher; no API stubs.
import assert from 'node:assert/strict'
import { readFileSync, writeFileSync, chmodSync } from 'node:fs'
import { createRequire } from 'node:module'
import { randomUUID } from 'node:crypto'
const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const { chromium, expect } = require('@playwright/test')
const [origin, directory, loginFile, phase] = process.argv.slice(2)
const saved =
  phase === 'second' ? JSON.parse(readFileSync(`${directory}/facts.json`, 'utf8')) : null
const browser = await chromium.launch({ headless: true })
try {
  const context = await browser.newContext({
    baseURL: origin,
    storageState: saved ? `${directory}/cookies.json` : undefined,
  })
  const page = await context.newPage()
  const styles = []
  let websockets = 0
  page.on('response', (response) => {
    if (response.request().resourceType() === 'stylesheet')
      styles.push({ status: response.status(), type: response.headers()['content-type'] })
  })
  page.on('websocket', (socket) => {
    if (socket.url().includes('/socket.io/')) websockets++
  })
  async function api(path, method = 'GET', body) {
    return page.evaluate(
      async ({ path, method, body }) => {
        const session = method === 'GET' ? null : await (await fetch('/api/session')).json()
        const response = await fetch(path, {
          method,
          headers: {
            'Content-Type': 'application/json',
            ...(session ? { 'X-CSRF-Token': session.csrf_token } : {}),
          },
          body: body === undefined ? undefined : JSON.stringify(body),
        })
        return { status: response.status, body: await response.json() }
      },
      { path, method, body },
    )
  }
  let facts = saved
  if (!saved) {
    const password = readFileSync(loginFile, 'utf8').split('\n')[1].split('：')[1]
    await page.goto('/login/')
    await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible()
    await expect(page.locator('html')).toHaveCSS('background-color', 'rgb(243, 246, 251)')
    await expect(page.locator('.button-primary')).toHaveCSS('background-color', 'rgb(36, 79, 185)')
    await page.getByLabel('用户名', { exact: true }).fill('MASTER')
    await page.getByLabel('密码', { exact: true }).fill(password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await expect(page.getByRole('heading', { name: '对局大厅', exact: true })).toBeVisible()
    await page.getByLabel('自动刷新并进入已开局对局（5 秒）').uncheck()
    const dictionary = await api('/api/dict', 'POST', { dictname: '本地启动持久性测试' })
    assert.equal(dictionary.status, 201)
    const dictId = dictionary.body.dict_id
    assert.ok(Number.isInteger(dictId))
    assert.equal(
      (await api(`/api/dict/${dictId}/word`, 'POST', { english: 'apple', chinese: '苹果' })).status,
      201,
    )
    const requestId = randomUUID()
    const created = await api('/api/game/create', 'POST', {
      dict_id: dictId,
      request_id: requestId,
    })
    assert.equal(created.status, 201)
    facts = { dictId, requestId, receipt: created.body, gameId: created.body.game_id }
    assert.ok(Number.isInteger(facts.gameId))
    writeFileSync(`${directory}/facts.json`, JSON.stringify(facts), { mode: 0o600 })
    await context.storageState({ path: `${directory}/cookies.json` })
    chmodSync(`${directory}/cookies.json`, 0o600)
  } else {
    await page.goto(`/game/${facts.gameId}/`)
    const session = (await api('/api/session')).body
    assert.equal(
      session.authenticated,
      true,
      'original Cookie must survive application and MySQL restart',
    )
    assert.equal(session.user.username, 'MASTER')
    const words = await api(`/api/dict/${facts.dictId}/words`)
    assert.equal(words.status, 200)
    assert.equal(words.body.pagination.total, 1)
    assert.equal(words.body.words[0].english, 'apple')
    const replay = await api('/api/game/create', 'POST', {
      dict_id: facts.dictId,
      request_id: facts.requestId,
    })
    assert.equal(replay.status, 201)
    assert.deepEqual(replay.body, facts.receipt)
  }
  await page.goto(`/game/${facts.gameId}/`)
  await expect(page.getByText('实时连接已订阅', { exact: false })).toBeVisible()
  await expect.poll(() => websockets).toBeGreaterThan(0)
  await expect(page.locator('nav .user-name')).toHaveCSS('color', 'rgb(128, 128, 128)')
  await expect(page.locator('.site-header')).toHaveCSS('display', 'flex')
  assert.ok(styles.length > 0)
  for (const style of styles) {
    assert.equal(style.status, 200)
    assert.match(style.type, /^text\/css/)
  }
  const cookies = await context.cookies()
  assert.ok(cookies.some((cookie) => /^wm_local_[0-9a-f]{16}_session$/.test(cookie.name)))
  assert.ok(!cookies.some((cookie) => cookie.name === 'wm_session' || cookie.name === 'wm_csrf'))
  console.log(
    `${phase}: real CSS, login/session, dictionary, command receipt and WebSocket subscription passed`,
  )
  await context.close()
} finally {
  await browser.close()
}
