export function afterLoginTarget(value: unknown): string {
  if (
    value === '/changepw/' ||
    value === '/admin/' ||
    value === '/admin/users/' ||
    value === '/admin/dictionary-promotions/' ||
    value === '/leaderboard/' ||
    value === '/game-end-requests/'
  )
    return value
  if (typeof value === 'string') {
    const match =
      /^\/(?:admin\/dicts|user)\/([1-9][0-9]{0,9})\/$/.exec(value) ??
      /^\/game\/([1-9][0-9]{0,9})\/(?:detail\/)?$/.exec(value)
    if (match && Number(match[1]) <= 2147483647) return value
  }
  return '/'
}
