import { z } from 'zod'
import type { ApiClient } from '../../shared/api/client'
import { successSchema, userSchema } from '../../shared/api/contracts'
import { listQueryString, paginationSchema, type ListQuery } from '../../shared/api/pagination'

const leaderSchema = userSchema
  .pick({ id: true, username: true, introduction: true, rating: true })
  .extend({
    rank: z.number().int().min(1).max(100),
    participation_count: z.number().int().min(0).max(2147483647),
  })
export function createPeopleService(client: ApiClient) {
  return {
    async profile(id: number, signal?: AbortSignal) {
      return (
        await client.request(`/api/user/${id}`, successSchema.extend({ user: userSchema }), {
          signal,
        })
      ).user
    },
    async leaders(query: ListQuery, signal?: AbortSignal) {
      const data = await client.request(
        `/api/leaderboard?${listQueryString(query)}`,
        successSchema.extend({
          users: z.array(leaderSchema).max(100),
          pagination: paginationSchema,
        }),
        { signal },
      )
      return { items: data.users, pagination: data.pagination }
    },
  }
}
