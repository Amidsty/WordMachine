import { z } from 'zod'
import type { ApiClient } from '../../shared/api/client'
import { perfPolicyFields, successSchema } from '../../shared/api/contracts'
import { gameCommandSchema, gameVersionSchema } from '../../shared/api/gameCommand'
import { listQueryString, paginationSchema, type ListQuery } from '../../shared/api/pagination'

import {
  gameIdSchema as id,
  gameNameSchema,
  gamePersonSchema as person,
  gameStatusSchema,
} from '../games/contracts'
export { gameStatusLabels } from '../games/contracts'
export const lobbyGameSchema = z.object({
  id,
  version: gameVersionSchema,
  name: gameNameSchema.nullable().optional(),
  dictid: id.nullable(),
  dictname: z.string().nullable(),
  ...perfPolicyFields,
  status: gameStatusSchema,
  rated: z.boolean(),
  users: z.array(person),
  owner: person.nullable(),
  is_joined: z.boolean(),
  actions: z.object({
    join: z.boolean(),
    leave: z.boolean(),
    start: z.boolean(),
    cancel: z.boolean(),
  }),
})
export type LobbyGame = z.infer<typeof lobbyGameSchema>
export type LobbyAction = 'join' | 'leave' | 'start' | 'cancel'
export type LobbyStatus = 'waiting' | 'running' | 'finished' | 'cancelled'
export const statusLabels: Record<LobbyStatus, string> = {
  waiting: '待开始',
  running: '进行中',
  finished: '已结束',
  cancelled: '已取消',
}
export const actionLabels: Record<LobbyAction, string> = {
  join: '报名',
  leave: '撤销报名',
  start: '开始对局',
  cancel: '取消对局',
}

export function createLobbyService(client: ApiClient) {
  return {
    async list(query: ListQuery, status: LobbyStatus, signal?: AbortSignal) {
      const data = await client.request(
        `/api/game/list?${listQueryString(query)}&status=${status}`,
        successSchema.extend({
          games: z.array(lobbyGameSchema).max(100),
          pagination: paginationSchema,
          active_game_id: id.nullable(),
        }),
        { signal },
      )
      return { items: data.games, pagination: data.pagination, activeGameId: data.active_game_id }
    },
    create(dictId: number, actorId: number, requestId: string, signal?: AbortSignal, rated = true) {
      return client.request(
        '/api/game/create',
        gameCommandSchema(requestId).extend({ game_id: id }),
        {
          method: 'POST',
          body: { dict_id: dictId, rated, request_id: requestId },
          expectedUserId: actorId,
          signal,
        },
      )
    },
    act(
      game: Pick<LobbyGame, 'id' | 'version'>,
      action: LobbyAction,
      actorId: number,
      requestId: string,
      signal?: AbortSignal,
    ) {
      return client.request(`/api/game/${game.id}/${action}`, gameCommandSchema(requestId), {
        method: 'POST',
        body: { request_id: requestId, expected_version: game.version },
        expectedUserId: actorId,
        signal,
      })
    },
  }
}
