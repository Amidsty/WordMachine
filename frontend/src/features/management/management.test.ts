import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import App from '../../app/App.vue'
import { createServices, servicesKey } from '../../app/services'
import { createAppRouter } from '../../app/router'
import { createApiClient } from '../../shared/api/client'
import { createManagementApi } from '../../../testing/managementApi'

const wrappers: VueWrapper[] = []
beforeEach(() => {
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
})
afterEach(() => wrappers.splice(0).forEach((wrapper) => wrapper.unmount()))

async function page(
  path: string,
  root = false,
  setup?: (api: ReturnType<typeof createManagementApi>) => void,
) {
  const api = createManagementApi(root)
  setup?.(api)
  const fetcher = vi.fn<typeof fetch>(async (url, options) => {
    const response = api.handle(
      String(url),
      options?.method ?? 'GET',
      options?.body ? JSON.parse(String(options.body)) : {},
      new Headers(options?.headers).get('X-CSRF-Token'),
    )
    return Response.json(response.body, { status: response.status })
  })
  const services = createServices(createApiClient({ fetcher, origin: 'http://localhost' }))
  const router = createAppRouter(services, createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(App, {
    attachTo: document.body,
    global: { plugins: [router], provide: { [servicesKey as symbol]: services } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return { api, services, wrapper, router, fetcher }
}

function button(wrapper: VueWrapper, label: string) {
  const found = wrapper.findAll('button').find((button) => button.text() === label)
  if (!found) throw Error(`Button not found: ${label}`)
  return found
}

describe('management pages', () => {
  it('denies normal-user navigation to user management without requesting its data', async () => {
    const { wrapper, router, fetcher } = await page('/admin/users/')
    expect(router.currentRoute.value.name).toBe('management')
    expect(wrapper.text()).toContain('只有管理员')
    expect(fetcher.mock.calls.some(([url]) => String(url).startsWith('/api/admin/users'))).toBe(
      false,
    )
    expect(wrapper.find('a[href="/admin/users/"]').exists()).toBe(false)
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('[onclick]').exists()).toBe(false)
  })

  it('paginates on the server and exposes only owner mutation controls', async () => {
    const { wrapper, fetcher } = await page('/admin/', false, (api) => {
      for (let id = 4; id <= 22; id++)
        api.dicts.push({
          id,
          dictname: `dictionary-${id}`,
          ownerid: 2,
          multiplier: '1.00',
          config_version: 0,
        })
    })
    expect(wrapper.findAll('tbody tr')).toHaveLength(20)
    await button(wrapper, '下一页').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.findAll('button').filter((button) => button.text() === '删除词典')).toHaveLength(
      1,
    )
    expect(fetcher.mock.calls.some(([url]) => String(url).includes('page=2&per_page=20'))).toBe(
      true,
    )
    await wrapper.get('#dict-search').setValue('System')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.findAll('button').some((button) => button.text() === '删除词典')).toBe(false)
  })

  it('creates dictionaries using the shared modal and navigates to the new detail', async () => {
    const { wrapper, api, router } = await page('/admin/')
    await button(wrapper, '新建词典').trigger('click')
    await wrapper.get('#dict-name').setValue('new dictionary')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    await vi.dynamicImportSettled()
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/admin/dicts/4/')
    expect(api.writes[0]?.body).toEqual({ dictname: 'new dictionary', multiplier: '1.00' })
    expect(wrapper.text()).toContain('新增单词')
  })

  it('saves a personal multiplier with its reviewed version without affecting CSV drafts', async () => {
    const { wrapper, api } = await page('/admin/dicts/2/')
    await wrapper.get('#csv-content').setValue('keep,draft')
    await button(wrapper, '修改倍率').trigger('click')
    await wrapper.get('#dict-multiplier').setValue('1.25')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(api.writes[0]).toEqual({
      path: '/api/dict/2/multiplier',
      method: 'PUT',
      body: { multiplier: '1.25', expected_version: 0, reason: '' },
    })
    expect(wrapper.text()).toContain('×1.25')
    expect((wrapper.get('#csv-content').element as HTMLTextAreaElement).value).toBe('keep,draft')
  })

  it('retains the multiplier draft after stale-version rejection and never retries automatically', async () => {
    const { wrapper, api } = await page('/admin/dicts/2/')
    await button(wrapper, '修改倍率').trigger('click')
    await wrapper.get('#dict-multiplier').setValue('1.001')
    await wrapper.get('dialog form').trigger('submit')
    expect(api.writes).toHaveLength(0)
    await wrapper.get('#dict-multiplier').setValue('1.25')
    api.dicts[1]!.config_version++
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('dialog').text()).toContain('词典配置已变化')
    expect((wrapper.get('#dict-multiplier').element as HTMLInputElement).value).toBe('1.25')
    expect(api.writes).toHaveLength(1)
  })

  it('denies system maintenance below level three and requires a reason at level three', async () => {
    const low = await page('/admin/dicts/1/', true, (api) => {
      api.actor.admin_level = 2
    })
    expect(low.wrapper.text()).toContain('只读词典')
    expect(low.wrapper.findAll('button').some((node) => node.text() === '修改倍率')).toBe(false)
    const { wrapper, api } = await page('/admin/dicts/1/', true, (api) => {
      api.actor.admin_level = 3
    })
    await button(wrapper, '修改倍率').trigger('click')
    await wrapper.get('#dict-multiplier').setValue('2.00')
    await wrapper.get('dialog form').trigger('submit')
    expect(api.writes).toHaveLength(0)
    await wrapper.get('#multiplier-reason').setValue('reviewed')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(api.writes).toHaveLength(1)
    expect(wrapper.text()).toContain('×2.00')
  })

  it('renaming preserves the current CSV draft', async () => {
    const { wrapper } = await page('/admin/dicts/2/')
    await wrapper.get('#csv-content').setValue('unfinished,draft')
    await button(wrapper, '重命名词典').trigger('click')
    await wrapper.get('#dict-name').setValue('renamed')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('#dictionary-title').text()).toBe('renamed')
    expect((wrapper.get('#csv-content').element as HTMLTextAreaElement).value).toBe(
      'unfinished,draft',
    )
  })

  it('keeps read-only dictionaries useful without exposing edit or import controls', async () => {
    const { wrapper } = await page('/admin/dicts/1/')
    expect(wrapper.text()).toContain('只读词典')
    expect(wrapper.find('#csv-content').exists()).toBe(false)
    expect(wrapper.findAll('button').some((button) => button.text() === '新增单词')).toBe(false)
    expect(button(wrapper, '导出全部 CSV').exists()).toBe(true)
  })

  it('closes a committed word dialog even if list reconciliation subsequently fails', async () => {
    const { wrapper, api } = await page('/admin/dicts/2/')
    await button(wrapper, '新增单词').trigger('click')
    await wrapper.get('#word-english').setValue('<img src=x>')
    await wrapper.get('#word-chinese').setValue('第一行\n第二行')
    api.state.failWords = true
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('dialog').exists()).toBe(false)
    expect(wrapper.text()).toContain('单词操作已保存')
    expect(wrapper.text()).toContain('服务暂时不可用')
    api.state.failWords = false
    await button(wrapper, '重试单词加载').trigger('click')
    await flushPromises()
    expect(api.writes).toHaveLength(1)
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('<img src=x>')
  })

  it('retains an unsaved dialog and displays API permission failures', async () => {
    const { wrapper, api } = await page('/admin/dicts/2/')
    await button(wrapper, '编辑单词').trigger('click')
    api.state.rejectWrites = true
    await wrapper.get('#word-english').setValue('changed')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('dialog').text()).toContain('没有执行此操作的权限')
    expect((wrapper.get('#word-english').element as HTMLInputElement).value).toBe('changed')
    expect(api.words[0]?.english).toBe('apple')
    // Ported from the legacy management DOM regression: failed writes must re-enable controls.
    expect(wrapper.get('dialog fieldset').attributes('disabled')).toBeUndefined()
    expect(button(wrapper, '保存单词').attributes('disabled')).toBeUndefined()
    expect(button(wrapper, '保存单词').classes()).not.toContain('disabled')
  })

  it('uses server-provided CSV limits for UTF-8 byte preflight', async () => {
    const { wrapper, api } = await page('/admin/dicts/2/', false, (api) => {
      api.csvLimits.max_bytes = 8
    })
    await wrapper.get('#csv-content').setValue('a,苹果')
    await wrapper.get('form.import-form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).not.toContain('CSV 文本超过')
    await wrapper.get('#csv-content').setValue('ab,苹果')
    await wrapper.get('form.import-form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('CSV 文本超过服务器大小限制')
    expect(api.writes).toHaveLength(1)
  })

  it('reports structured CSV errors as text and does not replay the import', async () => {
    const { wrapper, api } = await page('/admin/dicts/2/')
    await wrapper.get('#csv-content').setValue('apple,苹果\nbad')
    await wrapper.get('form.import-form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('第 2 行')
    expect(wrapper.find('script').exists()).toBe(false)
    expect(api.writes).toHaveLength(1)
    expect(api.words).toHaveLength(1)
    expect((wrapper.get('#csv-content').element as HTMLTextAreaElement).value).toContain('bad')
  })

  it('root edits normal profiles, sends only profile fields and renders saved text safely', async () => {
    const { wrapper, api } = await page('/admin/users/', true)
    await wrapper.get('tr[data-user-id="2"] button').trigger('click')
    expect((wrapper.get('#edit-username').element as HTMLInputElement).value).toBe(
      '<script>other</script>',
    )
    await wrapper.get('#edit-username').setValue('renamed-user')
    await wrapper.get('#edit-introduction').setValue('<img src=x>')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(api.writes).toHaveLength(1)
    expect(api.writes[0]).toEqual({
      path: '/api/admin/user/2/update',
      method: 'POST',
      body: { username: 'renamed-user', introduction: '<img src=x>' },
    })
    expect(wrapper.find('dialog').exists()).toBe(false)
    expect(wrapper.text()).toContain('renamed-user')
    expect(wrapper.text()).toContain('目标用户会话已撤销')
    expect(wrapper.find('img').exists()).toBe(false)
  })

  it('does not offer profile edits on another root and retains draft after rejection', async () => {
    const { wrapper, api } = await page('/admin/users/', true, (api) => {
      api.users[0]!.type = 'root'
      api.users[0]!.admin_level = 5
    })
    expect(wrapper.findAll('button').filter((item) => item.text() === '编辑资料')).toHaveLength(2)
    await wrapper.get('tr[data-user-id="2"] button').trigger('click')
    await wrapper.get('#edit-introduction').setValue('unsaved')
    api.state.rejectWrites = true
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('dialog').text()).toContain('没有执行此操作的权限')
    expect((wrapper.get('#edit-introduction').element as HTMLTextAreaElement).value).toBe('unsaved')
    expect(wrapper.get('dialog fieldset').attributes('disabled')).toBeUndefined()
    expect(api.writes).toHaveLength(1)
    expect(api.users[1]!.introduction).not.toBe('unsaved')
  })

  it('offers Rating controls for self and lower levels, never another peer', async () => {
    const { wrapper } = await page('/admin/users/', true, (api) => {
      api.actor.admin_level = 4
      api.users[2]!.admin_level = 4
      api.users[1]!.admin_level = 4
    })
    const controls = (id: number) =>
      wrapper
        .get(`tr[data-user-id="${id}"]`)
        .findAll('button')
        .filter((item) => item.text() === '调整 Rating / 流水')
    expect(controls(3)).toHaveLength(1)
    expect(controls(1)).toHaveLength(1)
    expect(controls(2)).toHaveLength(0)
  })

  it('offers only lower grant levels and submits the reviewed version and reason', async () => {
    const { wrapper, api } = await page('/admin/users/', true, (api) => {
      api.actor.admin_level = 3
      api.users[2]!.admin_level = 3
    })
    const row = wrapper.get('tr[data-user-id="2"]')
    await row
      .findAll('button')
      .find((button) => button.text() === '修改等级')!
      .trigger('click')
    expect(
      wrapper.findAll('#edit-admin-level option').map((option) => option.attributes('value')),
    ).toEqual(['0', '1', '2'])
    await wrapper.get('#edit-admin-level').setValue('2')
    await wrapper.get('#level-reason').setValue('approved')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(api.writes[0]).toEqual({
      path: '/api/admin/user/2/level',
      method: 'POST',
      body: { admin_level: 2, expected_version: 0, reason: 'approved' },
    })
    expect(wrapper.find('dialog').exists()).toBe(false)
    expect(wrapper.text()).toContain('管理员 Lv.2')
  })

  it('retains a stale level decision for review rather than automatically retrying', async () => {
    const { wrapper, api } = await page('/admin/users/', true)
    await wrapper
      .get('tr[data-user-id="2"]')
      .findAll('button')
      .find((button) => button.text() === '修改等级')!
      .trigger('click')
    await wrapper.get('#edit-admin-level').setValue('1')
    await wrapper.get('#level-reason').setValue('reviewed')
    api.users[1]!.admin_version = 1
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('dialog').text()).toContain('用户权限已变化')
    expect(api.writes).toHaveLength(1)
    expect(api.users[1]!.admin_level).toBe(0)
  })

  it('root can edit its own profile but cannot change its own level or ban itself', async () => {
    const { wrapper, api } = await page('/admin/users/', true)
    const rows = wrapper.findAll('tbody tr')
    expect(rows[0]!.text()).toContain('当前账号')
    expect(rows[0]!.findAll('button').map((button) => button.text())).toEqual([
      '编辑资料',
      '调整 Rating / 流水',
    ])
    expect(wrapper.find('script').exists()).toBe(false)
    await button(wrapper, '重置密码').trigger('click')
    await wrapper.get('#reset-password').setValue(' new-secret ')
    await wrapper.get('#reset-confirmation').setValue(' new-secret ')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    expect(api.writes[0]?.path).toBe('/api/admin/user/2/reset-password')
    expect(api.writes[0]?.body).toEqual({ new_password: ' new-secret ' })
    expect(wrapper.find('dialog').exists()).toBe(false)
  })
})
