import { afterEach, describe, expect, it, vi } from 'vitest'
import { gameCommandSchema, gameVersionSchema, newGameRequestId } from './gameCommand'

afterEach(() => vi.unstubAllGlobals())

describe('game command metadata', () => {
  it('prefers native randomUUID and preserves its Crypto receiver', () => {
    const id = '01234567-89ab-4cde-8fab-0123456789ab'
    const provider = {
      randomUUID: vi.fn(function (this: unknown) {
        expect(this).toBe(provider)
        return id
      }),
      getRandomValues: vi.fn(),
    }
    vi.stubGlobal('crypto', provider)
    expect(newGameRequestId()).toBe(id)
    expect(provider.randomUUID).toHaveBeenCalledOnce()
    expect(provider.getRandomValues).not.toHaveBeenCalled()
  })

  it('falls back without randomUUID and preserves byte order and leading zeros', () => {
    const provider = {
      getRandomValues: vi.fn(function (this: unknown, bytes: Uint8Array) {
        expect(this).toBe(provider)
        expect(bytes).toBeInstanceOf(Uint8Array)
        expect(bytes).toHaveLength(16)
        bytes.set(Array.from({ length: 16 }, (_, index) => index))
        return bytes
      }),
    }
    vi.stubGlobal('crypto', provider)
    expect(newGameRequestId()).toBe('00010203-0405-4607-8809-0a0b0c0d0e0f')
    expect(provider.getRandomValues).toHaveBeenCalledOnce()
  })

  it('clears the version and variant bits rather than only setting them', () => {
    vi.stubGlobal('crypto', { getRandomValues: (bytes: Uint8Array) => bytes.fill(255) })
    expect(newGameRequestId()).toBe('ffffffff-ffff-4fff-bfff-ffffffffffff')
  })

  it('uses fresh cryptographic bytes on each fallback call', () => {
    const getRandomValues = vi.fn(globalThis.crypto.getRandomValues.bind(globalThis.crypto))
    vi.stubGlobal('crypto', { getRandomValues })
    const first = newGameRequestId()
    const second = newGameRequestId()
    const v4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
    expect(first).toMatch(v4)
    expect(second).toMatch(v4)
    expect(first).not.toBe(second)
    expect(getRandomValues).toHaveBeenCalledTimes(2)
  })

  it.each([undefined, {}])('fails closed without a secure random generator (%j)', (crypto) => {
    vi.stubGlobal('crypto', crypto)
    expect(newGameRequestId).toThrow('secure random number generator')
  })

  it('creates distinct v4 IDs and accepts only matching successful receipts', () => {
    const requestId = newGameRequestId()
    const other = newGameRequestId()
    expect(requestId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    )
    expect(other).not.toBe(requestId)
    expect(
      gameCommandSchema(requestId).safeParse({ success: true, request_id: requestId, version: 0 })
        .success,
    ).toBe(true)
    expect(
      gameCommandSchema(requestId).safeParse({ success: true, request_id: other, version: 0 })
        .success,
    ).toBe(false)
  })
  it('rejects missing or invalid versions rather than guessing zero', () => {
    for (const value of [undefined, null, -1, true, '0', 1.5, 2147483648]) {
      expect(gameVersionSchema.safeParse(value).success).toBe(false)
    }
    expect(gameVersionSchema.parse(2147483647)).toBe(2147483647)
  })
})
