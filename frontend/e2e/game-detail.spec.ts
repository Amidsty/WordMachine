import { expect, test, type Page } from '@playwright/test'
import { createGameApi, gameState } from '../testing/gameApi'
import { backendOrigin } from './servers'

async function mockApi(page: Page, authenticated = true) {
  const api = createGameApi(authenticated)
  const requests: { path: string; method: string }[] = []
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      requests.push({ path, method: request.method() })
      const result = api.handle(request.url(), request.method())
      await route.fulfill({ status: result.status, json: result.body })
    },
  )
  return { api, requests }
}

test('built history is reached by Vue navigation and shows stored scores, text and local pages (mock API)', async ({
  page,
}) => {
  const { api, requests } = await mockApi(page)
  api.games.set(4, gameState(4, 1, 25))
  const documents: string[] = []
  page.on('request', (request) => {
    if (request.resourceType() === 'document') documents.push(request.url())
  })
  await page.goto(`${backendOrigin}/login/`)
  await page.getByRole('link', { name: '主页', exact: true }).click()
  await page.getByRole('button', { name: '已结束', exact: true }).click()
  await page.getByRole('link', { name: '查看详情', exact: true }).click()
  await expect(page).toHaveURL(`${backendOrigin}/game/4/detail/`)
  await expect(page.getByRole('heading', { name: '对局详情 #4' })).toBeVisible()
  expect(documents).toEqual([`${backendOrigin}/login/`])
  await expect(page.getByText('题目来自创建时快照', { exact: false })).toBeVisible()
  await expect(page.locator('main img, main svg, main script, [onclick]')).toHaveCount(0)
  const scores = page.getByRole('table', { name: '本局作答与评分' })
  await expect(scores).toContainText('1511.1')
  await expect(scores).not.toContainText('1511.1234567890124')
  await expect(scores).toContainText('1507')
  await expect(scores).not.toContainText('1707')
  await expect(scores).toContainText('无答题记录')
  const answers = page.getByRole('table', { name: '已接受的答题记录' })
  await expect(answers.locator('tbody tr')).toHaveCount(20)
  const count = requests.filter((request) => request.path === '/api/game/4').length
  await page.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(answers.locator('tbody tr')).toHaveCount(5)
  await expect(answers.locator('tbody tr').first().locator('td').first()).toHaveText('21')
  expect(requests.filter((request) => request.path === '/api/game/4')).toHaveLength(count)
  await expect(page.locator('main')).not.toContainText('standard-25')
  expect(requests.every((request) => request.method === 'GET')).toBe(true)
})

test('history polling reconciles an early finish, rejects older state, retries reads and stops on leave (mock API)', async ({
  page,
}) => {
  const { api, requests } = await mockApi(page)
  await page.clock.install()
  await page.goto('/game/7/detail/')
  await expect(page.getByRole('link', { name: '进入对局 / 观战' })).toHaveAttribute(
    'href',
    '/game/7/',
  )
  await expect(page.getByRole('table', { name: '本局作答与评分' })).toContainText('尚未结算')
  const count = () => requests.filter((request) => request.path === '/api/game/7').length
  api.games.set(7, { ...gameState(7), version: 6 })
  await page.clock.fastForward(5000)
  await expect.poll(count).toBe(2)
  await expect(page.getByRole('link', { name: '进入对局 / 观战' })).toHaveCount(0)
  await expect(page.getByRole('table', { name: '本局作答与评分' })).toContainText('+7')
  await expect(page.locator('main')).not.toContainText('standard-2')
  await page.getByRole('checkbox', { name: '自动刷新（5 秒）' }).uncheck()
  await page.clock.fastForward(15000)
  expect(count()).toBe(2)
  api.games.set(7, gameState(7, 0))
  await page.getByRole('checkbox', { name: '自动刷新（5 秒）' }).check()
  await expect(page.getByRole('alert')).toContainText('未覆盖已读取记录')
  await expect(page.getByRole('table', { name: '本局作答与评分' })).toContainText('+7')
  api.state.failure = { status: 503, code: 'database_unavailable' }
  await page.getByRole('button', { name: '刷新详情', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('服务暂时不可用')
  await expect(page.getByRole('table')).toHaveCount(0)
  api.state.failure = null
  api.games.set(7, { ...gameState(7), version: 6 })
  await page.getByRole('button', { name: '刷新详情', exact: true }).click()
  await expect(page.getByRole('table', { name: '本局作答与评分' })).toBeVisible()
  await page.getByRole('link', { name: '排行榜', exact: true }).click()
  await expect(page.getByRole('heading', { name: '排行榜', exact: true })).toBeVisible()
  const left = count()
  await page.clock.fastForward(15000)
  expect(count()).toBe(left)
  expect(requests.every((request) => request.method === 'GET')).toBe(true)
})

test('history preserves login targets, Vite deep-link refresh, missing fields and rejection of leaked future English (mock API)', async ({
  page,
}) => {
  const { api, requests } = await mockApi(page, false)
  const guarded = await page.request.get(`${backendOrigin}/game/4/detail/`, { maxRedirects: 0 })
  expect(guarded.status()).toBe(302)
  const redirect = new URL(guarded.headers().location!, backendOrigin)
  expect(redirect.pathname).toBe('/login/')
  expect(redirect.searchParams.get('next')).toBe('/game/4/detail/')
  await page.goto('/game/4/detail/')
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('next')).toBe('/game/4/detail/')
  expect(requests.some((request) => request.path === '/api/game/4')).toBe(false)
  api.lobby.state.authenticated = true
  const legacy = gameState()
  legacy.question_source = 'legacy_live'
  legacy.result[0] = { uid: 1, word_id: 11, answer: null, perf: null }
  api.games.set(4, legacy)
  await page.goto('/game/4/detail/')
  await page.reload()
  await expect(page.getByRole('heading', { name: '对局详情 #4' })).toBeVisible()
  await expect(page.locator('main')).toContainText('可能与原题不同')
  await expect(page.getByRole('table', { name: '已接受的答题记录' })).toContainText('未记录')
  api.games.get(4)!.words[2]!.english = 'future-private-answer'
  await page.getByRole('button', { name: '刷新详情', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('响应格式不符合约定')
  await expect(page.locator('main')).not.toContainText('future-private-answer')
  await expect(page.getByRole('table')).toHaveCount(0)
  api.lobby.state.authenticated = false
  await page.getByRole('button', { name: '刷新详情', exact: true }).click()
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('next')).toBe('/game/4/detail/')
})
