import { readonly, ref } from 'vue'
import { io, type Socket } from 'socket.io-client'
import type { z } from 'zod'
import { ApiError, type ApiClient } from './client'
import { errorSchema } from './contracts'

// A private Manager per page: no room subscriptions or buffered writes survive navigation.
export type SocketWire = Pick<
  Socket,
  'auth' | 'connected' | 'on' | 'off' | 'connect' | 'disconnect' | 'timeout'
>
export type SocketFactory = () => SocketWire
export const browserSocket: SocketFactory = () =>
  io({
    autoConnect: false,
    forceNew: true,
    retries: 0,
    timeout: 10000,
  })

export function createSocketService(client: ApiClient, factory: SocketFactory = browserSocket) {
  return {
    open(
      actorId: number,
      updated: (data: unknown) => void,
      connected: () => void,
      presence?: (data: unknown) => void,
    ) {
      const wire = factory()
      const online = ref(false)
      let closed = false
      const pending = new Set<() => void>()
      const unavailable = () =>
        new ApiError('socket_unconfirmed', '实时请求未获确认；请先核对状态，再手动重试原请求。')
      const onConnect = () => {
        if (closed) return
        online.value = true
        connected()
      }
      const onDisconnect = () => {
        online.value = false
        for (const cancel of [...pending]) cancel()
      }
      const onUpdate = (data: unknown) => {
        if (!closed) updated(data)
      }
      const onPresence = (data: unknown) => {
        if (!closed) presence?.(data)
      }
      // Reconnection only re-authenticates and subscribes. Never replay a write.
      wire.auth = (callback) => {
        void client
          .loadSession(true)
          .then((session) => {
            if (closed) return
            if (!session.authenticated || session.user.id !== actorId) {
              close()
              return
            }
            callback({ csrf_token: session.csrf_token })
          })
          .catch(() => {
            if (!closed) callback({ csrf_token: '' })
          })
      }
      wire.on('connect', onConnect)
      wire.on('disconnect', onDisconnect)
      wire.on('connect_error', onDisconnect)
      wire.on('game.update', onUpdate)
      wire.on('game.presence', onPresence)
      // game.error and game.answer_result are uncorrelated/duplicate notifications.
      // Only the per-emission acknowledgement may complete a command.
      function close() {
        if (closed) return
        closed = true
        onDisconnect()
        wire.off('connect', onConnect)
        wire.off('disconnect', onDisconnect)
        wire.off('connect_error', onDisconnect)
        wire.off('game.update', onUpdate)
        wire.off('game.presence', onPresence)
        wire.disconnect()
      }
      async function request<T>(
        event: 'game.subscribe' | 'game.answer' | 'game.end',
        payload: object,
        schema: z.ZodType<T, z.ZodTypeDef, unknown>,
        signal?: AbortSignal,
      ): Promise<T> {
        signal?.throwIfAborted()
        const session = client.session.value
        if (!session?.authenticated || session.user.id !== actorId)
          throw new ApiError('session_changed', '登录账号已变化，请重新操作')
        if (closed || !wire.connected) throw unavailable()
        try {
          return await new Promise<T>((resolve, reject) => {
            let done = false
            const finish = (error?: unknown, value?: T) => {
              if (done) return
              done = true
              pending.delete(cancel)
              signal?.removeEventListener('abort', abort)
              if (error) reject(error)
              else resolve(value as T)
            }
            const cancel = () => finish(unavailable())
            const abort = () => finish(new DOMException('Request cancelled', 'AbortError'))
            pending.add(cancel)
            signal?.addEventListener('abort', abort, { once: true })
            // Read-only subscription may queue while the handshake transport is busy.
            // Writes are volatile: dropping one never causes an automatic HTTP retry.
            const timed = wire.timeout(10000)
            const emitter = event === 'game.subscribe' ? timed : timed.volatile
            try {
              emitter.emit(
                event,
                { ...payload, csrf_token: session.csrf_token },
                (error: Error | null, data: unknown) => {
                  if (done) return
                  if (error) {
                    cancel()
                    return
                  }
                  const failure = errorSchema.safeParse(data)
                  if (failure.success) {
                    finish(new ApiError(failure.data.code, failure.data.message))
                    return
                  }
                  const parsed = schema.safeParse(data)
                  if (!parsed.success)
                    finish(
                      new ApiError(
                        'invalid_response',
                        '实时回执格式或请求编号不符合约定；请核对状态。',
                      ),
                    )
                  else finish(undefined, parsed.data)
                },
              )
            } catch (error) {
              finish(error)
            }
          })
        } catch (error) {
          // A late old-session failure cannot evict a different/new login.
          await client.handleSocketError(error, actorId, session.csrf_token)
          throw error
        }
      }
      return {
        online: readonly(online),
        connect: () => {
          if (!closed) wire.connect()
        },
        close,
        request,
      }
    },
  }
}
export type SocketChannel = ReturnType<ReturnType<typeof createSocketService>['open']>
