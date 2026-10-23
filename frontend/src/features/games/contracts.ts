import { z } from 'zod'
import { weightedSchema } from './weighted'
import { perfPolicyFields } from '../../shared/api/contracts'
import { gameVersionSchema } from '../../shared/api/gameCommand'

export const gameNameSchema = z
  .string()
  .refine(
    (value) =>
      value.trim() === value &&
      Array.from(value).length >= 1 &&
      Array.from(value).length <= 100 &&
      !/[\p{Cc}\p{Cs}\p{Zl}\p{Zp}]/u.test(value),
  )

export const gameIdSchema = z.number().int().positive().max(2147483647)
export const gamePersonSchema = z.object({
  id: gameIdSchema,
  username: z.string().nullable(),
  // Older responses may omit current Rating; never infer it from saved scores.
  rating: z.number().int().nullable().optional(),
})
export const gamePresenceSchema = z.object({
  game_id: gameIdSchema,
  revision: z.number().int().nonnegative().safe(),
  spectators: z
    .array(gamePersonSchema)
    .refine((users) => new Set(users.map((user) => user.id)).size === users.length),
})
export type GameSpectator = z.infer<typeof gamePersonSchema>

export const gameStatusSchema = z.union([z.literal(-1), z.literal(0), z.literal(1), z.literal(2)])
export const gameStatusLabels = { '-1': '待开始', '0': '进行中', '1': '已结束', '2': '已取消' }
const count = z.number().int().nonnegative().max(2147483647)
const score = z.number().finite()
const integer = z.number().int().safe()
const prompt = z.object({
  id: gameIdSchema,
  chinese: z.string().nullable(),
  english: z.never().optional(), // The current prompt must not include its English answer.
})
const word = z.object({
  id: gameIdSchema,
  chinese: z.string().nullable(),
  english: z.string().nullable().optional(),
})
const answer = z.object({
  // Legacy JSON may lack these fields. Absence is not a false result or zero score.
  uid: gameIdSchema.nullish(),
  word_id: gameIdSchema.nullish(),
  answer: z.string().nullish(),
  result: z.boolean().nullish(),
  perf: score.nullish(),
  perf_delta: score.nullish(),
  raw_perf_delta: score.nullish(),
  usercombo: count.nullish(),
  globalcombo: count.nullish(),
  rating_version: z.string().nullish(),
})
const rating = z.object({
  game_id: gameIdSchema,
  delta: integer.nullish(),
  new_rating: integer.nullish(),
})
const participantKey = z
  .string()
  .regex(/^[1-9][0-9]*$/)
  .refine((value) => Number(value) <= 2147483647)

export const gameStateSchema = z
  .object({
    id: gameIdSchema,
    version: gameVersionSchema,
    name: gameNameSchema.nullable().optional(),
    dictid: gameIdSchema.nullable(),
    dictname: z.string().nullable(),
    question_source: z.enum(['snapshot', 'legacy_live']),
    rated: z.boolean(),
    ...perfPolicyFields,
    scoring: weightedSchema.nullable().optional(),
    owner: gamePersonSchema.nullable(),
    users: z.array(gamePersonSchema),
    userrating: z.array(z.object({ user_id: gameIdSchema, ratinghistory: z.array(rating) })),
    words: z.array(word),
    result: z.array(answer),
    perf: z.record(
      participantKey,
      z.object({ correct: count, wrong: count, perf: score.nullable() }),
    ),
    status: gameStatusSchema,
    total_words: count,
    current_index: count,
    next_turn: gameIdSchema.nullable(),
    next_word: prompt.nullable(),
  })
  .superRefine((game, context) => {
    function require(condition: boolean) {
      if (!condition)
        context.addIssue({ code: z.ZodIssueCode.custom, message: 'Inconsistent game response' })
    }
    if (game.perf_rule_version === 'dict-perf-v1')
      require(game.multiplier_snapshot != null && game.question_source === 'snapshot')
    else require(game.multiplier_snapshot == null)
    if (game.scoring) {
      require(
        game.next_answer_perf_rule_version ===
          ([-1, 0].includes(game.status) ? 'weighted-perf-v1' : null),
      )
      require(game.scoring.answers.length === game.result.length)
      game.scoring.answers.forEach((a, i) =>
        require(
          a.position === i &&
            a.user_id === game.result[i]?.uid &&
            a.perf_delta === game.result[i]?.perf_delta,
        ),
      )
      require(
        game.scoring.players.every(
          (p) =>
            game.users.some((u) => u.id === p.user_id) &&
            (!p.settlement || (game.rated && game.status === 1)),
        ),
      )
      for (const p of game.scoring.players) {
        const own = game.result.filter((a) => a.uid === p.user_id)
        require(p.answered_count === own.length && p.perf === (own.at(-1)?.perf ?? null))
        if (p.settlement) {
          const saved = game.userrating
            .find((u) => u.user_id === p.user_id)
            ?.ratinghistory.find((r) => r.game_id === game.id)
          require(
            saved?.delta === p.settlement.total_delta &&
              saved?.new_rating === p.settlement.public_after,
          )
        }
      }
      require(game.result.every((a) => a.rating_version === 'weighted-perf-v1'))
      require(
        game.scoring.players.length === ([0, 1].includes(game.status) ? game.users.length : 0),
      )
    } else {
      require(game.next_answer_perf_rule_version !== 'weighted-perf-v1')
      require(!game.result.some((a) => a.rating_version === 'weighted-perf-v1'))
    }
    const unique = (ids: number[]) => new Set(ids).size === ids.length
    require(game.total_words === game.words.length)
    require(game.current_index === game.result.length && game.current_index <= game.total_words)
    require(unique(game.words.map((word) => word.id)))
    require(unique(game.users.map((user) => user.id)))
    require(unique(game.userrating.map((user) => user.user_id)))
    game.words.forEach((word, index) => {
      if (index >= game.current_index) require(word.english === undefined)
    })
    game.userrating.forEach((user) => {
      require(unique(user.ratinghistory.map((entry) => entry.game_id)))
      if (game.status !== 1 || !game.rated)
        require(!user.ratinghistory.some((entry) => entry.game_id === game.id))
    })
    require((game.next_turn === null) === (game.next_word === null))
    if (game.next_word) {
      require(game.status === 0)
      const current = game.words[game.current_index]
      require(current?.id === game.next_word.id && current?.chinese === game.next_word.chinese)
    }
  })

export type GameState = z.infer<typeof gameStateSchema>
export type GameAnswer = z.infer<typeof answer>
export type GameRating = z.infer<typeof rating>
