import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, nextTick, ref } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { usePolling } from './usePolling'

let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.useRealTimers()
})
function start(operation: () => Promise<void>, enabled = ref(true)) {
  let state!: ReturnType<typeof usePolling>
  wrapper = mount(
    defineComponent({
      setup() {
        state = usePolling(operation, () => enabled.value)
        return () => null
      },
    }),
  )
  return state
}

describe('read-only polling lifecycle', () => {
  it('does not overlap slow requests or restart after unmount', async () => {
    let resolve!: () => void
    const operation = vi.fn(
      () =>
        new Promise<void>((done) => {
          resolve = done
        }),
    )
    start(operation)
    await vi.advanceTimersByTimeAsync(5000)
    expect(operation).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(30000)
    expect(operation).toHaveBeenCalledTimes(1)
    wrapper!.unmount()
    wrapper = undefined
    resolve()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(30000)
    expect(operation).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })
  it('pauses offline and in background, then refreshes immediately on recovery', async () => {
    const operation = vi.fn(async () => {})
    const state = start(operation)
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    window.dispatchEvent(new Event('offline'))
    await nextTick()
    await vi.advanceTimersByTimeAsync(10000)
    expect(state.paused.value).toBe(true)
    expect(operation).not.toHaveBeenCalled()
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true)
    window.dispatchEvent(new Event('online'))
    await flushPromises()
    expect(operation).toHaveBeenCalledTimes(1)
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    document.dispatchEvent(new Event('visibilitychange'))
    await nextTick()
    await vi.advanceTimersByTimeAsync(10000)
    expect(operation).toHaveBeenCalledTimes(1)
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(operation).toHaveBeenCalledTimes(2)
  })
  it('pauses while a dialog is open and exposes unexpected failures', async () => {
    const enabled = ref(false)
    const operation = vi.fn(async () => {
      throw Error('offline')
    })
    const state = start(operation, enabled)
    await vi.advanceTimersByTimeAsync(10000)
    expect(operation).not.toHaveBeenCalled()
    enabled.value = true
    await flushPromises()
    expect(state.error.value).toContain('网络异常')
    enabled.value = false
    await nextTick()
    await vi.advanceTimersByTimeAsync(10000)
    expect(operation).toHaveBeenCalledTimes(1)
  })
})
