import { expect, test, type Page } from '@playwright/test'
import { createManagementApi } from '../testing/managementApi'
import { backendOrigin } from './servers'

// UI/browser coverage with a mocked API, not database acceptance.
async function mockApi(page: Page, root = false) {
  const api = createManagementApi(root)
  const requests: string[] = []
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    async (route) => {
      const request = route.request()
      requests.push(new URL(request.url()).pathname)
      const response = api.handle(
        request.url(),
        request.method(),
        request.postData() ? request.postDataJSON() : {},
        request.headers()['x-csrf-token'],
      )
      await route.fulfill({ status: response.status, json: response.body })
    },
  )
  return { api, requests }
}

test('ordinary users get read-only shared dictionaries and cannot enter user management (mock API)', async ({
  page,
}) => {
  const { requests } = await mockApi(page)
  await page.goto('/admin/users/')
  await expect(page).toHaveURL(/\/admin\/\?denied=1$/)
  await expect(page.getByRole('alert')).toContainText('只有管理员')
  expect(requests).not.toContain('/api/admin/users')
  await expect(page.locator('main img')).toHaveCount(0)
  await page.getByRole('link', { name: 'Shared', exact: true }).click()
  await expect(page.getByText('只读词典：')).toBeVisible()
  await expect(page.getByRole('button', { name: '新增单词', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('CSV 文本')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '导出全部 CSV' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Shared', exact: true })).toBeVisible()
})

test('owner dictionary/word CRUD, modal focus, CSV import/export (Flask build, mock API)', async ({
  page,
}) => {
  const { api } = await mockApi(page)
  await page.goto(`${backendOrigin}/login/`)
  await page.getByRole('link', { name: '管理', exact: true }).click()
  await page.getByRole('button', { name: '新建词典', exact: true }).click()
  await page.getByLabel('词典名称', { exact: true }).fill('Browser dictionary')
  await page.getByRole('button', { name: '保存词典' }).click()
  await expect(page).toHaveURL(/\/admin\/dicts\/4\/$/)
  await expect(page.getByRole('heading', { name: 'Browser dictionary', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '重命名词典', exact: true }).click()
  await page.getByLabel('词典名称', { exact: true }).fill('Renamed dictionary')
  await page.getByRole('button', { name: '保存词典' }).click()
  await expect(page.getByRole('heading', { name: 'Renamed dictionary', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '新增单词', exact: true }).click()
  await page.getByLabel('英文', { exact: true }).fill('hello')
  await page.getByLabel('中文', { exact: true }).fill('你好')
  await page.getByRole('button', { name: '保存单词' }).click()
  await expect(page.getByRole('cell', { name: 'hello', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '编辑单词' }).click()
  await page.getByLabel('英文', { exact: true }).fill('hello revised')
  await page.getByRole('button', { name: '保存单词' }).click()
  await expect(page.getByRole('cell', { name: 'hello revised', exact: true })).toBeVisible()
  const remove = page.getByRole('button', { name: '删除单词', exact: true })
  await remove.click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(remove).toBeFocused()
  await page.getByLabel('CSV 文本', { exact: true }).fill('apple,苹果\nbad')
  await page.getByRole('button', { name: '导入 CSV', exact: true }).click()
  await expect(page.getByLabel('CSV 行错误')).toContainText('第 2 行')
  await expect(page.locator('main script')).toHaveCount(0)
  expect(api.words.filter((word) => word.dictid === 4)).toHaveLength(1)
  const content = '"hello, friend","你好\n朋友"\r\n'
  await page.getByLabel('读取 CSV 文件', { exact: false }).setInputFiles({
    name: 'words.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('\ufeff' + content),
  })
  // Native textarea values normalize CRLF; the untouched file model retains its raw CSV.
  await expect(page.getByLabel('CSV 文本', { exact: true })).toHaveValue(
    content.replaceAll('\r\n', '\n'),
  )
  await page.getByRole('button', { name: '导入 CSV', exact: true }).click()
  await expect(page.getByText('成功导入 1 个单词。', { exact: true })).toBeVisible()
  expect(api.writes.filter((write) => write.path.endsWith('/import-csv')).at(-1)?.body).toEqual({
    csv: content,
  })
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出全部 CSV' }).click()
  expect((await download).suggestedFilename()).toBe('dictionary.csv')
  const row = page.getByRole('row').filter({ hasText: 'hello revised' })
  await row.getByRole('button', { name: '删除单词' }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(row).toHaveCount(0)
  await page.getByRole('link', { name: '返回词典列表', exact: true }).click()
  const dictionaryRow = page.getByRole('row').filter({ hasText: 'Renamed dictionary' })
  await dictionaryRow.getByRole('button', { name: '删除词典' }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(dictionaryRow).toHaveCount(0)
})

test('administrator reset, ban and restore (Flask build, mock API)', async ({ page }) => {
  const { api } = await mockApi(page, true)
  await page.goto(`${backendOrigin}/login/`)
  await page.getByRole('link', { name: '管理', exact: true }).click()
  await page.getByRole('link', { name: '用户管理', exact: true }).click()
  const own = page.getByRole('row').filter({ hasText: 'root-user' })
  await expect(own).toContainText('当前账号')
  await expect(own.getByRole('button', { name: '编辑资料', exact: true })).toHaveCount(1)
  await expect(own.getByRole('button', { name: '调整 Rating / 流水', exact: true })).toHaveCount(1)
  await expect(own.getByRole('button')).toHaveCount(2)
  const target = page.getByRole('row').filter({ hasText: '<script>other</script>' })
  await expect(page.locator('main script, main img')).toHaveCount(0)
  await target.getByRole('button', { name: '重置密码', exact: true }).click()
  await page.getByLabel('新密码', { exact: true }).fill(' reset-secret ')
  await page.getByLabel('确认新密码', { exact: true }).fill('wrong')
  await page.getByRole('button', { name: '确认重置密码', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('两次输入的密码不一致')
  expect(api.writes).toHaveLength(0)
  await page.getByLabel('确认新密码', { exact: true }).fill(' reset-secret ')
  await page.getByRole('button', { name: '确认重置密码', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(api.writes[0]?.body).toEqual({ new_password: ' reset-secret ' })
  await target.getByRole('button', { name: '封禁用户', exact: true }).click()
  await page.getByRole('button', { name: '确认封禁用户', exact: true }).click()
  await expect(target).toHaveCount(0)
  await page.getByLabel('包含已封禁用户').check()
  await expect(target).toContainText('已封禁')
  await target.getByRole('button', { name: '恢复用户', exact: true }).click()
  await page.getByRole('button', { name: '确认恢复用户', exact: true }).click()
  await expect(target).toContainText('正常')
  expect(api.writes.map((write) => write.path)).toEqual([
    '/api/admin/user/2/reset-password',
    '/api/admin/user/2/delete',
    '/api/admin/user/2/restore',
  ])
})
