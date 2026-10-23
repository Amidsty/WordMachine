import { effectScope } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../shared/api/client'
import { gameState } from '../../../testing/gameApi'
import type { GameState } from './contracts'
import { useGameState } from './useGameState'

function resource(loader: (signal: AbortSignal) => Promise<GameState>) {
  const scope = effectScope()
  const value = scope.run(() => useGameState(loader))!
  return { ...value, stop: () => scope.stop() }
}

describe('game state reads', () => {
  it.each(['failure', 'older', 'equal'] as const)(
    'a slow HTTP %s cannot erase a newer push',
    async (outcome) => {
      let resolve!: (game: GameState) => void
      let reject!: (cause: Error) => void
      const view = resource(
        () =>
          new Promise((yes, no) => {
            resolve = yes
            reject = no
          }),
      )
      const reading = view.refresh()
      await flushPromises()
      const pushed = { ...gameState(), version: 9 }
      expect(view.accept(pushed)).toBe(true)
      if (outcome === 'failure') reject(new Error('offline'))
      else resolve({ ...gameState(), version: outcome === 'equal' ? 9 : 8 })
      await reading
      expect(view.game.value).toBe(pushed)
      expect(view.error.value).toBe('')
      view.stop()
      expect(view.accept({ ...gameState(), version: 10 })).toBe(false)
    },
  )
  it('post-command reconciliation waits for the older read and then starts a fresh one', async () => {
    let finish!: (game: GameState) => void
    const loader = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve
          }),
      )
      .mockResolvedValue({ ...gameState(), version: 8 })
    const view = resource(loader)
    const reading = view.refresh()
    await flushPromises()
    const reconciliation = view.reconcile()
    expect(loader).toHaveBeenCalledTimes(1)
    finish(gameState())
    await reading
    await reconciliation
    expect(loader).toHaveBeenCalledTimes(2)
    expect(view.game.value?.version).toBe(8)
    view.stop()
  })
  it('coalesces reads, keeps the visible page while refreshing, and accepts renamed users at equal version', async () => {
    const loader = vi.fn().mockResolvedValue(gameState())
    const view = resource(loader)
    await view.refresh()
    let finish!: (game: GameState) => void
    loader.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve
        }),
    )
    const first = view.refresh()
    expect(view.refresh()).toBe(first)
    await flushPromises()
    expect(loader).toHaveBeenCalledTimes(2)
    expect(view.game.value?.version).toBe(5)
    const renamed = gameState()
    renamed.users[0]!.username = 'new name'
    finish(renamed)
    await first
    expect(view.game.value?.users[0]?.username).toBe('new name')
    view.stop()
  })
  it.each([
    [gameState(), { ...gameState(), version: 4 }],
    [gameState(), { ...gameState(4, 0), version: 6 }],
    [gameState(4, 2), { ...gameState(4, -1), version: 6 }],
    [gameState(4, 0), { ...gameState(4, -1), version: 6 }],
    [gameState(), { ...gameState(4, 1, 1), version: 6 }],
  ])(
    'rejects version/index/terminal regression without overwriting accepted state',
    async (first, late) => {
      const loader = vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(late)
      const view = resource(loader)
      await view.refresh()
      await view.refresh()
      expect(view.game.value).toEqual(first)
      expect(view.error.value).toContain('未覆盖')
      view.stop()
    },
  )
  it('clears the view on failure but retains its watermark until a valid recovery', async () => {
    const loader = vi
      .fn()
      .mockResolvedValueOnce(gameState())
      .mockRejectedValueOnce(new ApiError('invalid_game_answers', 'private details', 409))
      .mockResolvedValueOnce({ ...gameState(), version: 4 })
      .mockResolvedValueOnce({ ...gameState(), version: 6 })
    const view = resource(loader)
    await view.refresh()
    await view.refresh()
    expect(view.game.value).toBe(null)
    expect(view.error.value).toContain('答题记录异常')
    await view.refresh()
    expect(view.game.value).toBe(null)
    await view.refresh()
    expect(view.game.value?.version).toBe(6)
    expect(view.error.value).toBe('')
    view.stop()
  })
  it('aborts on dispose and ignores late success even if transport ignores cancellation', async () => {
    let finish!: (game: GameState) => void
    let signal!: AbortSignal
    const view = resource((value) => {
      signal = value
      return new Promise((resolve) => {
        finish = resolve
      })
    })
    const request = view.refresh()
    await flushPromises()
    view.stop()
    expect(signal.aborted).toBe(true)
    finish(gameState())
    await request
    expect(view.game.value).toBe(null)
    await view.refresh()
    expect(view.game.value).toBe(null)
  })
  it('does not start a queued read after disposal', async () => {
    const loader = vi.fn().mockResolvedValue(gameState())
    const view = resource(loader)
    const request = view.refresh()
    view.stop()
    await request
    expect(loader).not.toHaveBeenCalled()
  })
  it('allows explicit retry after a synchronous loader failure', async () => {
    const loader = vi
      .fn()
      .mockImplementationOnce(() => {
        throw Error('network')
      })
      .mockResolvedValue(gameState())
    const view = resource(loader)
    await view.refresh()
    expect(view.error.value).toContain('网络异常')
    await view.refresh()
    expect(view.game.value?.id).toBe(4)
    view.stop()
  })
})
