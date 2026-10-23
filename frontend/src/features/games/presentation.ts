import type { GameAnswer, GameRating, GameState } from './contracts'

export function storedText(value: string | null | undefined) {
  return value == null ? '记录缺失' : value === '' ? '（空文本）' : value
}

export function storedNumber(value: number | null | undefined, signed = false) {
  if (value == null) return '记录缺失'
  if (Object.is(value, -0)) return '-0'
  return `${signed && value > 0 ? '+' : ''}${value}`
}

const perfFormatter = new Intl.NumberFormat('en-US', {
  useGrouping: false,
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})

// Display-only, rounded half away from zero; never change stored/scoring values.
export function storedPerf(value: number | null | undefined, signed = false) {
  if (value == null || !Number.isFinite(value)) return '记录缺失'
  return `${signed && value > 0 ? '+' : ''}${perfFormatter.format(value)}`
}

export function personName(game: GameState, uid: number | null | undefined) {
  if (uid == null) return '作答者记录缺失'
  return game.users.find((user) => user.id === uid)?.username ?? `用户 #${uid}（资料缺失）`
}

export function personRating(game: GameState, uid: number | null | undefined) {
  return game.users.find((user) => user.id === uid)?.rating
}

export function answerWord(game: GameState, answer: GameAnswer, index: number) {
  const word = game.words[index]
  // Do not repair a broken legacy reference or look up a future/source-dictionary word.
  return word && word.id === answer.word_id ? word : null
}

type ScoreRow = {
  id: number
  name: string
  participant: boolean
  answered: number
  correct: number
  wrong: number
  unknown: number
  perf: number | null
  rating: GameRating | undefined
}

export function participantIds(game: GameState) {
  // The server's summary retains legacy member IDs even when user info is missing.
  return new Set([...game.users.map((user) => user.id), ...Object.keys(game.perf).map(Number)])
}

export function scoreRows(game: GameState): ScoreRow[] {
  const participants = participantIds(game)
  const ids = new Set([
    ...participants,
    ...game.result.flatMap((answer) => (answer.uid == null ? [] : [answer.uid])),
  ])
  const histories = new Map(game.userrating.map((user) => [user.user_id, user.ratinghistory]))
  const rows = new Map<number, ScoreRow>()
  for (const id of ids) {
    rows.set(id, {
      id,
      name: personName(game, id),
      participant: participants.has(id),
      answered: 0,
      correct: 0,
      wrong: 0,
      unknown: 0,
      perf: null,
      rating: histories.get(id)?.find((rating) => rating.game_id === game.id),
    })
  }
  // Display counts only, not scoring rules. Perf is the last recorded value;
  // missing correctness is not "wrong", missing Perf is not zero/the previous Perf.
  for (const answer of game.result) {
    if (answer.uid == null) continue
    const row = rows.get(answer.uid)!
    row.answered++
    row[answer.result === true ? 'correct' : answer.result === false ? 'wrong' : 'unknown']++
    row.perf = answer.perf ?? null
  }
  return [...rows.values()]
}
