// In-memory API fixture for component/browser interaction tests only.
// This is NOT a replacement for backend permissions, CSV parsing, or MySQL tests.
export function createManagementApi(root = false) {
  const actor = {
    id: root ? 3 : 1,
    username: root ? 'root-user' : 'owner',
    introduction: '',
    rating: 1500,
    type: root ? 'root' : 'normal',
    admin_level: root ? 5 : 0,
  }
  const dicts = [
    { id: 1, dictname: 'System', ownerid: null as number | null },
    { id: 2, dictname: 'Owned <img src=x>', ownerid: 1 as number | null },
    { id: 3, dictname: 'Shared', ownerid: 2 as number | null },
  ].map((dict) => ({ ...dict, multiplier: '1.00', config_version: 0 }))
  const words = [{ id: 11, dictid: 2, english: 'apple', chinese: '苹果' }]
  const users = [
    {
      id: 1,
      username: 'owner',
      introduction: '',
      rating: 1500,
      type: 'normal',
      admin_level: 0,
      admin_version: 0,
      deleted: 0,
    },
    {
      id: 2,
      username: '<script>other</script>',
      introduction: '<img src=x>',
      rating: 1600,
      type: 'normal',
      admin_level: 0,
      admin_version: 0,
      deleted: 0,
    },
    {
      id: 3,
      username: 'root-user',
      introduction: '',
      rating: 1700,
      type: 'root',
      admin_level: 5,
      admin_version: 0,
      deleted: 0,
    },
  ]
  const writes: { path: string; method: string; body: Record<string, unknown> }[] = []
  const state = { failWords: false, rejectWrites: false }
  const csvLimits = { max_bytes: 512 * 1024, max_rows: 5000 }
  const session = () => ({
    success: true,
    authenticated: true,
    user: actor,
    csrf_token: 'test-csrf',
  })
  const canManage = (ownerid: number | null) =>
    ownerid === actor.id || actor.admin_level === 5 || (ownerid === null && actor.admin_level >= 3)
  const capabilities = (user: (typeof users)[number]) => {
    const lower = actor.admin_level > user.admin_level && user.id !== actor.id
    return {
      can_edit_profile: root && (lower || user.id === actor.id),
      can_reset_password: lower,
      can_ban: lower && !user.deleted,
      can_restore: lower && !!user.deleted,
      can_set_level: lower && !user.deleted,
      max_assignable_level: Math.max(0, actor.admin_level - 1),
      meets_rating_threshold: actor.admin_level >= 4 && (lower || user.id === actor.id),
      can_adjust_rating: actor.admin_level >= 4 && (lower || user.id === actor.id) && !user.deleted,
    }
  }
  const summary = (dictionary: (typeof dicts)[number]) => ({
    ...dictionary,
    can_manage: canManage(dictionary.ownerid),
    word_count: words.filter((word) => word.dictid === dictionary.id).length,
  })
  function paginate<T>(items: T[], params: URLSearchParams) {
    const perPage = Number(params.get('per_page') || 20)
    const pages = Math.max(1, Math.ceil(items.length / perPage))
    const page = Math.min(Number(params.get('page') || 1), pages)
    return {
      items: items.slice((page - 1) * perPage, page * perPage),
      pagination: { page, per_page: perPage, pages, total: items.length },
    }
  }
  function handle(
    url: string,
    method = 'GET',
    body: Record<string, unknown> = {},
    csrf?: string | null,
  ) {
    const parsed = new URL(url, 'http://test.local')
    const path = parsed.pathname
    const q = parsed.searchParams.get('q') || ''
    const ok = (data: object = {}) => ({ status: 200, body: { success: true, ...data } })
    const error = (code: string, status: number) => ({
      status,
      body: { success: false, code, message: code },
    })
    if (method !== 'GET') {
      writes.push({ path, method, body })
      if (csrf !== 'test-csrf') return error('csrf_failed', 403)
      if (state.rejectWrites) return error('forbidden', 403)
    }
    if (path === '/api/session') return ok(session())
    if (path === '/api/dicts') {
      const page = paginate(
        dicts.filter((dict) => dict.dictname.includes(q)).sort((a, b) => b.id - a.id),
        parsed.searchParams,
      )
      return ok({ dicts: page.items.map(summary), pagination: page.pagination })
    }
    if (path === '/api/dict' && method === 'POST') {
      const id = Math.max(...dicts.map((dict) => dict.id), 0) + 1
      dicts.push({
        id,
        dictname: String(body.dictname),
        ownerid: actor.id,
        multiplier: Number(body.multiplier ?? 1).toFixed(2),
        config_version: 0,
      })
      return { status: 201, body: { success: true, dict_id: id } }
    }
    const dictMatch = /^\/api\/dict\/(\d+)(?:\/(.*))?$/.exec(path)
    if (dictMatch) {
      const id = Number(dictMatch[1])
      const dict = dicts.find((dict) => dict.id === id)
      if (!dict) return error('not_found', 404)
      if (method !== 'GET' && !canManage(dict.ownerid)) return error('forbidden', 403)
      const operation = dictMatch[2]
      if (!operation) {
        if (method === 'PUT') {
          dict.dictname = String(body.dictname)
          dict.config_version++
        }
        if (method === 'DELETE') dicts.splice(dicts.indexOf(dict), 1)
        return ok({ dict: summary(dict), csv_limits: csvLimits })
      }
      if (operation === 'multiplier' && method === 'PUT') {
        if (body.expected_version !== dict.config_version)
          return error('stale_dictionary_version', 409)
        if (dict.ownerid === null && !body.reason) return error('reason_required', 400)
        dict.multiplier = Number(body.multiplier).toFixed(2)
        dict.config_version++
        return ok()
      }
      if (operation === 'words') {
        if (state.failWords) return error('database_unavailable', 503)
        const page = paginate(
          words.filter(
            (word) => word.dictid === id && (word.english.includes(q) || word.chinese.includes(q)),
          ),
          parsed.searchParams,
        )
        return ok({ words: page.items, pagination: page.pagination })
      }
      if (operation === 'word') {
        const wordId = Math.max(...words.map((word) => word.id), 0) + 1
        words.push({
          id: wordId,
          dictid: id,
          english: String(body.english),
          chinese: String(body.chinese),
        })
        return { status: 201, body: { success: true, word_id: wordId } }
      }
      if (operation === 'import-csv') {
        if (String(body.csv).includes('bad'))
          return {
            status: 400,
            body: {
              success: false,
              code: 'invalid_csv',
              message: 'Invalid CSV',
              details: {
                errors: [{ line: 2, message: '<script>two columns required</script>' }],
                limit: 50,
              },
            },
          }
        words.push({
          id: Math.max(...words.map((word) => word.id), 0) + 1,
          dictid: id,
          english: 'imported',
          chinese: '导入',
        })
        return ok({ count: 1 })
      }
      if (operation === 'export-csv')
        return ok({ filename: 'dictionary.csv', content: 'apple,苹果\r\n' })
    }
    const wordMatch = /^\/api\/word\/(\d+)$/.exec(path)
    if (wordMatch) {
      const word = words.find((word) => word.id === Number(wordMatch[1]))
      if (!word) return error('not_found', 404)
      if (method === 'DELETE') words.splice(words.indexOf(word), 1)
      if (method === 'PUT') {
        word.english = String(body.english)
        word.chinese = String(body.chinese)
      }
      return ok()
    }
    if (path === '/api/admin/users') {
      if (!root) return error('forbidden', 403)
      const page = paginate(
        users
          .filter(
            (user) =>
              user.username.includes(q) &&
              (parsed.searchParams.get('include_deleted') === 'true' || !user.deleted),
          )
          .sort((a, b) => b.id - a.id),
        parsed.searchParams,
      )
      return ok({
        users: page.items.map((user) => ({ ...user, capabilities: capabilities(user) })),
        pagination: page.pagination,
      })
    }
    const action = /^\/api\/admin\/user\/(\d+)\/(reset-password|delete|restore|update|level)$/.exec(
      path,
    )
    if (action) {
      if (!root) return error('forbidden', 403)
      const user = users.find((user) => user.id === Number(action[1]))
      if (!user) return error('not_found', 404)
      if (user.id === actor.id && action[2] !== 'update') return error('bad_request', 400)
      if (action[2] === 'level') {
        if (!capabilities(user).can_set_level || Number(body.admin_level) >= actor.admin_level)
          return error('forbidden', 403)
        if (body.expected_version !== user.admin_version) return error('stale_admin_version', 409)
        user.admin_level = Number(body.admin_level)
        user.type = user.admin_level ? 'root' : 'normal'
        user.admin_version++
      }
      if (action[2] === 'update') {
        if (!capabilities(user).can_edit_profile) return error('forbidden', 403)
        user.username = String(body.username)
        user.introduction = String(body.introduction)
      }
      if (action[2] === 'delete') user.deleted = 1
      if (action[2] === 'restore') user.deleted = 0
      return ok()
    }
    throw Error(`Unhandled fixture request ${method} ${path}`)
  }
  return { actor, dicts, words, users, writes, state, csvLimits, session, handle }
}
