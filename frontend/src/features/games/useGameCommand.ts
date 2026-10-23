import { onScopeDispose, readonly, ref, shallowReadonly, shallowRef } from 'vue'
import { errorMessage } from '../../shared/forms/useFormTask'
import { newIntent, type GameIntent, type NewGameIntent } from './commands'

// A single frozen intent survives timeout/disconnect and state changes, until a deliberate
// retry or dismissal. An acknowledgement is not current state and never updates scores.
export function useGameCommand(
  send: (intent: GameIntent, signal: AbortSignal) => Promise<unknown>,
  reconcile: () => Promise<void>,
) {
  const intent = shallowRef<GameIntent | null>(null)
  const pending = ref(false)
  const error = ref('')
  const notice = ref('')
  const controller = new AbortController()
  onScopeDispose(() => controller.abort())
  async function retry() {
    if (!intent.value || pending.value || controller.signal.aborted) return
    const original = intent.value
    pending.value = true
    error.value = ''
    notice.value = ''
    let confirmed = false
    const attempt = new AbortController()
    const abort = () => attempt.abort()
    controller.signal.addEventListener('abort', abort, { once: true })
    const timeout = setTimeout(abort, 10000)
    try {
      await send(original, attempt.signal)
      confirmed = true
      if (!controller.signal.aborted)
        notice.value = '操作回执已确认；成绩和状态以重新读取的对局为准。'
    } catch (cause) {
      if (!controller.signal.aborted)
        error.value = errorMessage(cause) + ' 未自动重发；可核对状态后手动重试原请求。'
    } finally {
      clearTimeout(timeout)
      controller.signal.removeEventListener('abort', abort)
    }
    // Refresh failure must not relabel a confirmed commit as a failed write.
    if (!controller.signal.aborted) {
      try {
        await reconcile()
      } catch {
        /* The state resource owns read errors. */
      }
      if (!controller.signal.aborted) {
        if (confirmed) intent.value = null
        pending.value = false
      }
    }
  }
  async function submit(input: NewGameIntent) {
    if (pending.value || intent.value || controller.signal.aborted) return
    try {
      intent.value = newIntent(input)
    } catch {
      error.value = '请求参数无效，未提交操作。'
      return
    }
    await retry()
  }
  function dismiss() {
    if (pending.value) return
    intent.value = null
    error.value = ''
    notice.value = '已放弃等待原回执，不代表撤销或回滚；请先核对当前状态。'
    void reconcile()
  }
  return {
    intent: shallowReadonly(intent),
    pending: readonly(pending),
    error: readonly(error),
    notice: readonly(notice),
    submit,
    retry,
    dismiss,
  }
}
