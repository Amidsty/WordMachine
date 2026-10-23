import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../../shared/api/client'
import { gameState } from '../../../testing/gameApi'
import { gameStateSchema, type GameState } from './contracts'
import { createGameService } from './service'
import { answerWord, scoreRows, storedNumber, storedText } from './presentation'

describe('game read contract', () => {
  it.each([-1, 0, 1, 2] as const)(
    'accepts state %s without guessing missing legacy fields',
    (status) => {
      const game = gameState(4, status)
      if (game.result.length) game.result[0] = {}
      expect(gameStateSchema.parse(game).status).toBe(status)
    },
  )
  it.each<[string, (game: GameState) => void]>([
    [
      'version',
      (game) => {
        game.version = -1
      },
    ],
    ['unknown source', (game) => Object.assign(game, { question_source: 'unknown' })],
    [
      'future English',
      (game) => {
        game.words[2]!.english = 'secret'
      },
    ],
    [
      'future English on cancellation',
      (game) =>
        Object.assign(game, {
          status: 2,
          current_index: 0,
          result: [],
          userrating: [],
          words: game.words,
        }),
    ],
    [
      'prompt English',
      (game) =>
        Object.assign(game, {
          next_turn: 1,
          next_word: { id: 33, chinese: 'text', english: 'secret' },
        }),
    ],
    [
      'count mismatch',
      (game) => {
        game.current_index++
      },
    ],
    [
      'question count',
      (game) => {
        game.total_words++
      },
    ],
    [
      'duplicate question',
      (game) => {
        game.words[1]!.id = game.words[0]!.id
      },
    ],
    [
      'duplicate user',
      (game) => {
        game.users.push(game.users[0]!)
      },
    ],
    [
      'duplicate histories',
      (game) => {
        game.userrating.push(game.userrating[0]!)
      },
    ],
    [
      'duplicate settlement',
      (game) => {
        game.userrating[0]!.ratinghistory.push({ game_id: 4 })
      },
    ],
    [
      'unsettled history',
      (game) => {
        game.status = 0
      },
    ],
    ['truthy correctness', (game) => Object.assign(game.result[0]!, { result: 'false' })],
    [
      'nonfinite perf',
      (game) => {
        game.result[0]!.perf = Infinity
      },
    ],
    [
      'unsafe rating',
      (game) => {
        game.userrating[0]!.ratinghistory[1]!.new_rating = 2 ** 53
      },
    ],
    ['numeric string', (game) => Object.assign(game.result[0]!, { perf: '1511' })],
    [
      'bad participant key',
      (game) => {
        game.perf['01'] = game.perf['1']!
      },
    ],
  ])('rejects %s rather than showing a plausible repaired state', (_name, corrupt) => {
    const game = gameState()
    corrupt(game)
    expect(gameStateSchema.safeParse(game).success).toBe(false)
  })
  it.each(['timeout', 'dispose'] as const)(
    'bounds slow game reads and cleans the %s timer',
    async (action) => {
      vi.useFakeTimers()
      try {
        const fetcher = vi.fn<typeof fetch>(
          (_url, options) =>
            new Promise((_resolve, reject) => {
              options!.signal!.addEventListener('abort', () =>
                reject(new DOMException('aborted', 'AbortError')),
              )
            }),
        )
        const service = createGameService(createApiClient({ fetcher, origin: 'http://localhost' }))
        const controller = new AbortController()
        const promise = service.get(4, controller.signal)
        const rejection = expect(promise).rejects.toMatchObject({ name: 'AbortError' })
        if (action === 'timeout') await vi.advanceTimersByTimeAsync(10000)
        else controller.abort()
        await rejection
        expect(fetcher).toHaveBeenCalledTimes(1)
        expect(vi.getTimerCount()).toBe(0)
      } finally {
        vi.useRealTimers()
      }
    },
  )
  it('binds response to requested ID and refuses invalid IDs before fetch', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ success: true, game: gameState(5) }))
    const service = createGameService(createApiClient({ fetcher, origin: 'http://localhost' }))
    await expect(service.get(0)).rejects.toMatchObject({ code: 'invalid_parameters' })
    await expect(service.get(2147483648)).rejects.toMatchObject({ code: 'invalid_parameters' })
    expect(fetcher).not.toHaveBeenCalled()
    await expect(service.get(4)).rejects.toMatchObject({ code: 'invalid_response' })
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0]![1]).toMatchObject({
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
    })
  })
})

describe('history presentation is not a scoring engine', () => {
  it('selects this game rather than latest/current rating and preserves exact zero and Perf', () => {
    const game = gameState()
    const before = JSON.stringify(game)
    const rows = scoreRows(game)
    expect(rows[0]!.perf).toBe(game.result[0]!.perf)
    expect(rows[0]!.rating).toEqual({ game_id: 4, delta: 7, new_rating: 1507 })
    expect(rows[1]!.perf).toBe(0)
    expect(rows[1]!.rating).toEqual({ game_id: 4, delta: 0, new_rating: 0 })
    expect(rows[2]).toMatchObject({ answered: 0, perf: null, rating: undefined })
    expect(storedNumber(0)).toBe('0')
    expect(storedNumber(-0)).toBe('-0')
    expect(storedNumber(7, true)).toBe('+7')
    expect(storedNumber(null)).toBe('记录缺失')
    expect(storedText('')).toBe('（空文本）')
    expect(JSON.stringify(game)).toBe(before)
  })
  it('does not carry forward an earlier Perf, turn unknown correctness into wrong, or hide missing users', () => {
    const game = gameState(4, 1, 3)
    game.users = game.users.filter((user) => user.id !== 2)
    game.result[2] = { uid: 1, word_id: 33 }
    game.result.push({ uid: 77, perf: 12 }, {})
    const rows = scoreRows(game)
    expect(rows[0]).toMatchObject({ correct: 1, wrong: 0, unknown: 1, perf: null })
    expect(rows.find((row) => row.id === 2)?.name).toContain('用户 #2')
    expect(rows.find((row) => row.id === 77)).toMatchObject({
      participant: false,
      perf: 12,
      unknown: 1,
    })
    expect(rows).toHaveLength(4) // No fabricated ID for the answer without an author.
  })
  it('never follows a bad legacy answer ID to a future or unrelated question', () => {
    const game = gameState()
    expect(answerWord(game, { word_id: 33 }, 0)).toBe(null)
    expect(answerWord(game, {}, 0)).toBe(null)
    expect(answerWord(game, game.result[0]!, 0)?.english).toBe('standard-0')
  })
})
