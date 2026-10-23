import { z } from 'zod'
import type { ApiClient } from '../../shared/api/client'
import { successSchema, multiplierSchema } from '../../shared/api/contracts'
import { listQueryString, paginationSchema, type ListQuery } from '../../shared/api/pagination'

const id = z.number().int().positive()
const rating = z.number().int().min(-2147483648).max(2147483647)
export const promotionSchema = z.object({
  request_id: z.string().uuid(),
  dict_id: id,
  applicant_id: id,
  reason: z.string(),
  state: z.union([z.literal(0), z.literal(1), z.literal(2)]),
  reviewer_id: id.nullable(),
  reviewer_level: z.number().int().min(4).max(5).nullable(),
  review_reason: z.string().nullable(),
  rated_min: rating.nullable(),
  rated_max: rating.nullable(),
  result_version: z.number().int().positive().nullable(),
  submitted_at: z.string(),
  reviewed_at: z.string().nullable(),
})
export const promotionReviewSchema = successSchema.extend({
  application: promotionSchema,
  dict: z.object({
    id,
    dictname: z.string().nullable(),
    ownerid: id.nullable(),
    deleted: z.number().int(),
    multiplier: multiplierSchema,
    difficulty: z.number().int().min(0).max(4000).optional(),
    config_version: z.number().int().nonnegative(),
    rated_min: rating,
    rated_max: rating,
  }),
  review_token: z.string().nullable(),
  word_count: z.number().int().nonnegative().nullable(),
})
export type Promotion = z.infer<typeof promotionSchema>
export type PromotionReview = z.infer<typeof promotionReviewSchema>
export type PromotionDecision =
  | { approve: false; reason: string }
  | { approve: true; reason: string; rated_min: number; rated_max: number; review_token: string }
export function createPromotionService(client: ApiClient) {
  return {
    async list(query: ListQuery, signal?: AbortSignal) {
      const result = await client.request(
        `/api/dictionary-promotions?${listQueryString(query)}`,
        successSchema.extend({
          applications: z.array(promotionSchema.extend({ dictname: z.string().nullable() })),
          pagination: paginationSchema,
        }),
        { signal },
      )
      return { items: result.applications, pagination: result.pagination }
    },
    submit(
      dictId: number,
      body: { request_id: string; expected_version: number; reason: string },
      actorId: number,
      signal?: AbortSignal,
    ) {
      return client.request(
        `/api/dict/${dictId}/promotions`,
        successSchema.extend({
          request_id: z.literal(body.request_id),
          dict_id: z.literal(dictId),
        }),
        { method: 'POST', body, expectedUserId: actorId, signal },
      )
    },
    review(row: Promotion, signal?: AbortSignal) {
      return client.request(
        `/api/dict/${row.dict_id}/promotions/${row.request_id}`,
        promotionReviewSchema.refine(
          (result) =>
            result.application.request_id === row.request_id &&
            result.application.dict_id === row.dict_id &&
            result.dict.id === row.dict_id,
        ),
        { signal },
      )
    },
    decide(row: Promotion, body: PromotionDecision, actorId: number, signal?: AbortSignal) {
      return client.request(
        `/api/dict/${row.dict_id}/promotions/${row.request_id}`,
        successSchema
          .extend({ application: promotionSchema })
          .refine(
            (result) =>
              result.application.request_id === row.request_id &&
              result.application.dict_id === row.dict_id &&
              result.application.state === (body.approve ? 1 : 2),
          ),
        { method: 'POST', body, expectedUserId: actorId, signal },
      )
    },
  }
}
