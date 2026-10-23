import { z } from 'zod'
import { ratingStateSchema } from '../games/weighted'
import type { ApiClient } from '../../shared/api/client'
import { successSchema, userSchema } from '../../shared/api/contracts'
import { listQueryString, paginationSchema, type ListQuery } from '../../shared/api/pagination'

export const managedUserSchema = userSchema.extend({
  admin_version: z.number().int().min(0).max(2147483647).optional(),
  capabilities: z
    .object({
      can_edit_profile: z.boolean(),
      can_reset_password: z.boolean(),
      can_ban: z.boolean(),
      can_restore: z.boolean(),
      can_set_level: z.boolean(),
      max_assignable_level: z.number().int().min(0).max(4),
      meets_rating_threshold: z.boolean(),
      can_adjust_rating: z.boolean(),
    })
    .optional(),
  deleted: z
    .union([z.boolean(), z.literal(0), z.literal(1), z.null()])
    .transform((value) => (value === null ? null : Boolean(value))),
})
export type ManagedUser = z.infer<typeof managedUserSchema>
export type UserAction = 'update' | 'level' | 'reset-password' | 'delete' | 'restore'

const ratingValue = z.number().int().min(-2147483648).max(2147483647)
const eventId = z.string().regex(/^[1-9]\d{0,18}$/)
export const ratingReviewSchema = successSchema.extend({
  user_id: z.number().int().positive(),
  rating: ratingValue,
  rating_event_id: eventId.nullable(),
  running_game: z.boolean(),
  rating_state: ratingStateSchema.optional(),
  events: z.array(
    z.object({
      id: eventId,
      kind: z.enum(['game', 'manual']),
      sequence: z.number().int().positive(),
      rating_before: ratingValue,
      delta: z.number().int().min(-4294967295).max(4294967295),
      rating_after: ratingValue,
      game_id: z.number().int().positive().nullable(),
      actor_id: z.number().int().positive().nullable(),
      reason: z.string().nullable(),
      recorded_at: z.string(),
    }),
  ),
})
export type RatingReview = z.infer<typeof ratingReviewSchema>
export type RatingIntent = Readonly<{
  request_id: string
  expected_rating: number
  expected_event_id: string | null
  new_rating: number
  reason: string
}>

export function createUserManagementService(client: ApiClient) {
  return {
    async get(uid: number, signal?: AbortSignal) {
      const result = await client.request(
        `/api/admin/user/${uid}`,
        successSchema.extend({
          user: managedUserSchema.extend({ id: z.literal(uid) }),
        }),
        { signal },
      )
      return result.user
    },
    reviewRating(uid: number, signal?: AbortSignal) {
      return client.request(
        `/api/admin/user/${uid}/rating`,
        ratingReviewSchema.extend({ user_id: z.literal(uid) }),
        { signal },
      )
    },
    adjustRating(
      uid: number,
      intent: RatingIntent,
      password: string,
      actorId: number,
      signal?: AbortSignal,
    ) {
      return client.request(
        `/api/admin/user/${uid}/rating`,
        successSchema.extend({
          request_id: z.literal(intent.request_id),
          user_id: z.literal(uid),
          rating_before: z.literal(intent.expected_rating),
          rating_after: z.literal(intent.new_rating),
          delta: z.literal(intent.new_rating - intent.expected_rating),
          rating_event_id: eventId,
        }),
        {
          method: 'POST',
          body: { ...intent, current_password: password },
          expectedUserId: actorId,
          signal,
        },
      )
    },
    async list(query: ListQuery, includeDeleted: boolean, signal?: AbortSignal) {
      const data = await client.request(
        `/api/admin/users?${listQueryString(query)}&include_deleted=${includeDeleted}`,
        successSchema.extend({ users: z.array(managedUserSchema), pagination: paginationSchema }),
        { signal },
      )
      return { items: data.users, pagination: data.pagination }
    },
    update(
      uid: number,
      body: { username: string; introduction: string },
      actorId: number,
      signal?: AbortSignal,
    ) {
      return client.request(`/api/admin/user/${uid}/update`, successSchema, {
        method: 'POST',
        body,
        expectedUserId: actorId,
        signal,
      })
    },
    setLevel(
      uid: number,
      level: number,
      version: number,
      reason: string,
      actorId: number,
      signal?: AbortSignal,
    ) {
      return client.request(`/api/admin/user/${uid}/level`, successSchema, {
        method: 'POST',
        body: { admin_level: level, expected_version: version, reason },
        expectedUserId: actorId,
        signal,
      })
    },
    act(
      uid: number,
      action: Exclude<UserAction, 'update' | 'level'>,
      actorId: number,
      password?: string,
      signal?: AbortSignal,
    ) {
      return client.request(`/api/admin/user/${uid}/${action}`, successSchema, {
        method: 'POST',
        body: action === 'reset-password' ? { new_password: password } : {},
        expectedUserId: actorId,
        signal,
      })
    },
  }
}
