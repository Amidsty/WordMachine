import { z } from 'zod'
import { successSchema } from './contracts'

export const gameVersionSchema = z.number().int().min(0).max(2147483647)

export function gameCommandSchema(requestId: string) {
  return successSchema.extend({ request_id: z.literal(requestId), version: gameVersionSchema })
}

// One UUID per intent. Keep it with the original payload when manually retrying;
// never reuse it for a changed command, or automatically replay a failed write.
export function newGameRequestId() {
  const crypto = globalThis.crypto
  if (typeof crypto?.randomUUID === 'function') return crypto.randomUUID()
  // randomUUID requires a secure context; getRandomValues also works on LAN HTTP.
  // Never substitute Math.random or timestamps for cryptographic randomness.
  if (typeof crypto?.getRandomValues !== 'function') {
    throw new Error('This browser does not provide a secure random number generator')
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  // These indices exist in the fixed-size 16-byte UUID buffer.
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
