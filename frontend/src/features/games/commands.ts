import { z } from 'zod'
import { gameVersionSchema, newGameRequestId } from '../../shared/api/gameCommand'
import { gameIdSchema } from './contracts'

export const gameIntentSchema = z
  .object({
    gameId: gameIdSchema,
    actorId: gameIdSchema,
    request_id: z.string().uuid(),
    expected_version: gameVersionSchema,
  })
  .and(
    z.discriminatedUnion('action', [
      z.object({
        action: z.literal('answer'),
        word_id: gameIdSchema,
        answer: z.string().min(1).max(255),
      }),
      z.object({ action: z.literal('end') }),
    ]),
  )
export type GameIntent = Readonly<z.infer<typeof gameIntentSchema>>
export type NewGameIntent = Omit<GameIntent, 'action' | 'request_id'> &
  ({ action: 'answer'; word_id: number; answer: string } | { action: 'end' })
export function newIntent(input: NewGameIntent): GameIntent {
  return Object.freeze(gameIntentSchema.parse({ ...input, request_id: newGameRequestId() }))
}
export function commandPayload(intent: GameIntent) {
  return {
    request_id: intent.request_id,
    expected_version: intent.expected_version,
    ...(intent.action === 'answer' ? { word_id: intent.word_id, answer: intent.answer } : {}),
  }
}
