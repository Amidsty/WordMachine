import { describe, expect, it } from 'vitest'
import { listQueryString, paginationSchema } from './pagination'

describe('pagination protocol', () => {
  it('accepts empty and last-page metadata', () => {
    expect(paginationSchema.safeParse({ page: 1, pages: 1, per_page: 20, total: 0 }).success).toBe(
      true,
    )
    expect(paginationSchema.safeParse({ page: 2, pages: 2, per_page: 20, total: 21 }).success).toBe(
      true,
    )
  })
  it('rejects missing, oversized and internally inconsistent metadata', () => {
    for (const value of [
      {},
      { page: 1, pages: 1, per_page: 101, total: 0 },
      { page: 2, pages: 1, per_page: 20, total: 0 },
      { page: 1, pages: 2, per_page: 20, total: 0 },
    ])
      expect(paginationSchema.safeParse(value).success).toBe(false)
  })
  it('encodes search text without allowing additional query parameters', () => {
    const query = '苹果 &page=99/%_!'
    const params = new URLSearchParams(listQueryString({ page: 2, perPage: 20, query }))
    expect(params.getAll('page')).toEqual(['2'])
    expect(params.get('q')).toBe(query)
  })
})
