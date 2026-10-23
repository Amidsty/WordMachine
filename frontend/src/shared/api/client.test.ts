import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from './client'
import { sessionSchema, successSchema, type Session } from './contracts'
import { createAuthService } from '../../features/auth/service'

const anonymous: Session = {
  success: true,
  authenticated: false,
  user: null,
  csrf_token: 'anonymous-token',
}
const active: Session = {
  success: true,
  authenticated: true,
  user: { id: 1, username: 'user1', introduction: '', rating: 1500, type: 'normal' },
  csrf_token: 'session-token',
}
const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers })

function fixture(handler: typeof fetch) {
  const fetcher = vi.fn(handler)
  return { fetcher, client: createApiClient({ fetcher, origin: 'https://word.test' }) }
}

describe('session API boundary', () => {
  it('uses same-origin cookies and CSRF without identity fields; passwords remain exact', async () => {
    const { client, fetcher } = fixture(async (path) =>
      json(path === '/api/session' ? anonymous : active),
    )
    await createAuthService(client).login('user1', ' secret ')
    const [path, options] = fetcher.mock.calls[1]!
    expect(path).toBe('/api/login')
    expect(options?.credentials).toBe('same-origin')
    expect(new Headers(options?.headers).get('X-CSRF-Token')).toBe('anonymous-token')
    expect(JSON.parse(String(options?.body))).toEqual({ username: 'user1', password: ' secret ' })
    expect(client.session.value?.user?.id).toBe(1)
  })

  it('deduplicates simultaneous session reads', async () => {
    const { client, fetcher } = fixture(async () => json(anonymous))
    await Promise.all([client.loadSession(), client.loadSession(), client.loadSession()])
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it.each([
    'https://evil.test/api/login',
    '//evil.test/api/login',
    '/outside',
    'https://user:password@word.test/api/login',
  ])('rejects %s before fetching any credentials', async (url) => {
    const { client, fetcher } = fixture(async () => json(anonymous))
    await expect(client.request(url, successSchema, { method: 'POST' })).rejects.toMatchObject({
      code: 'invalid_url',
    })
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('refreshes CSRF without replaying a rejected write', async () => {
    let token = 0
    const { client, fetcher } = fixture(async (path) =>
      path === '/api/session'
        ? json({ ...active, csrf_token: `token-${++token}` })
        : json({ success: false, code: 'csrf_failed', message: 'Expired' }, 403),
    )
    await expect(
      client.request('/api/logout', successSchema, { method: 'POST', body: {} }),
    ).rejects.toMatchObject({ code: 'csrf_failed' })
    expect(fetcher.mock.calls.filter(([path]) => path === '/api/logout')).toHaveLength(1)
    expect(client.session.value?.csrf_token).toBe('token-2')
  })

  it('rejects malformed success responses instead of trusting TypeScript alone', async () => {
    const { client } = fixture(async () =>
      json({ success: true, authenticated: true, user: null, csrf_token: 'token' }),
    )
    await expect(client.loadSession()).rejects.toMatchObject({ code: 'invalid_response' })
    expect(client.session.value).toBeNull()
  })

  it('rejects an anonymous login response', async () => {
    const { client } = fixture(async () => json(anonymous))
    await expect(createAuthService(client).login('user1', 'secret')).rejects.toMatchObject({
      code: 'invalid_response',
    })
  })

  it('does not clear identity for an incorrect current password', async () => {
    const { client } = fixture(async () =>
      json({ success: false, code: 'invalid_credentials', message: 'Wrong password' }, 401),
    )
    client.acceptSession(active)
    await expect(
      client.request('/api/user/1/update', successSchema, { method: 'POST', body: {} }),
    ).rejects.toMatchObject({ code: 'invalid_credentials' })
    expect(client.session.value?.user?.id).toBe(1)
  })

  it('invalidates identity on expiry and exposes Retry-After on throttling', async () => {
    const { client, fetcher } = fixture(async () =>
      json({ success: false, code: 'unauthenticated', message: 'Expired' }, 401),
    )
    client.acceptSession(active)
    await expect(client.request('/api/session', sessionSchema)).rejects.toMatchObject({
      code: 'unauthenticated',
    })
    expect(client.session.value).toBeNull()
    fetcher.mockResolvedValueOnce(
      json({ success: false, code: 'rate_limited', message: 'Too many attempts' }, 429, {
        'Retry-After': '12',
      }),
    )
    await expect(client.request('/api/session', sessionSchema)).rejects.toMatchObject({
      retryAfter: 12,
    })
  })

  it('never restores a stale session GET after logout', async () => {
    let finish!: (response: Response) => void
    const { client } = fixture(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    const pending = client.loadSession()
    client.acceptSession(null)
    finish(json(active))
    await expect(pending).rejects.toMatchObject({ code: 'session_changed' })
    expect(client.session.value).toBeNull()
  })

  it('does not overwrite a newly logged in account with an earlier anonymous GET', async () => {
    let finish!: (response: Response) => void
    const { client } = fixture(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    const pending = client.loadSession()
    client.acceptSession(active)
    finish(json(anonymous))
    expect((await pending).user?.id).toBe(1)
  })

  it('does not sign out a new login because an older request returned 401', async () => {
    let finish!: (response: Response) => void
    const { client } = fixture(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    client.acceptSession(active)
    const pending = client.request('/api/user/1', successSchema)
    client.acceptSession({ ...active, authenticated: true, user: { ...active.user!, id: 2 } })
    finish(json({ success: false, code: 'unauthenticated', message: 'Expired old session' }, 401))
    await expect(pending).rejects.toMatchObject({ code: 'unauthenticated' })
    expect(client.session.value?.user?.id).toBe(2)
  })

  it('refuses a profile write for a different current account', async () => {
    const { client, fetcher } = fixture(async () => json(active))
    client.acceptSession(active)
    await expect(
      createAuthService(client).updateProfile(2, { introduction: 'wrong account' }),
    ).rejects.toMatchObject({ code: 'session_changed' })
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('does not automatically retry transport failures or send aborted writes', async () => {
    const { client, fetcher } = fixture(async () => {
      throw new TypeError('offline')
    })
    client.acceptSession(active)
    await expect(client.request('/api/logout', successSchema, { method: 'POST' })).rejects.toThrow(
      'offline',
    )
    expect(fetcher).toHaveBeenCalledTimes(1)
    const controller = new AbortController()
    controller.abort()
    await expect(
      client.request('/api/logout', successSchema, { method: 'POST', signal: controller.signal }),
    ).rejects.toThrow()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})
