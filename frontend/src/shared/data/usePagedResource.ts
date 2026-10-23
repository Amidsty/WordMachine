import { onScopeDispose, ref, shallowRef } from 'vue'
import type { ListQuery, PageResult } from '../api/pagination'
import { errorMessage } from '../forms/useFormTask'

export function usePagedResource<T>(
  loader: (query: ListQuery, signal: AbortSignal) => Promise<PageResult<T>>,
) {
  const page = ref(1)
  const perPage = ref(20)
  const query = ref('')
  const result = shallowRef<PageResult<T> | null>(null)
  const loading = ref(false)
  const error = ref('')
  // Search input is a draft: paging/refreshing must retain the last submitted filter.
  let appliedQuery = ''
  let revision = 0
  let controller: AbortController | undefined
  onScopeDispose(() => {
    revision++
    controller?.abort()
  })

  async function fetchPage(keepRows: boolean) {
    const current = ++revision
    controller?.abort()
    controller = new AbortController()
    loading.value = true
    error.value = ''
    if (!keepRows) result.value = null
    try {
      const data = await loader(
        { page: page.value, perPage: perPage.value, query: appliedQuery },
        controller.signal,
      )
      if (current !== revision) return
      result.value = data
      page.value = data.pagination.page
    } catch (cause) {
      if (current === revision) {
        result.value = null
        error.value = errorMessage(cause)
      }
    } finally {
      if (current === revision) loading.value = false
    }
  }
  function load() {
    return fetchPage(false)
  }
  function refresh() {
    return loading.value ? Promise.resolve() : fetchPage(true)
  }
  function search() {
    appliedQuery = query.value.trim()
    page.value = 1
    return load()
  }
  function goToPage(value: number) {
    page.value = value
    return load()
  }
  return { page, perPage, query, result, loading, error, load, refresh, search, goToPage }
}
