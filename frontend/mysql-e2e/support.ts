import { expect, test as base, type BrowserContext, type Page } from '@playwright/test'

// Every actor has an independent cookie jar. All requests reach the actual server.
export const test = base.extend<{ newActor: () => Promise<Page> }>({
  newActor: async ({ browser, baseURL }, use) => {
    const contexts: BrowserContext[] = []
    try {
      await use(async () => {
        const context = await browser.newContext({ baseURL })
        contexts.push(context)
        return context.newPage()
      })
    } finally {
      await Promise.all(contexts.map((context) => context.close()))
    }
  },
})
export { expect }

export async function enterCredentials(page: Page, username: string, password: string) {
  await page.goto('/login/')
  await page.getByLabel('用户名', { exact: true }).fill(username)
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
}

export async function login(page: Page, username: string, password = 'test-password') {
  await enterCredentials(page, username, password)
  await expect(page.getByRole('heading', { name: '对局大厅', exact: true })).toBeVisible()
  await page.getByLabel('自动刷新并进入已开局对局（5 秒）').uncheck()
}

export async function logout(page: Page) {
  await page.getByRole('button', { name: '登出', exact: true }).click()
  await expect(page).toHaveURL(/\/login\/$/)
}

// Negative permission probes bypass hidden controls, not server auth or CSRF.
// Execute fetch inside Chromium, so same-origin Cookie/Origin semantics remain real.
export async function api(
  page: Page,
  path: string,
  method = 'GET',
  body?: unknown,
  csrf?: string | null,
) {
  return page.evaluate(
    async ({ path, method, body, csrf }) => {
      if (method !== 'GET' && csrf === undefined) {
        const state = await (await fetch('/api/session')).json()
        csrf = state.csrf_token
      }
      const response = await fetch(path, {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      return { status: response.status, body: await response.json() }
    },
    { path, method, body, csrf },
  )
}

export async function rejected(
  page: Page,
  path: string,
  method: string,
  body: unknown,
  status: number,
  code: string,
  csrf?: string | null,
) {
  const result = await api(page, path, method, body, csrf)
  expect(result.status, `${method} ${path}`).toBe(status)
  expect(result.body).toMatchObject({ success: false, code })
}
