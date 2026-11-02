import { z } from 'zod'

const rating = z.number().int().min(-2147483648).max(2147483647).nullable()
export const scorePointSchema = z
  .object({
    key: z
      .string()
      .regex(/^(game|manual):[1-9]\d*$/)
      .max(40),
    kind: z.enum(['rated', 'unrated', 'manual']),
    game_id: z.number().int().positive().max(2147483647).nullable(),
    game_name: z.string().nullable(),
    game_available: z.boolean(),
    recorded_at: z.string().datetime({ offset: true }).nullable(),
    rating,
    rating_origin: z.enum(['recorded', 'carried', 'unknown']),
    perf: z.number().finite().nullable(),
    perf_missing: z.enum(['no_answers', 'missing_perf', 'not_applicable']).nullable(),
  })
  .superRefine((point, context) => {
    const manual = point.kind === 'manual'
    if (
      (manual
        ? point.game_id !== null || !point.key.startsWith('manual:') || point.game_available
        : point.key !== `game:${point.game_id}` || point.game_id === null) ||
      (manual &&
        (point.perf !== null ||
          point.perf_missing !== 'not_applicable' ||
          point.rating_origin === 'carried')) ||
      (!manual && point.perf_missing === 'not_applicable') ||
      (point.rating === null) !== (point.rating_origin === 'unknown') ||
      (point.perf === null) !== (point.perf_missing !== null) ||
      (point.kind === 'unrated' && point.rating_origin === 'recorded')
    )
      context.addIssue({ code: 'custom', message: 'Inconsistent score timeline point' })
  })
export const scorePointsSchema = z
  .array(scorePointSchema)
  .refine(
    (points) => new Set(points.map((point) => point.key)).size === points.length,
    'Duplicate timeline point',
  )
export type ScorePoint = z.infer<typeof scorePointSchema>
// Exhaustive field list: adding a public point field must also invalidate an
// unchanged-response cache when that field changes. Never skip API validation.
const pointFields: Record<keyof ScorePoint, true> = {
  key: true,
  kind: true,
  game_id: true,
  game_name: true,
  game_available: true,
  recorded_at: true,
  rating: true,
  rating_origin: true,
  perf: true,
  perf_missing: true,
}
const pointKeys = Object.keys(pointFields) as (keyof ScorePoint)[]
export function sameScorePoints(
  previous: readonly ScorePoint[] | null,
  next: readonly ScorePoint[],
) {
  return (
    previous !== null &&
    previous.length === next.length &&
    previous.every((point, index) =>
      pointKeys.every((key) => Object.is(point[key], next[index]![key])),
    )
  )
}

export type ChartMode = 'rated' | 'all'
export const kindLabels = { rated: 'Rated', unrated: 'Unrated', manual: '人工调分' }

export function chartPoints(points: ScorePoint[], mode: ChartMode) {
  return points.filter((point) => mode === 'all' || point.kind !== 'unrated')
}

export function geometry(points: ScorePoint[], width: number) {
  const left = 68,
    right = Math.max(left + 120, width - 18),
    top = 20,
    bottom = 282
  const dated = points.filter((point) => point.recorded_at !== null)
  // No spread of the entire history into Math.min/max (argument-stack limits).
  let scale = 1,
    minTime = Infinity,
    maxTime = -Infinity
  for (const point of dated) {
    for (const value of [point.rating, point.perf])
      if (value !== null) scale = Math.max(scale, Math.abs(value))
    const time = Date.parse(point.recorded_at!)
    minTime = Math.min(minTime, time)
    maxTime = Math.max(maxTime, time)
  }
  let low = Infinity,
    high = -Infinity
  for (const point of dated)
    for (const value of [point.rating, point.perf]) {
      if (value !== null) {
        low = Math.min(low, value / scale)
        high = Math.max(high, value / scale)
      }
    }
  if (!Number.isFinite(low)) {
    low = 0
    high = 100 / scale
  }
  const span = Math.max(high - low, 100 / scale, 0.02)
  low = Math.max(-Number.MAX_VALUE / scale, low - span * 0.08)
  high = Math.min(Number.MAX_VALUE / scale, high + span * 0.08)
  const y = (value: number) => bottom - ((value / scale - low) / (high - low)) * (bottom - top)
  const x = (time: number) =>
    minTime === maxTime
      ? (left + right) / 2
      : left + ((time - minTime) / (maxTime - minTime)) * (right - left)
  const nodes = dated.map((point) => ({
    point,
    x: x(Date.parse(point.recorded_at!)),
    ratingY: point.rating === null ? null : y(point.rating),
    perfY: point.perf === null ? null : y(point.perf),
  }))
  function line(kind: 'ratingY' | 'perfY') {
    let path = '',
      connected = false
    for (const node of nodes) {
      const value = node[kind]
      if (value === null) {
        // Perf explicitly bridges gaps. An unknown Rating is not a known balance.
        if (kind === 'ratingY') connected = false
        continue
      }
      path += `${connected ? 'L' : 'M'}${node.x.toFixed(2)},${value.toFixed(2)} `
      connected = true
    }
    return path.trim()
  }
  const thresholds = [-Infinity, 1200, 1400, 1600, 1900, 2100, 2400, 3000, Infinity]
  const colors = [
    '#eeeeee',
    '#daf0d5',
    '#d4f2ee',
    '#dce8ff',
    '#ebddf5',
    '#ffebcf',
    '#f7d9dc',
    '#f3c4cc',
  ]
  const bands = colors
    .map((color, index) => {
      const a = Math.max(top, y(thresholds[index + 1]!)),
        b = Math.min(bottom, y(thresholds[index]!))
      return { color, y: a, height: Math.max(0, b - a) }
    })
    .filter((band) => band.height > 0)
  const ticks = Array.from({ length: 6 }, (_, index) => {
    const position = index / 5
    return { y: bottom - position * (bottom - top), value: (low + (high - low) * position) * scale }
  })
  const timeTicks = !dated.length
    ? []
    : minTime === maxTime
      ? [{ x: x(minTime), value: minTime }]
      : [minTime, maxTime].map((value) => ({ x: x(value), value }))
  return {
    left,
    right,
    top,
    bottom,
    nodes,
    bands,
    ticks,
    timeTicks,
    ratingPath: line('ratingY'),
    perfPath: line('perfY'),
  }
}

type ChartNode = ReturnType<typeof geometry>['nodes'][number]
type HoverColumn = { x: number; marks: { y: number; key: string }[] }

// A separate hit-test index; never reorder/drop points in the actual graph.
// Equal-time records use the nearest saved Rating/Perf vertically. Completely
// coincident marks select the first record; all remain available in the select.
export function createHoverIndex(nodes: readonly ChartNode[]): HoverColumn[] {
  const columns = new Map<number, Map<number, string>>()
  for (const node of nodes) {
    for (const y of [node.ratingY, node.perfY]) {
      if (y === null) continue
      let marks = columns.get(node.x)
      if (!marks) columns.set(node.x, (marks = new Map()))
      if (!marks.has(y)) marks.set(y, node.point.key)
    }
  }
  return [...columns]
    .map(([x, marks]) => ({
      x,
      marks: [...marks].map(([y, key]) => ({ y, key })).sort((a, b) => a.y - b.y),
    }))
    .sort((a, b) => a.x - b.x)
}

function neighbours<T>(items: readonly T[], value: number, position: (item: T) => number) {
  let low = 0,
    high = items.length
  while (low < high) {
    const middle = Math.floor((low + high) / 2)
    if (position(items[middle]!) < value) low = middle + 1
    else high = middle
  }
  return [items[low - 1], items[low]].filter((item): item is T => item !== undefined)
}

export function nearestHoverKey(columns: readonly HoverColumn[], x: number, y: number) {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return undefined
  let key: string | undefined
  let dx = Infinity,
    dy = Infinity
  for (const column of neighbours(columns, x, (column) => column.x)) {
    const distanceX = Math.abs(column.x - x)
    for (const mark of neighbours(column.marks, y, (mark) => mark.y)) {
      const distanceY = Math.abs(mark.y - y)
      if (distanceX < dx || (distanceX === dx && distanceY < dy)) {
        key = mark.key
        dx = distanceX
        dy = distanceY
      }
    }
  }
  return key
}

export function axisNumber(value: number) {
  if (Math.abs(value) >= 1e6) return value.toExponential(1)
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value)
}
