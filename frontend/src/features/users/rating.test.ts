import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createServices, servicesKey } from '../../app/services'
import { createApiClient } from '../../shared/api/client'
import RatingDialog from './RatingDialog.vue'
import type { ManagedUser, RatingIntent, RatingReview } from './service'

const wrappers: VueWrapper[] = []
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
})
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.useRealTimers()
  vi.restoreAllMocks()
})
const user: ManagedUser = {
  id: 1,
  username: 'target',
  introduction: '',
  rating: 1500,
  type: 'normal',
  admin_level: 0,
  deleted: false,
}
const session = {
  success: true as const,
  authenticated: true as const,
  user: { ...user, id: 3, type: 'root' as const, admin_level: 5 },
  csrf_token: 'csrf',
}
function button(wrapper: VueWrapper, label: string) {
  const found = wrapper.findAll('button').find((entry) => entry.text() === label)
  if (!found) throw new Error(`Missing button: ${label}`)
  return found
}
function receipt(body: RatingIntent) {
  return Response.json({
    success: true,
    request_id: body.request_id,
    user_id: 1,
    rating_before: body.expected_rating,
    rating_after: body.new_rating,
    delta: body.new_rating - body.expected_rating,
    rating_event_id: '9007199254740994',
  })
}
async function dialog(
  options: {
    running?: boolean
    post?: (body: RatingIntent, signal?: AbortSignal) => Promise<Response>
  } = {},
) {
  const review: RatingReview = {
    success: true,
    user_id: 1,
    rating: 1500,
    rating_event_id: '9007199254740993',
    running_game: options.running ?? false,
    events: [
      {
        id: '9007199254740993',
        kind: 'manual',
        sequence: 1,
        rating_before: 1400,
        rating_after: 1500,
        delta: 100,
        game_id: null,
        actor_id: 3,
        reason: '<img src=x onerror=alert(1)>',
        recorded_at: '2026-01-01T00:00:00Z',
      },
    ],
  }
  const writes: Array<RatingIntent & { current_password: string }> = []
  const fetcher = vi.fn<typeof fetch>(async (_url, init) => {
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body)) as RatingIntent & { current_password: string }
      writes.push(body)
      expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf')
      return options.post ? options.post(body, init.signal ?? undefined) : receipt(body)
    }
    return Response.json(review)
  })
  const client = createApiClient({ fetcher, origin: 'http://localhost' })
  client.acceptSession(session)
  const services = createServices(client)
  const wrapper = mount(RatingDialog, {
    props: { user },
    attachTo: document.body,
    global: { provide: { [servicesKey as symbol]: services } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, writes, fetcher, services, review }
}
async function prepare(wrapper: VueWrapper, amount = '1700') {
  await wrapper.get('#rating-amount').setValue(amount)
  await wrapper.get('#rating-reason').setValue('approved')
  await wrapper.get('form').trigger('submit')
}
async function submit(wrapper: VueWrapper) {
  await wrapper.get('#rating-password').setValue('my-current-password')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

describe('manual rating review and fixed intent', () => {
  it('requires a separate confirmation, sends the exact BIGINT review, and escapes reasons', async () => {
    const { wrapper, writes } = await dialog()
    expect(wrapper.text()).toContain('人工调整')
    expect(wrapper.find('img').exists()).toBe(false)
    await prepare(wrapper)
    expect(writes).toHaveLength(0)
    expect(wrapper.text()).toContain('1500 → 1700')
    await submit(wrapper)
    expect(writes).toHaveLength(1)
    expect(writes[0]).toMatchObject({
      expected_rating: 1500,
      expected_event_id: '9007199254740993',
      new_rating: 1700,
      reason: 'approved',
      current_password: 'my-current-password',
    })
    expect(writes[0]?.request_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
  it.each(['1.5', '2147483648', '-2147483649', '1e3'])(
    'rejects invalid integer %s before preparing a request',
    async (value) => {
      const { wrapper, writes } = await dialog()
      await prepare(wrapper, value)
      expect(wrapper.text()).toContain('必须是')
      expect(wrapper.find('#rating-password').exists()).toBe(false)
      expect(writes).toHaveLength(0)
    },
  )
  it('blocks a running-game review even if the submit handler is triggered directly', async () => {
    const { wrapper, writes } = await dialog({ running: true })
    await prepare(wrapper)
    expect(wrapper.text()).toContain('该用户正在进行对局')
    expect(wrapper.find('#rating-password').exists()).toBe(false)
    expect(writes).toHaveLength(0)
  })
  it('does not resend a lost confirmation; a manual retry retains the complete intent', async () => {
    let calls = 0
    const { wrapper, writes } = await dialog({
      post: async (body) => {
        if (++calls === 1) throw new TypeError('synthetic lost acknowledgement')
        return receipt(body)
      },
    })
    await prepare(wrapper)
    await submit(wrapper)
    await flushPromises()
    expect(writes).toHaveLength(1)
    expect(wrapper.text()).toContain('未自动重复提交')
    expect(wrapper.find('#rating-amount').exists()).toBe(false)
    expect((wrapper.get('#rating-password').element as HTMLInputElement).value).toBe('')
    expect(button(wrapper, '重试原请求').exists()).toBe(true)
    await submit(wrapper)
    expect(writes).toHaveLength(2)
    expect(writes[1]).toEqual(writes[0])
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
  it('guards double submit while a write is in flight', async () => {
    let resolve!: (response: Response) => void
    const { wrapper, writes } = await dialog({
      post: () =>
        new Promise<Response>((done) => {
          resolve = done
        }),
    })
    await prepare(wrapper)
    await submit(wrapper)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(writes).toHaveLength(1)
    resolve(receipt(writes[0]!))
    await flushPromises()
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
  it('times out without treating abort as rollback or automatically retrying', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const { wrapper, writes } = await dialog({
      post: (_body, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        }),
    })
    await prepare(wrapper)
    await submit(wrapper)
    await vi.advanceTimersByTimeAsync(10000)
    await flushPromises()
    expect(writes).toHaveLength(1)
    expect(wrapper.text()).toContain('不代表回滚')
    expect(button(wrapper, '重试原请求').attributes('disabled')).toBeUndefined()
    expect(wrapper.emitted('saved')).toBeUndefined()
  })
  it('requires explicit rereview after a stale balance and generates a new intent only on preparation', async () => {
    const { wrapper, writes, review } = await dialog({
      post: async () =>
        Response.json({ success: false, code: 'stale_rating', message: 'stale' }, { status: 409 }),
    })
    await prepare(wrapper)
    await submit(wrapper)
    expect(wrapper.text()).toContain('Rating 或流水版本已变化')
    review.rating = 1800
    review.rating_event_id = '9007199254740995'
    await button(wrapper, '放弃原请求并重新审查（不撤销已提交结果）').trigger('click')
    await flushPromises()
    expect(writes).toHaveLength(1)
    expect((wrapper.get('#rating-amount').element as HTMLInputElement).value).toBe('1800')
    await prepare(wrapper, '1900')
    await submit(wrapper)
    expect(writes[1]?.request_id).not.toBe(writes[0]?.request_id)
    expect(writes[1]?.expected_event_id).toBe('9007199254740995')
  })
  it('does not accept an old-account success or resend its intent as a new actor', async () => {
    let resolve!: (response: Response) => void
    const { wrapper, writes, services } = await dialog({
      post: () =>
        new Promise<Response>((done) => {
          resolve = done
        }),
    })
    await prepare(wrapper)
    await submit(wrapper)
    services.client.acceptSession({ ...session, user: { ...session.user, id: 4 } })
    resolve(receipt(writes[0]!))
    await flushPromises()
    expect(wrapper.emitted('saved')).toBeUndefined()
    await submit(wrapper)
    expect(writes).toHaveLength(1)
    expect(wrapper.text()).toContain('登录账号已变化')
  })
  it('cancel before confirmation sends no write', async () => {
    const { wrapper, writes } = await dialog()
    await prepare(wrapper)
    await wrapper.get('button[aria-label="关闭对话框"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(writes).toHaveLength(0)
  })
})
