import { z } from 'zod'
import type { ApiClient } from '../../shared/api/client'
import { multiplierSchema, successSchema } from '../../shared/api/contracts'
import { listQueryString, paginationSchema, type ListQuery } from '../../shared/api/pagination'

const id = z.number().int().positive()
const dictionaryFields = z.object({
  id,
  dictname: z.string().nullable(),
  ownerid: id.nullable(),
  can_manage: z.boolean(),
  rated_min: z.number().int().min(-2147483648).max(2147483647),
  rated_max: z.number().int().min(-2147483648).max(2147483647),
  can_create_rated: z.boolean(),
  multiplier: multiplierSchema.optional(),
  difficulty: z.number().int().min(0).max(4000).optional(),
  config_version: z.number().int().min(0).max(2147483647).optional(),
})
export const dictionarySchema = dictionaryFields.refine(
  (value) => value.rated_min <= value.rated_max,
)
export const dictionarySummarySchema = dictionaryFields
  .extend({
    word_count: z.number().int().nonnegative(),
  })
  .refine((value) => value.rated_min <= value.rated_max)
export const wordSchema = z.object({
  id,
  dictid: id,
  english: z.string().nullable(),
  chinese: z.string().nullable(),
})
export const csvErrorsSchema = z.object({
  errors: z.array(z.object({ line: z.number().int().positive(), message: z.string() })).max(50),
})
export const csvLimitsSchema = z.object({
  max_bytes: z.number().int().positive(),
  max_rows: z.number().int().positive(),
})
export type CsvLimits = z.infer<typeof csvLimitsSchema>
export type Dictionary = z.infer<typeof dictionarySchema>
export type DictionarySummary = z.infer<typeof dictionarySummarySchema>
export type Word = z.infer<typeof wordSchema>
export type WordInput = { english: string; chinese: string }
const rangeIndex = z.number().int().min(1).max(2147483647)
export const wordRangeSchema = successSchema.extend({
  dict_id: id,
  dictname: z.string().nullable(),
  l: rangeIndex,
  r: rangeIndex,
  count: rangeIndex,
  total: z.number().int().nonnegative(),
  confirmation_token: z.string().min(1).max(2048),
  expires_in: z.number().int().positive(),
  words: z
    .array(
      z.object({
        position: rangeIndex,
        id: z.number().int(),
        english: z.string().nullable(),
        chinese: z.string().nullable(),
      }),
    )
    .min(1)
    .max(10),
})
export type WordRangePreview = z.infer<typeof wordRangeSchema>

export function createDictionaryService(client: ApiClient) {
  return {
    async list(query: ListQuery, signal?: AbortSignal) {
      const data = await client.request(
        `/api/dicts?${listQueryString(query)}`,
        successSchema.extend({
          dicts: z.array(dictionarySummarySchema),
          pagination: paginationSchema,
        }),
        { signal },
      )
      return { items: data.dicts, pagination: data.pagination }
    },
    async get(dictId: number, signal?: AbortSignal) {
      return client.request(
        `/api/dict/${dictId}`,
        successSchema.extend({ dict: dictionarySchema, csv_limits: csvLimitsSchema }),
        { signal },
      )
    },
    async words(dictId: number, query: ListQuery, signal?: AbortSignal) {
      const data = await client.request(
        `/api/dict/${dictId}/words?${listQueryString(query)}`,
        successSchema.extend({ words: z.array(wordSchema), pagination: paginationSchema }),
        { signal },
      )
      return { items: data.words, pagination: data.pagination }
    },
    create(dictname: string, actorId: number, signal?: AbortSignal, multiplier = '1.00') {
      return client.request('/api/dict', successSchema.extend({ dict_id: id }), {
        method: 'POST',
        body: { dictname, multiplier },
        expectedUserId: actorId,
        signal,
      })
    },
    setRatedBounds(
      dictId: number,
      lower: number,
      upper: number,
      expectedVersion: number,
      reason: string,
      actorId: number,
      signal?: AbortSignal,
    ) {
      return client.request(`/api/dict/${dictId}/rated-bounds`, successSchema, {
        method: 'PUT',
        body: { rated_min: lower, rated_max: upper, expected_version: expectedVersion, reason },
        expectedUserId: actorId,
        signal,
      })
    },
    setDifficulty(
      dictId: number,
      difficulty: number,
      expectedVersion: number,
      reason: string,
      actorId: number,
      signal?: AbortSignal,
    ) {
      return client.request(`/api/dict/${dictId}/difficulty`, successSchema, {
        method: 'PUT',
        body: { difficulty, expected_version: expectedVersion, reason },
        expectedUserId: actorId,
        signal,
      })
    },
    setMultiplier(
      dictId: number,
      multiplier: string,
      expectedVersion: number,
      reason: string,
      actorId: number,
      signal?: AbortSignal,
    ) {
      return client.request(`/api/dict/${dictId}/multiplier`, successSchema, {
        method: 'PUT',
        body: { multiplier, expected_version: expectedVersion, reason },
        expectedUserId: actorId,
        signal,
      })
    },
    rename(dictId: number, dictname: string, actorId: number, signal?: AbortSignal) {
      return client.request(`/api/dict/${dictId}`, successSchema, {
        method: 'PUT',
        body: { dictname },
        expectedUserId: actorId,
        signal,
      })
    },
    remove(dictId: number, actorId: number, signal?: AbortSignal) {
      return client.request(`/api/dict/${dictId}`, successSchema, {
        method: 'DELETE',
        body: {},
        expectedUserId: actorId,
        signal,
      })
    },
    saveWord(
      dictId: number,
      wordId: number | null,
      data: WordInput,
      actorId: number,
      signal?: AbortSignal,
    ) {
      return client.request(
        wordId ? `/api/word/${wordId}` : `/api/dict/${dictId}/word`,
        successSchema,
        { method: wordId ? 'PUT' : 'POST', body: data, expectedUserId: actorId, signal },
      )
    },
    removeWord(wordId: number, actorId: number, signal?: AbortSignal) {
      return client.request(`/api/word/${wordId}`, successSchema, {
        method: 'DELETE',
        body: {},
        expectedUserId: actorId,
        signal,
      })
    },
    previewRange(dictId: number, l: number, r: number, actorId: number, signal?: AbortSignal) {
      return client.request(
        `/api/dict/${dictId}/words/delete-range/preview`,
        wordRangeSchema
          .extend({
            dict_id: z.literal(dictId),
            l: z.literal(l),
            r: z.literal(r),
            count: z.literal(r - l + 1),
          })
          .refine(
            (data) =>
              data.total >= r &&
              data.words[0]?.position === l &&
              data.words.at(-1)?.position === r &&
              data.words.every(
                (word, index) =>
                  word.position >= l &&
                  word.position <= r &&
                  (index === 0 || word.position > data.words[index - 1]!.position),
              ),
          ),
        { method: 'POST', body: { l, r }, expectedUserId: actorId, signal },
      )
    },
    deleteRange(preview: WordRangePreview, actorId: number, signal?: AbortSignal) {
      return client.request(
        `/api/dict/${preview.dict_id}/words/delete-range`,
        successSchema.extend({
          dict_id: z.literal(preview.dict_id),
          l: z.literal(preview.l),
          r: z.literal(preview.r),
          deleted_count: z.literal(preview.count),
        }),
        {
          method: 'POST',
          body: { confirmation_token: preview.confirmation_token },
          expectedUserId: actorId,
          signal,
        },
      )
    },
    importCsv(dictId: number, csv: string, actorId: number, signal?: AbortSignal) {
      return client.request(
        `/api/dict/${dictId}/import-csv`,
        successSchema.extend({ count: z.number().int().nonnegative() }),
        { method: 'POST', body: { csv }, expectedUserId: actorId, signal },
      )
    },
    exportCsv(dictId: number, signal?: AbortSignal) {
      return client.request(
        `/api/dict/${dictId}/export-csv`,
        successSchema.extend({ filename: z.string(), content: z.string() }),
        { signal },
      )
    },
  }
}
