import { onScopeDispose, readonly, ref, shallowReadonly, shallowRef } from 'vue'
import { ApiError } from '../../shared/api/client'
import { errorMessage } from '../../shared/forms/useFormTask'
import type { GameState } from './contracts'

// One outstanding read per page. Only validated GET/push states, never command receipts.
export function useGameState(load: (signal: AbortSignal) => Promise<GameState>) {
  const game = shallowRef<GameState | null>(null)
  const pending = ref(false)
  const error = ref('')
  let previous: GameState | null = null // Keep the watermark even when a failed read clears the view.
  let request: Promise<void> | null = null
  let controller: AbortController | null = null
  let disposed = false
  let revision = 0

  function accept(next: GameState) {
    if (disposed) return false
    if (
      previous &&
      (next.id !== previous.id ||
        next.rated !== previous.rated ||
        (next.scoring?.model ?? null) !== (previous.scoring?.model ?? null) ||
        (next.scoring?.difficulty ?? null) !== (previous.scoring?.difficulty ?? null) ||
        (next.version === previous.version &&
          JSON.stringify(next.scoring ?? null) !== JSON.stringify(previous.scoring ?? null)) ||
        next.version < previous.version ||
        (next.version === previous.version && (next.name ?? null) !== (previous.name ?? null)) ||
        next.current_index < previous.current_index ||
        ([1, 2].includes(previous.status) && next.status !== previous.status) ||
        (previous.status === 0 && next.status === -1))
    ) {
      error.value = '收到较旧或倒退的对局状态，未覆盖已读取记录；请刷新确认。'
      return false
    }
    revision += 1
    previous = next
    game.value = next
    error.value = ''
    return true
  }

  async function reconcile() {
    // A read started before the command committed may be an older MVCC snapshot.
    if (request) await request
    await refresh()
  }

  function refresh(): Promise<void> {
    if (disposed) return Promise.resolve()
    if (request) return request
    controller = new AbortController()
    const signal = controller.signal
    const started = revision
    pending.value = true
    error.value = ''
    request = Promise.resolve().then(async () => {
      try {
        signal.throwIfAborted()
        const next = await load(signal)
        if (disposed || signal.aborted) return
        if (revision !== started && previous && next.version <= previous.version) return
        accept(next) // Equal versions may carry renamed users/live dictionary text.
      } catch (cause) {
        if (disposed || signal.aborted || revision !== started) return
        game.value = null
        error.value =
          cause instanceof ApiError ? errorMessage(cause) : '网络异常，无法读取对局；请稍后刷新。'
      } finally {
        request = null
        if (!disposed) pending.value = false
      }
    })
    return request
  }
  onScopeDispose(() => {
    disposed = true
    controller?.abort()
  })
  return {
    game: shallowReadonly(game),
    pending: readonly(pending),
    error: readonly(error),
    refresh,
    accept,
    reconcile,
  }
}
