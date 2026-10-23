// Read-only UI fixture, not a scoring/authorization/database implementation.
import type { GameState } from '../src/features/games/contracts'
import { createLobbyApi } from './lobbyApi'

export function gameState(id = 4, status: GameState['status'] = 1, answers = 2): GameState {
  const size = status === -1 || status === 2 ? 0 : answers
  const words = Array.from({ length: Math.max(3, size + 1) }, (_, index) => ({
    id: (index + 1) * 11,
    chinese: `题面-${index} <img src=x>\n第二行`,
    ...(index < size ? { english: `standard-${index}` } : {}),
  }))
  const result = Array.from({ length: size }, (_, index) => ({
    uid: (index % 2) + 1,
    word_id: words[index]!.id,
    answer: `提交-${index} <script>x</script>`,
    result: index % 2 === 0,
    perf: index % 2 === 0 ? 1511.1234567890124 : 0,
    perf_delta: index % 2 === 0 ? 11.123456789012344 : -1,
    usercombo: 1,
    globalcombo: 1,
    rating_version: 'legacy-v1',
  }))
  return {
    id,
    version: 5,
    rated: true,
    status,
    dictid: 2,
    dictname: '<svg onload=alert(1)>旧词典',
    question_source: 'snapshot',
    owner: { id: 1, username: '<img src=x>', rating: 2400 },
    users: [
      { id: 1, username: '<img src=x>', rating: 2400 },
      { id: 2, username: null, rating: null },
      { id: 3, username: '未作答的人', rating: 1200 },
    ],
    words,
    result,
    total_words: words.length,
    current_index: size,
    next_turn: status === 0 ? (size % 2) + 1 : null,
    next_word: status === 0 ? { id: words[size]!.id, chinese: words[size]!.chinese } : null,
    perf: {
      '1': { correct: 1, wrong: 0, perf: 1511.1234567890124 },
      '2': { correct: 0, wrong: 1, perf: 0 },
      '3': { correct: 0, wrong: 0, perf: 0 },
    },
    userrating: [
      {
        user_id: 1,
        ratinghistory:
          status === 1 && size > 0
            ? [
                { game_id: 999, delta: 100, new_rating: 1500 },
                { game_id: id, delta: 7, new_rating: 1507 },
                { game_id: 998, delta: 200, new_rating: 1707 },
              ]
            : [],
      },
      {
        user_id: 2,
        ratinghistory: status === 1 && size > 1 ? [{ game_id: id, delta: 0, new_rating: 0 }] : [],
      },
      { user_id: 3, ratinghistory: [] },
    ],
  }
}

export function createGameApi(authenticated = true) {
  const lobby = createLobbyApi(authenticated)
  const games = new Map(
    [gameState(), gameState(5, 2), gameState(6, -1), gameState(7, 0)].map((game) => [
      game.id,
      game,
    ]),
  )
  const state = { failure: null as null | { status: number; code: string } }
  function handle(
    url: string,
    method = 'GET',
    body: Record<string, unknown> = {},
    csrf?: string | null,
  ) {
    const path = new URL(url, 'http://localhost').pathname
    const match = /^\/api\/game\/(\d+)$/.exec(path)
    if (match) {
      const failure = !lobby.state.authenticated
        ? { status: 401, code: 'unauthenticated' }
        : state.failure
      if (failure)
        return {
          status: failure.status,
          body: { success: false, code: failure.code, message: failure.code },
        }
      const game = games.get(Number(match[1]))
      return game && method === 'GET'
        ? { status: 200, body: { success: true, game } }
        : { status: 404, body: { success: false, code: 'not_found', message: 'not_found' } }
    }
    return lobby.handle(url, method, body, csrf)
  }
  return { games, state, lobby, handle }
}
