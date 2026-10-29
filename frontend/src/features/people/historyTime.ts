import { z } from 'zod'

const timestamp = z.string().datetime({ offset: true })

// UTC/offset timestamps remain the stored facts. Only their visible text is
// localized; never guess the timezone of an unqualified or malformed value.
export function localHistoryTime(value: string | null): { text: string; datetime: string | null } {
  if (value === null) return { text: '时间未记录', datetime: null }
  if (!timestamp.safeParse(value).success) return { text: '时间无效', datetime: null }
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return { text: '时间无效', datetime: null }
  return {
    text: new Intl.DateTimeFormat(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).format(date),
    datetime: value,
  }
}
