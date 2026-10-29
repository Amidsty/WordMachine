import { z } from 'zod'
import { ratingStateSchema } from '../games/weighted'
import type { ApiClient } from '../../shared/api/client'
import { successSchema } from '../../shared/api/contracts'
import { listQueryString, paginationSchema, type ListQuery } from '../../shared/api/pagination'

export type HistoryKind = 'rating' | 'perf'
const integer = z.number().int().min(-2147483648).max(2147483647)
const common = z.object({
  game_id: z.number().int().positive().nullable(),
  game_name: z.string().nullable(),
  recorded_at: z.string().nullable(),
})
export const ratingHistorySchema = common
  .extend({
    source: z.enum(['legacy', 'game', 'manual']),
    reason: z
      .string()
      .min(1)
      .refine((value) => Array.from(value).length <= 500)
      .optional(),
    actor_id: z.number().int().positive().optional(),
    game_available: z.boolean(),
    before: integer.nullable(),
    delta: z.number().int().min(-4294967295).max(4294967295).nullable(),
    after: integer.nullable(),
    rule_version: z.string().nullable().optional(),
    competitive_delta: z.number().int().min(-200).max(200).nullable().optional(),
    newcomer_bonus: z.number().int().min(0).max(600).nullable().optional(),
  })
  .refine(
    (row) => row.source === 'manual' || (row.reason === undefined && row.actor_id === undefined),
  )
  .refine((row) =>
    ['weighted-rating-v1', 'weighted-rating-v2'].includes(row.rule_version ?? '')
      ? row.source === 'game' &&
        row.competitive_delta != null &&
        row.newcomer_bonus != null &&
        row.delta === row.competitive_delta + row.newcomer_bonus &&
        row.before !== null &&
        row.after !== null &&
        row.after === row.before + row.delta
      : row.competitive_delta == null && row.newcomer_bonus == null,
  )
export const perfHistorySchema = common.extend({
  game_id: z.number().int().positive(),
  source: z.enum(['legacy', 'answers']),
  rated: z.boolean(),
  perf: z.number().finite().nullable(),
  answered_count: z.number().int().nonnegative(),
  rule_version: z.string().nullable().optional(),
  missing_reason: z.enum(['no_answers', 'missing_perf']).nullable(),
})
export type RatingHistory = z.infer<typeof ratingHistorySchema>
export type PerfHistory = z.infer<typeof perfHistorySchema>
export function createHistoryService(client: ApiClient) {
  const envelope = (uid: number, kind: HistoryKind) =>
    successSchema.extend({
      user_id: z.literal(uid),
      kind: z.literal(kind),
      current_rating: integer.nullable(),
      pagination: paginationSchema,
    })
  return {
    account(uid: number, signal?: AbortSignal) {
      return client.request(
        `/api/user/${uid}/rating-state`,
        successSchema.extend({ user_id: z.literal(uid), rating_state: ratingStateSchema }),
        { signal },
      )
    },
    async ratings(uid: number, query: ListQuery, signal?: AbortSignal) {
      const data = await client.request(
        `/api/user/${uid}/history?kind=rating&${listQueryString(query)}`,
        envelope(uid, 'rating').extend({ history: z.array(ratingHistorySchema) }),
        { signal },
      )
      return { items: data.history, pagination: data.pagination }
    },
    async perfs(uid: number, query: ListQuery, signal?: AbortSignal) {
      const data = await client.request(
        `/api/user/${uid}/history?kind=perf&${listQueryString(query)}`,
        envelope(uid, 'perf').extend({ history: z.array(perfHistorySchema) }),
        { signal },
      )
      return { items: data.history, pagination: data.pagination }
    },
  }
}
