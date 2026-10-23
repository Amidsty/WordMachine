import { z } from 'zod'
import { ApiError, type ApiClient } from '../../shared/api/client'
import { successSchema } from '../../shared/api/contracts'
import { gameIdSchema, gameStateSchema } from './contracts'
import { gameCommandSchema } from '../../shared/api/gameCommand'
import { commandPayload, gameIntentSchema, type GameIntent } from './commands'

export function createGameService(client: ApiClient) {
  return {
    rename(
      gameId: number,
      body: { name: string; expected_version: number; request_id: string },
      actorId: number,
      signal?: AbortSignal,
    ) {
      return client.request(
        `/api/game/${gameId}/rename`,
        gameCommandSchema(body.request_id).extend({
          game_id: z.literal(gameId),
          name: z.literal(body.name),
        }),
        { method: 'POST', body, expectedUserId: actorId, signal },
      )
    },
    async command(intent: GameIntent, signal?: AbortSignal) {
      const checked = gameIntentSchema.parse(intent)
      return client.request(
        `/api/game/${checked.gameId}/${checked.action}`,
        gameCommandSchema(checked.request_id),
        {
          method: 'POST',
          body: commandPayload(checked),
          expectedUserId: checked.actorId,
          signal,
        },
      )
    },
    async get(gameId: number, signal?: AbortSignal) {
      if (!gameIdSchema.safeParse(gameId).success)
        throw new ApiError('invalid_parameters', '无效的对局编号。')
      signal?.throwIfAborted()
      const controller = new AbortController()
      const abort = () => controller.abort()
      signal?.addEventListener('abort', abort, { once: true })
      const timeout = setTimeout(abort, 10000)
      try {
        const data = await client.request(
          `/api/game/${gameId}`,
          successSchema.extend({ game: gameStateSchema.refine((game) => game.id === gameId) }),
          { signal: controller.signal },
        )
        return data.game
      } finally {
        clearTimeout(timeout)
        signal?.removeEventListener('abort', abort)
      }
    },
  }
}
