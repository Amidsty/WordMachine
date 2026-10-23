import { readonly, shallowRef } from 'vue'
import type { z } from 'zod'
import { errorSchema, sessionSchema, type Session } from './contracts'

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status = 0,
    public readonly retryAfter: number | null = null,
    public readonly details: unknown = undefined,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
  expectedUserId?: number
}

type ClientOptions = { fetcher?: typeof fetch; origin?: string }

export function createApiClient(options: ClientOptions = {}) {
  const fetcher = options.fetcher ?? window.fetch.bind(window)
  const origin = options.origin ?? window.location.origin
  const session = shallowRef<Session | null>(null)
  const sessionEndReason = shallowRef<'expired' | 'logout' | 'password_changed' | null>(null)
  let generation = 0
  let pendingSession: Promise<Session> | null = null

  function pathFor(path: string) {
    const url = new URL(path, origin)
    if (
      url.origin !== origin ||
      !url.pathname.startsWith('/api/') ||
      url.username ||
      url.password
    ) {
      throw new ApiError('invalid_url', '拒绝向非同源 API 地址发送请求')
    }
    return url.pathname + url.search
  }

  async function send<T>(
    path: string,
    schema: z.ZodType<T, z.ZodTypeDef, unknown>,
    request: RequestOptions = {},
    csrf?: string,
  ): Promise<T> {
    const headers = new Headers({ Accept: 'application/json' })
    if (csrf) headers.set('X-CSRF-Token', csrf)
    if (request.body !== undefined) headers.set('Content-Type', 'application/json')
    const response = await fetcher(pathFor(path), {
      method: request.method ?? 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      headers,
      body: request.body === undefined ? undefined : JSON.stringify(request.body),
      signal: request.signal,
    })
    let data: unknown
    try {
      data = await response.json()
    } catch {
      throw new ApiError(
        'invalid_response',
        '服务器返回了无法识别的响应，请稍后重试',
        response.status,
      )
    }
    if (!response.ok) {
      const error = errorSchema.safeParse(data)
      const retry = Number(response.headers.get('Retry-After'))
      throw new ApiError(
        error.success ? error.data.code : 'request_failed',
        error.success ? error.data.message : '请求失败，请稍后重试',
        response.status,
        Number.isFinite(retry) && retry > 0 ? retry : null,
        error.success ? error.data.details : undefined,
      )
    }
    const result = schema.safeParse(data)
    if (!result.success) throw new ApiError('invalid_response', '服务器响应格式不符合约定')
    return result.data
  }

  function acceptSession(
    next: Session | null,
    reason: 'expired' | 'logout' | 'password_changed' = 'expired',
  ) {
    generation += 1
    sessionEndReason.value = next?.authenticated ? null : reason
    session.value = next
    pendingSession = null
  }

  function loadSession(force = false): Promise<Session> {
    if (pendingSession) return pendingSession
    if (session.value && !force) return Promise.resolve(session.value)
    const revision = generation
    const pending = send('/api/session', sessionSchema)
      .then((data) => {
        // A GET started before login/logout must never overwrite the new identity.
        if (revision !== generation) {
          if (session.value) return session.value
          throw new ApiError('session_changed', '登录状态已变化，请重新操作')
        }
        if (data.authenticated) sessionEndReason.value = null
        session.value = data
        return data
      })
      .finally(() => {
        if (pendingSession === pending) pendingSession = null
      })
    pendingSession = pending
    return pending
  }

  async function handleSessionError(error: unknown) {
    if (!(error instanceof ApiError)) return
    if (error.code === 'unauthenticated') acceptSession(null)
    if (error.code === 'csrf_failed') {
      // Refresh for the NEXT deliberate action. Never replay a mutation.
      await loadSession(true).catch(() => undefined)
    }
  }

  async function handleSocketError(error: unknown, actorId: number, csrfToken: string) {
    if (session.value?.user?.id === actorId && session.value.csrf_token === csrfToken)
      await handleSessionError(error)
  }

  async function request<T>(
    path: string,
    schema: z.ZodType<T, z.ZodTypeDef, unknown>,
    options: RequestOptions = {},
  ): Promise<T> {
    pathFor(path) // Validate before even obtaining a CSRF token.
    let csrf: string | undefined
    if (options.method && options.method !== 'GET') {
      const state = await loadSession()
      options.signal?.throwIfAborted()
      if (options.expectedUserId !== undefined && state.user?.id !== options.expectedUserId) {
        throw new ApiError('session_changed', '登录账号已变化，请重新操作')
      }
      csrf = state.csrf_token
    }
    const revision = generation
    try {
      return await send(path, schema, options, csrf)
    } catch (error) {
      if (revision === generation) await handleSessionError(error)
      throw error
    }
  }

  return {
    session: readonly(session),
    sessionEndReason: readonly(sessionEndReason),
    loadSession,
    acceptSession,
    handleSocketError,
    request,
  }
}

export type ApiClient = ReturnType<typeof createApiClient>
