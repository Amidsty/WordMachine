import { effectScope } from 'vue'
import { describe, expect, it } from 'vitest'
import { usePagedResource } from './usePagedResource'
import type { PageResult } from '../api/pagination'

const result = (name: string): PageResult<string> => ({
  items: [name],
  pagination: { page: 1, per_page: 20, total: 1, pages: 1 },
})

describe('paged resources', () => {
  it('ignores late responses even when the transport ignores abort', async () => {
    const scope = effectScope()
    const resolvers: ((value: PageResult<string>) => void)[] = []
    const signals: AbortSignal[] = []
    const list = scope.run(() =>
      usePagedResource<string>((_, signal) => {
        signals.push(signal)
        return new Promise((resolve) => resolvers.push(resolve))
      }),
    )!
    const first = list.load()
    list.query.value = 'new'
    const second = list.search()
    expect(signals[0]?.aborted).toBe(true)
    resolvers[1]!(result('new'))
    await second
    resolvers[0]!(result('old'))
    await first
    expect(list.result.value?.items).toEqual(['new'])
    const third = list.load()
    scope.stop()
    expect(signals[2]?.aborted).toBe(true)
    resolvers[2]!(result('after unmount'))
    await third
    expect(list.result.value).toBeNull()
  })

  it('paging and write reconciliation keep the submitted filter rather than the search draft', async () => {
    const scope = effectScope()
    const queries: string[] = []
    const list = scope.run(() =>
      usePagedResource<string>(async (query) => {
        queries.push(query.query)
        return result('rows')
      }),
    )!
    await list.load()
    list.query.value = ' submitted '
    await list.search()
    list.query.value = 'unfinished draft'
    await list.goToPage(2)
    await list.load()
    expect(queries).toEqual(['', 'submitted', 'submitted', 'submitted'])
    scope.stop()
  })

  it('keeps rows during background reads, skips overlapping refreshes and clears rows on failure', async () => {
    const scope = effectScope()
    let finish!: (value: PageResult<string>) => void
    let calls = 0
    let failed = false
    const list = scope.run(() =>
      usePagedResource<string>(async () => {
        calls++
        if (failed) throw Error('offline')
        if (calls === 1) return result('old')
        return new Promise((resolve) => {
          finish = resolve
        })
      }),
    )!
    await list.load()
    const pending = list.refresh()
    expect(list.result.value?.items).toEqual(['old'])
    await list.refresh()
    expect(calls).toBe(2)
    finish(result('new'))
    await pending
    expect(list.result.value?.items).toEqual(['new'])
    failed = true
    await list.refresh()
    expect(list.result.value).toBeNull()
    scope.stop()
  })

  it('uses server-clamped pages and exposes failed refreshes without retaining stale rows', async () => {
    let fail = false
    const scope = effectScope()
    const list = scope.run(() =>
      usePagedResource<string>(async () => {
        if (fail) throw Error('offline')
        return result('ok')
      }),
    )!
    await list.goToPage(99)
    expect(list.page.value).toBe(1)
    fail = true
    await list.load()
    expect(list.result.value).toBeNull()
    expect(list.error.value).toContain('网络异常')
    scope.stop()
  })
})
