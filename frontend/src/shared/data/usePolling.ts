import { computed, onMounted, onScopeDispose, ref, watch } from 'vue'
import { errorMessage } from '../forms/useFormTask'

// Only repeat reads. The resource owns request cancellation and stale-response checks.
export function usePolling(
  operation: () => Promise<void>,
  enabled: () => boolean,
  intervalMs = 5000,
) {
  const visible = ref(!document.hidden)
  const online = ref(navigator.onLine)
  const paused = computed(() => !visible.value || !online.value || !enabled())
  const error = ref('')
  let timer: ReturnType<typeof setTimeout> | undefined
  let mounted = false
  let disposed = false
  let running = false
  function clear() {
    clearTimeout(timer)
    timer = undefined
  }
  function schedule() {
    clear()
    if (mounted && !disposed && !paused.value && !running)
      timer = setTimeout(() => void run(), intervalMs)
  }
  async function run() {
    clear()
    if (disposed || paused.value || running) return
    running = true
    error.value = ''
    try {
      await operation()
    } catch (cause) {
      if (!disposed) error.value = errorMessage(cause)
    } finally {
      running = false
      schedule()
    }
  }
  function visibility() {
    visible.value = !document.hidden
  }
  function connectivity() {
    online.value = navigator.onLine
  }
  watch(paused, (value) => {
    if (value) clear()
    else if (mounted) void run()
  })
  onMounted(() => {
    mounted = true
    document.addEventListener('visibilitychange', visibility)
    window.addEventListener('online', connectivity)
    window.addEventListener('offline', connectivity)
    schedule()
  })
  onScopeDispose(() => {
    disposed = true
    clear()
    document.removeEventListener('visibilitychange', visibility)
    window.removeEventListener('online', connectivity)
    window.removeEventListener('offline', connectivity)
  })
  return { paused, error }
}
