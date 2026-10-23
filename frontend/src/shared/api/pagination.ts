import { z } from 'zod'

export const paginationSchema = z
  .object({
    page: z.number().int().positive(),
    per_page: z.number().int().min(1).max(100),
    total: z.number().int().nonnegative(),
    pages: z.number().int().positive(),
  })
  .refine(
    (value) =>
      value.page <= value.pages &&
      value.pages === Math.max(1, Math.ceil(value.total / value.per_page)),
    'Invalid pagination',
  )
export type Pagination = z.infer<typeof paginationSchema>
export type ListQuery = { page: number; perPage: number; query: string }
export type PageResult<T> = { items: T[]; pagination: Pagination }

export function listQueryString(query: ListQuery) {
  return new URLSearchParams({
    page: String(query.page),
    per_page: String(query.perPage),
    q: query.query,
  }).toString()
}
