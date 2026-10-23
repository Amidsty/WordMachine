import { z } from 'zod'
import type { ApiClient } from '../../shared/api/client'
import { successSchema } from '../../shared/api/contracts'
import { listQueryString, paginationSchema, type ListQuery } from '../../shared/api/pagination'

export function canManuallyEnd(
  ownerId: number | undefined,
  user: { id: number; admin_level?: number } | null | undefined,
) {
  return (
    !!user &&
    (user.id === ownerId || ((user.admin_level ?? 0) >= 2 && (user.admin_level ?? 0) <= 5))
  )
}
export const endRequestSchema = z.object({
  game_id: z.number().int().positive(),
  request_id: z.string().uuid(),
  message: z.string().min(1).max(1000),
  sent_at: z.string(),
  game_name: z.string().nullable(),
  status: z.union([z.literal(-1), z.literal(0), z.literal(1), z.literal(2)]),
  owner_id: z.number().int().positive().nullable(),
  sender: z.object({
    id: z.number().int().positive(),
    username: z.string().nullable(),
    rating: z.number().nullable(),
  }),
})
export function createEndRequestService(client: ApiClient) {
  return {
    async list(query: ListQuery, signal?: AbortSignal, gameId?: number, includeFinished = false) {
      const path =
        gameId === undefined ? '/api/game-end-requests' : `/api/game/${gameId}/end-requests`
      const data = await client.request(
        `${path}?${listQueryString(query)}&include_finished=${includeFinished}`,
        successSchema.extend({ requests: z.array(endRequestSchema), pagination: paginationSchema }),
        { signal },
      )
      return { items: data.requests, pagination: data.pagination }
    },
    async send(
      gameId: number,
      body: { message: string; request_id: string },
      actorId: number,
      signal?: AbortSignal,
    ) {
      signal?.throwIfAborted()
      const controller = new AbortController()
      const abort = () => controller.abort()
      signal?.addEventListener('abort', abort, { once: true })
      const timeout = setTimeout(abort, 10000)
      try {
        return await client.request(
          `/api/game/${gameId}/end-requests`,
          successSchema.extend({
            game_id: z.literal(gameId),
            sender_id: z.literal(actorId),
            request_id: z.literal(body.request_id),
            message: z.literal(body.message),
            sent_at: z.string(),
            version: z.number().int().nonnegative(),
          }),
          { method: 'POST', body, signal: controller.signal, expectedUserId: actorId },
        )
      } finally {
        clearTimeout(timeout)
        signal?.removeEventListener('abort', abort)
      }
    },
  }
}
