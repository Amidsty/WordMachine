// Controllable transport fixture, not a Socket.IO/server/authentication implementation.
import type { SocketWire } from '../src/shared/api/socket'
export class FakeSocket {
  connected = false
  autoConnect = true
  writable = true
  auth: SocketWire['auth'] = {}
  handshakes: unknown[] = []
  listeners = new Map<string, Set<(...data: unknown[]) => void>>()
  sent: {
    event: string
    volatile: boolean
    data: Record<string, unknown>
    ack: (data: unknown, error?: Error) => void
  }[] = []
  private pending = new Set<() => void>()
  factory = () => this as unknown as SocketWire
  on(event: string, listener: (...data: unknown[]) => void) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set())
    this.listeners.get(event)!.add(listener)
  }
  off(event: string, listener: (...data: unknown[]) => void) {
    this.listeners.get(event)?.delete(listener)
  }
  server(event: string, ...data: unknown[]) {
    for (const listener of [...(this.listeners.get(event) ?? [])]) listener(...data)
  }
  connect() {
    if (!this.autoConnect) return
    if (typeof this.auth === 'function')
      this.auth((data) => {
        this.handshakes.push(data)
        this.connected = true
        this.server('connect')
      })
  }
  disconnect() {
    this.connected = false
    for (const cancel of [...this.pending]) cancel()
    this.server('disconnect')
  }
  timeout(ms: number) {
    const emit =
      (volatile: boolean) =>
      (
        event: string,
        data: Record<string, unknown>,
        callback: (error: Error | null, data?: unknown) => void,
      ) => {
        const cancel = () => {
          clearTimeout(timer)
          this.pending.delete(cancel)
          callback(new Error('disconnect'))
        }
        const timer = setTimeout(cancel, ms)
        this.pending.add(cancel)
        if (volatile && !this.writable) return
        this.sent.push({
          event,
          volatile,
          data,
          ack: (value, error) => {
            clearTimeout(timer)
            this.pending.delete(cancel)
            callback(error ?? null, value)
          },
        })
      }
    return { emit: emit(false), volatile: { emit: emit(true) } }
  }
}
