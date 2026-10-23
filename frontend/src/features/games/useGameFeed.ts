import { computed, onMounted, onScopeDispose, ref, shallowRef, watch } from 'vue'
import type { AppServices } from '../../app/services'
import { successSchema } from '../../shared/api/contracts'
import { gameCommandSchema } from '../../shared/api/gameCommand'
import type { SocketChannel } from '../../shared/api/socket'
import { errorMessage } from '../../shared/forms/useFormTask'
import {
  gameIdSchema,
  gamePresenceSchema,
  gameStateSchema,
  type GameSpectator,
  type GameState,
} from './contracts'
import { commandPayload, type GameIntent } from './commands'

export function useGameFeed(
  services: AppServices,
  gameId: number,
  actorId: number,
  accept: (game: GameState) => boolean,
  reconcile: () => Promise<void>,
) {
  const enabled = ref(true)
  const channel = shallowRef<SocketChannel | null>(null)
  const subscribed = ref(false)
  const error = ref('')
  const presence = shallowRef<GameSpectator[] | null>(null)
  const online = computed(() => channel.value?.online.value ?? false)
  const ready = computed(() => online.value && subscribed.value)
  const spectators = computed(() => (ready.value ? presence.value : null))
  const lifetime = new AbortController()
  let subscription = 0
  let presenceRevision = -1
  let heartbeat: ReturnType<typeof setInterval> | undefined
  let renew: (() => void) | null = null
  function clearPresence() {
    presence.value = null
    presenceRevision = -1
  }
  function start() {
    if (!enabled.value || !gameIdSchema.safeParse(gameId).success || !actorId) return
    let subscribing = false
    const current = services.sockets.open(
      actorId,
      (raw) => {
        if (typeof raw === 'object' && raw && 'id' in raw && raw.id !== gameId) return
        const parsed = gameStateSchema.safeParse(raw)
        if (!parsed.success) {
          error.value = '实时状态格式异常，请使用刷新核对。'
          return
        }
        accept(parsed.data)
      },
      () => {
        subscribed.value = false
        clearPresence() // A reconnect may reach a restarted server with a new revision sequence.
        subscribing = false
        subscribe(true)
      },
      (raw) => {
        if (typeof raw === 'object' && raw && 'game_id' in raw && raw.game_id !== gameId) return
        const parsed = gamePresenceSchema.safeParse(raw)
        if (!parsed.success) {
          presence.value = null
          return
        }
        if (parsed.data.revision <= presenceRevision) return
        presenceRevision = parsed.data.revision
        presence.value = parsed.data.spectators
      },
    )
    function subscribe(repair = false) {
      if (subscribing || channel.value !== current || !current.online.value) return
      subscribing = true
      const attempt = ++subscription
      const before = presenceRevision
      void current
        .request('game.subscribe', { game_id: gameId }, successSchema, lifetime.signal)
        .then(() => {
          if (channel.value !== current || lifetime.signal.aborted || attempt !== subscription)
            return
          subscribed.value = true
          error.value = ''
          if (presenceRevision === before) presence.value = null
          if (repair) void reconcile()
        })
        .catch((cause) => {
          if (channel.value !== current || lifetime.signal.aborted || attempt !== subscription)
            return
          subscribed.value = false
          clearPresence()
          error.value = errorMessage(cause)
        })
        .finally(() => {
          if (attempt === subscription) subscribing = false
        })
    }
    channel.value = current
    renew = () => subscribe()
    current.connect()
  }
  function stop() {
    const current = channel.value
    channel.value = null
    subscribed.value = false
    renew = null
    clearPresence()
    current?.close()
  }
  watch(enabled, () => {
    stop()
    if (enabled.value) start()
  })
  watch(
    online,
    (next, previous) => {
      if (!next) {
        subscribed.value = false
        clearPresence()
      }
      if (!next && previous && !lifetime.signal.aborted) void reconcile()
    },
    { flush: 'sync' },
  )
  onMounted(() => {
    start()
    // Read-only renewal revalidates expired/revoked viewers even during idle games.
    heartbeat = setInterval(() => {
      if (online.value) renew?.()
    }, 15000)
  })
  onScopeDispose(() => {
    lifetime.abort()
    clearInterval(heartbeat)
    stop()
  })
  async function send(intent: GameIntent, signal: AbortSignal) {
    const current = channel.value
    // Choose ONCE before sending. Never fall back automatically after an uncertain emit.
    if (current && ready.value)
      return current.request(
        `game.${intent.action}`,
        { game_id: gameId, ...commandPayload(intent) },
        gameCommandSchema(intent.request_id),
        signal,
      )
    return services.games.command(intent, signal)
  }
  return { enabled, ready, error, send, spectators }
}
