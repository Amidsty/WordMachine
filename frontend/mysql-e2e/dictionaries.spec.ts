import { readFile } from 'node:fs/promises'
import type { Page } from '@playwright/test'
import { api, expect, login, rejected, test } from './support'

async function rename(page: Page, name: string) {
  await page.getByRole('button', { name: '重命名词典', exact: true }).click()
  await page.getByLabel('词典名称', { exact: true }).fill(name)
  await page.getByRole('button', { name: '保存词典', exact: true }).click()
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
}
async function addWord(page: Page, english: string, chinese: string) {
  await page.getByRole('button', { name: '新增单词', exact: true }).click()
  await page.getByLabel('英文', { exact: true }).fill(english)
  await page.getByLabel('中文', { exact: true }).fill(chinese)
  await page.getByRole('button', { name: '保存单词', exact: true }).click()
  await expect(page.getByRole('cell', { name: english, exact: true })).toBeVisible()
}
async function deleteDictionary(page: Page, name: string) {
  await page.getByRole('link', { name: '返回词典列表', exact: true }).click()
  const row = page.getByRole('row').filter({ has: page.getByRole('link', { name, exact: true }) })
  await row.getByRole('button', { name: '删除词典', exact: true }).click()
  await page.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(row).toHaveCount(0)
}
async function cannotMaintain(page: Page, dictId: number, wordId: number) {
  const forged = { uid: 3, ownerid: 2, type: 'root' }
  for (const [method, path, body] of [
    ['PUT', `/api/dict/${dictId}`, { dictname: 'forged' }],
    ['DELETE', `/api/dict/${dictId}`, forged],
    ['POST', `/api/dict/${dictId}/word`, { english: 'forged', chinese: '伪造', ...forged }],
    ['POST', `/api/dict/${dictId}/import-csv`, { csv: 'forged,伪造', ...forged }],
    ['PUT', `/api/word/${wordId}`, { english: 'forged', chinese: '伪造', ...forged }],
    ['DELETE', `/api/word/${wordId}`, forged],
  ] as const)
    await rejected(page, path, method, body, 403, 'forbidden')
}

test('owner, reader, root and anonymous dictionary rights, complete CRUD and atomic CSV work against MySQL', async ({
  newActor,
}) => {
  const owner = await newActor()
  const reader = await newActor()
  const admin = await newActor()
  const anonymous = await newActor()
  await login(owner, 'user1')
  await login(reader, 'user2')
  await login(admin, 'user3')
  await anonymous.goto('/login/')
  for (const path of ['/api/dicts', '/api/dict/1', '/api/dict/1/words', '/api/dict/1/export-csv'])
    await rejected(anonymous, path, 'GET', undefined, 401, 'unauthenticated')
  await rejected(anonymous, '/api/dict', 'POST', { dictname: 'anonymous' }, 401, 'unauthenticated')
  await owner.goto('/admin/dicts/1/')
  await expect(owner.getByText('只读词典：', { exact: false })).toBeVisible()
  await cannotMaintain(owner, 1, 11)
  await rejected(
    owner,
    '/api/dict',
    'POST',
    { dictname: 'forged', ownerid: 2, uid: 3, type: 'root' },
    400,
    'invalid_parameters',
  )
  await owner.getByRole('link', { name: '返回词典列表', exact: true }).click()
  let creates = 0
  await owner.route('**/api/dict', async (route) => {
    creates++
    await route.continue({
      headers: {
        ...route.request().headers(),
        ...(creates === 1 ? { 'x-csrf-token': 'expired-test-token' } : {}),
      },
      postData: JSON.stringify({
        ...route.request().postDataJSON(),
      }),
    })
  })
  await owner.getByRole('button', { name: '新建词典', exact: true }).click()
  await owner.getByLabel('词典名称', { exact: true }).fill('权限词典 %_!')
  await owner.getByRole('button', { name: '保存词典', exact: true }).click()
  await expect(owner.getByRole('alert')).toContainText('安全校验已过期')
  expect(creates).toBe(1) // Real 403, refresh CSRF for NEXT action; never auto-replay a write.
  expect((await api(owner, '/api/dicts')).body.dicts).toHaveLength(1)
  await owner.getByRole('button', { name: '保存词典', exact: true }).click()
  await expect(owner).toHaveURL(/\/admin\/dicts\/\d+\/$/)
  expect(creates).toBe(2)
  const id = Number(new URL(owner.url()).pathname.match(/dicts\/(\d+)/)![1])
  expect((await api(owner, `/api/dict/${id}`)).body.dict.ownerid).toBe(1)
  await owner.getByLabel('CSV 文本', { exact: true }).fill('draft,草稿')
  await rename(owner, '维护词典 %_!')
  await expect(owner.getByLabel('CSV 文本', { exact: true })).toHaveValue('draft,草稿')
  const malicious = '<img src=x onerror="window.injected=1">'
  await addWord(owner, malicious, '文本而非 HTML')
  await expect(owner.locator('main img')).toHaveCount(0)
  await owner.getByRole('button', { name: '编辑单词', exact: true }).click()
  await owner.getByLabel('英文', { exact: true }).fill('edited word')
  await owner.getByLabel('中文', { exact: true }).fill('已编辑')
  await owner.getByRole('button', { name: '保存单词', exact: true }).click()
  await expect(owner.getByRole('cell', { name: 'edited word', exact: true })).toBeVisible()
  const wordId = (await api(owner, `/api/dict/${id}/words`)).body.words[0].id as number
  await reader.goto(`/admin/dicts/${id}/`)
  await expect(reader.getByText('只读词典：', { exact: false })).toBeVisible()
  await expect(reader.getByRole('button', { name: '新增单词', exact: true })).toHaveCount(0)
  await expect(reader.getByLabel('CSV 文本', { exact: true })).toHaveCount(0)
  await cannotMaintain(reader, id, wordId)
  await expect(reader.getByRole('cell', { name: 'edited word', exact: true })).toBeVisible()

  let imports = 0
  owner.on('request', (request) => {
    if (new URL(request.url()).pathname === `/api/dict/${id}/import-csv`) imports++
  })
  await owner.getByLabel('读取 CSV 文件', { exact: false }).setInputFiles({
    name: 'invalid.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from([0xff, 0xfe]),
  })
  await expect(owner.getByRole('alert')).toContainText('有效 UTF-8')
  await owner.getByLabel('读取 CSV 文件', { exact: false }).setInputFiles({
    name: 'oversized.csv',
    mimeType: 'text/csv',
    buffer: Buffer.alloc(512 * 1024 + 1, 'a'),
  })
  await expect(owner.getByRole('alert')).toContainText('超过服务器大小限制')
  expect(imports).toBe(0)
  const invalidCsv = 'must-not-exist,不应存在\nbroken'
  await owner.getByLabel('CSV 文本', { exact: true }).fill(invalidCsv)
  await owner.getByRole('button', { name: '导入 CSV', exact: true }).click()
  await expect(owner.getByLabel('CSV 行错误')).toContainText('第 2 行')
  await expect(owner.getByLabel('CSV 文本', { exact: true })).toHaveValue(invalidCsv)
  expect((await api(owner, `/api/dict/${id}/words`)).body.pagination.total).toBe(1)
  const rows = Array.from(
    { length: 21 },
    (_, index) => `word${String(index).padStart(2, '0')},词${index}`,
  )
  const content = rows.join('\r\n') + '\r\n"say ""hi"", please","第一行\n第二行"\r\n'
  await owner.getByLabel('读取 CSV 文件', { exact: false }).setInputFiles({
    name: 'words.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('\ufeff' + content),
  })
  await expect(owner.getByLabel('CSV 文本', { exact: true })).toHaveValue(
    content.replaceAll('\r\n', '\n'),
  )
  await owner.getByRole('button', { name: '导入 CSV', exact: true }).click()
  await expect(owner.getByText('成功导入 22 个单词。', { exact: true })).toBeVisible()
  await expect(owner.getByLabel('CSV 文本', { exact: true })).toHaveValue('')
  expect(imports).toBe(2)
  const pagination = owner.getByRole('navigation', { name: '单词分页', exact: true })
  await expect(pagination).toContainText('共 23 条')
  await pagination.getByRole('button', { name: '下一页', exact: true }).click()
  await expect(owner.getByRole('cell', { name: 'say "hi", please', exact: true })).toBeVisible()
  await owner.getByLabel('搜索英文或中文', { exact: true }).fill('word00')
  await owner.getByRole('button', { name: '搜索单词', exact: true }).click()
  await expect(pagination).toContainText('共 1 条')
  // Export is complete even when the UI is filtered and the data spans multiple pages.
  for (const page of [owner, reader]) {
    const download = page.waitForEvent('download')
    await page.getByRole('button', { name: '导出全部 CSV', exact: true }).click()
    const file = await download
    expect(file.suggestedFilename()).toBe('维护词典 %_!.csv')
    expect(await readFile((await file.path())!, 'utf8')).toBe('edited word,已编辑\r\n' + content)
  }
  await owner.getByLabel('搜索英文或中文', { exact: true }).fill('edited word')
  await owner.getByRole('button', { name: '搜索单词', exact: true }).click()
  await owner.getByRole('button', { name: '删除单词', exact: true }).click()
  await owner.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(owner.getByRole('cell', { name: 'edited word', exact: true })).toHaveCount(0)
  await rejected(
    owner,
    `/api/word/${wordId}`,
    'PUT',
    { english: 'revive', chinese: '复活' },
    404,
    'not_found',
  )

  // Root manages both another user's dictionary and the unowned legacy system dictionary.
  await admin.goto(`/admin/dicts/${id}/`)
  await rename(admin, '管理员维护 %_!')
  const rootRow = admin
    .getByRole('row')
    .filter({ has: admin.getByRole('cell', { name: 'word00', exact: true }) })
  await rootRow.getByRole('button', { name: '编辑单词', exact: true }).click()
  await admin.getByLabel('中文', { exact: true }).fill('管理员修改')
  await admin.getByRole('button', { name: '保存单词', exact: true }).click()
  await expect(rootRow).toContainText('管理员修改')
  await admin.goto('/admin/dicts/1/')
  await rename(admin, '管理员系统词典')
  await addWord(admin, 'root-created', '管理员新增')
  const added = admin
    .getByRole('row')
    .filter({ has: admin.getByRole('cell', { name: 'root-created', exact: true }) })
  await added.getByRole('button', { name: '删除单词', exact: true }).click()
  await admin.getByRole('button', { name: '确认删除', exact: true }).click()
  await expect(added).toHaveCount(0)
  await admin.getByLabel('CSV 文本', { exact: true }).fill('root-imported,管理员导入')
  await admin.getByRole('button', { name: '导入 CSV', exact: true }).click()
  await expect(admin.getByText('成功导入 1 个单词。', { exact: true })).toBeVisible()
  await deleteDictionary(admin, '管理员系统词典')
  await owner.goto(`/admin/dicts/${id}/`)
  await expect(owner.getByRole('heading', { name: '管理员维护 %_!', exact: true })).toBeVisible()
  await owner.getByRole('link', { name: '返回词典列表', exact: true }).click()
  await owner.getByLabel('按词典名称搜索', { exact: true }).fill('%_!')
  await owner.getByRole('button', { name: '搜索词典', exact: true }).click()
  await expect(owner.getByRole('navigation', { name: '词典分页', exact: true })).toContainText(
    '共 1 条',
  )
  await owner.getByRole('link', { name: '管理员维护 %_!', exact: true }).click()
  await deleteDictionary(owner, '管理员维护 %_!')
  await reader.reload()
  await expect(reader.getByRole('alert')).toContainText('记录不存在或已删除')
  await expect(reader.getByRole('button', { name: '导出全部 CSV', exact: true })).toHaveCount(0)
  for (const dictId of [1, id]) {
    await rejected(admin, `/api/dict/${dictId}`, 'GET', undefined, 404, 'not_found')
    await rejected(admin, `/api/dict/${dictId}/export-csv`, 'GET', undefined, 404, 'not_found')
    await rejected(
      admin,
      `/api/dict/${dictId}/word`,
      'POST',
      { english: 'revive', chinese: '复活' },
      404,
      'not_found',
    )
  }
})
