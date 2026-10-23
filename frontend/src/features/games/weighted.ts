import { z } from 'zod'

const integer = z.number().int().safe()
const rating = integer.min(-2147483648).max(2147483647)
const count = integer.nonnegative().max(2147483647)
const finite = z.number().finite()
const allowance = (n: number, enabled: boolean) =>
  enabled ? ([1500, 900, 550, 300, 150, 50][n] ?? 0) : 0
const bonus = (n: number, enabled: boolean) =>
  enabled ? ([600, 350, 250, 150, 100, 50][n] ?? 0) : 0
export const ratingStateSchema = z
  .object({
    model: z.literal('weighted-v1'),
    public_rating: rating,
    internal_rating: integer,
    remaining_bonus: integer.min(0).max(1500),
    completed_games: count,
    newcomer_enabled: z.boolean(),
    next_bonus: integer.min(0).max(600),
  })
  .refine(
    (v) =>
      v.internal_rating === v.public_rating + v.remaining_bonus &&
      v.remaining_bonus === allowance(v.completed_games, v.newcomer_enabled) &&
      v.next_bonus === bonus(v.completed_games, v.newcomer_enabled),
  )
export const weightedSchema = z.object({
  model: z.literal('weighted-v1'),
  perf_version: z.literal('weighted-perf-v1'),
  rating_version: z.literal('weighted-rating-v1'),
  difficulty: integer.min(0).max(4000),
  players: z
    .array(
      z.object({
        user_id: count.positive(),
        public_before: rating,
        internal_before: integer,
        remaining_before: integer.min(0).max(1500),
        completed_before: count,
        newcomer_enabled: z.boolean(),
        streak_protection: finite.min(0).max(1),
        rating_protection: finite.min(0.2).max(1),
        speed_up: finite.min(0.25).max(1),
        speed_down: finite.min(1).max(2),
        answered_count: count,
        raw_points: finite.nullable(),
        perf: finite.nullable(),
        settlement: z
          .object({
            competitive_delta: integer.min(-200).max(200),
            newcomer_bonus: integer.min(0).max(600),
            total_delta: integer,
            public_after: rating,
            internal_after: integer,
            remaining_after: integer.min(0).max(1500),
            completed_after: count,
          })
          .nullable(),
      }),
    )
    .refine(
      (rows) =>
        new Set(rows.map((r) => r.user_id)).size === rows.length &&
        rows.every(
          (r) =>
            r.internal_before === r.public_before + r.remaining_before &&
            r.remaining_before === allowance(r.completed_before, r.newcomer_enabled) &&
            (r.answered_count > 0
              ? r.raw_points !== null && r.perf !== null
              : r.raw_points === null && r.perf === null && r.settlement === null) &&
            (!r.settlement ||
              (r.settlement.newcomer_bonus === bonus(r.completed_before, r.newcomer_enabled) &&
                r.settlement.total_delta ===
                  r.settlement.competitive_delta + r.settlement.newcomer_bonus &&
                r.settlement.public_after === r.public_before + r.settlement.total_delta &&
                r.settlement.internal_after ===
                  r.settlement.public_after + r.settlement.remaining_after &&
                r.settlement.remaining_after === r.remaining_before - r.settlement.newcomer_bonus &&
                r.settlement.completed_after === r.completed_before + 1)),
        ),
    ),
  answers: z.array(
    z.object({
      position: count,
      user_id: count.positive(),
      draw: integer.min(5).max(15),
      raw_point_delta: finite,
      perf_delta: finite,
      self_before: count,
      global_before: count,
      effective_multiplier: finite.min(1).max(1.4),
    }),
  ),
})
export type RatingState = z.infer<typeof ratingStateSchema>
