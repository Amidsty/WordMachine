import { describe, expect, it } from 'vitest'
import { gameState } from '../../../testing/gameApi'
import { scoreRows, storedNumber, storedPerf } from './presentation'

describe('Perf display precision', () => {
  it.each([
    [1511.1234567890124, '1511.1'],
    [12, '12.0'],
    [0, '0.0'],
    [-0, '-0.0'],
    [1.24, '1.2'],
    [1.25, '1.3'],
    [1.15, '1.2'],
    [-1.25, '-1.3'],
    [9.95, '10.0'],
    [null, '记录缺失'],
    [undefined, '记录缺失'],
    [NaN, '记录缺失'],
    [Infinity, '记录缺失'],
  ])('formats %s as %s', (value, expected) => {
    expect(storedPerf(value)).toBe(expected)
  })

  it('retains delta signs without changing Rating or combo formatting', () => {
    expect(storedPerf(11.15, true)).toBe('+11.2')
    expect(storedPerf(-11.15, true)).toBe('-11.2')
    expect(storedPerf(0, true)).toBe('0.0')
    expect(storedNumber(7, true)).toBe('+7')
    expect(storedNumber(1507)).toBe('1507')
  })

  it('does not round source records or derived raw Perf', () => {
    const game = gameState(4, 1, 2)
    const before = structuredClone(game)
    const rows = scoreRows(game)
    for (const row of rows) storedPerf(row.perf)
    for (const answer of game.result) {
      storedPerf(answer.perf)
      storedPerf(answer.perf_delta, true)
    }
    expect(game).toEqual(before)
    expect(rows[0]!.perf).toBe(game.result[0]!.perf)
  })
})
