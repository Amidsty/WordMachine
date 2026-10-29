const segmenter =
  typeof Intl.Segmenter === 'function'
    ? new Intl.Segmenter(undefined, { granularity: 'grapheme' })
    : null

export function shortIntroduction(value: string | null | undefined): string {
  const text = value?.replace(/\s+/gu, ' ').trim() ?? ''
  if (!text) return '—'
  const characters = segmenter
    ? Array.from(segmenter.segment(text), (item) => item.segment)
    : Array.from(text)
  return characters.length > 30 ? characters.slice(0, 30).join('') + '…' : text
}
