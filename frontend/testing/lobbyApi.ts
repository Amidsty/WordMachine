// UI-only fixture. It does not validate transactions, JSON SQL or backend permissions.
import { createManagementApi } from './managementApi'
import type { LobbyGame } from '../src/features/lobby/service'

export function createLobbyApi(authenticated = true) {
  const management = createManagementApi()
  const state = {
    authenticated,
    activeGameId: null as number | null,
    failList: false,
    rejectWrites: false,
  }
  const users = Array.from({ length: 101 }, (_, index) => ({
    id: index + 1,
    username: index === 0 ? 'owner' : index === 1 ? '<img src=x>' : `person-${index + 1}`,
    introduction: index === 1 ? '<script>first</script>\nsecond line' : '',
    rating: index === 100 ? null : 1500,
    type: 'normal',
  }))
  function game(id: number, status: LobbyGame['status'] = -1, joined = false): LobbyGame {
    const owner = { id: joined ? 1 : 2, username: joined ? 'owner' : '<img src=x>' }
    return {
      id,
      version: 0,
      rated: true,
      status,
      dictid: 2,
      dictname: `Dictionary <b>${id}</b>`,
      owner,
      users: joined ? [owner, { id: 2, username: '<img src=x>' }] : [owner],
      is_joined: joined,
      actions: {
        join: status === -1 && !joined,
        leave: false,
        start: status === -1 && joined,
        cancel: status === -1 && joined,
      },
    }
  }
  const games = [game(1), game(2, -1, true), game(3, 0), game(4, 1), game(5, 2)]
  const writes: { path: string; body: Record<string, unknown> }[] = []
  function session() {
    return {
      success: true,
      authenticated: state.authenticated,
      user: state.authenticated ? management.actor : null,
      csrf_token: 'test-csrf',
    }
  }
  function page<T>(items: T[], params: URLSearchParams) {
    const perPage = Number(params.get('per_page') || 20)
    const pages = Math.max(1, Math.ceil(items.length / perPage))
    const current = Math.min(Number(params.get('page') || 1), pages)
    return {
      items: items.slice((current - 1) * perPage, current * perPage),
      pagination: { page: current, per_page: perPage, total: items.length, pages },
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
    const ok = (data: object) => ({ status: 200, body: { success: true, ...data } })
    const fail = (code: string, status: number) => ({
      status,
      body: { success: false, code, message: code },
    })
    if (path === '/api/session') return ok(session())
    if (path === '/api/leaderboard') {
      const result = page(
        users.slice(0, 100).map((user, index) => ({ ...user, rank: index + 1 })),
        parsed.searchParams,
      )
      return ok({ users: result.items, pagination: result.pagination })
    }
    const profile = /^\/api\/user\/(\d+)$/.exec(path)
    if (profile) {
      const user = users.find((user) => user.id === Number(profile[1]))
      return user ? ok({ user }) : fail('not_found', 404)
    }
    if (path.startsWith('/api/game/')) {
      if (!state.authenticated) return fail('unauthenticated', 401)
      if (path === '/api/game/list') {
        if (state.failList) return fail('database_unavailable', 503)
        const status = { waiting: -1, running: 0, finished: 1, cancelled: 2 }[
          parsed.searchParams.get('status') || 'waiting'
        ]
        const q = parsed.searchParams.get('q') || ''
        const result = page(
          games
            .filter((game) => game.status === status && (game.dictname || '').includes(q))
            .sort((a, b) => b.id - a.id),
          parsed.searchParams,
        )
        return ok({
          games: result.items,
          pagination: result.pagination,
          active_game_id: state.activeGameId,
        })
      }
      writes.push({ path, body })
      if (csrf !== 'test-csrf') return fail('csrf_failed', 403)
      if (state.rejectWrites) return fail('forbidden', 403)
      if (path === '/api/game/create') {
        if (!management.words.some((word) => word.dictid === body.dict_id))
          return fail('empty_dictionary', 400)
        const id = Math.max(...games.map((game) => game.id)) + 1
        games.push({
          ...game(id, -1, true),
          users: [{ id: 1, username: 'owner' }],
          actions: { join: false, leave: false, start: false, cancel: true },
        })
        return {
          status: 201,
          body: { success: true, game_id: id, version: 0, request_id: body.request_id },
        }
      }
      const action = /^\/api\/game\/(\d+)\/(join|leave|start|cancel)$/.exec(path)
      const target = games.find((game) => game.id === Number(action?.[1]))
      if (!action || !target) return fail('not_found', 404)
      if (body.expected_version !== target.version) return fail('stale_game_version', 409)
      if (action[2] === 'join') {
        target.users.push({ id: 1, username: 'owner' })
        target.is_joined = true
        target.actions = { join: false, leave: true, start: false, cancel: false }
      }
      if (action[2] === 'leave') {
        target.users = target.users.filter((user) => user.id !== 1)
        target.is_joined = false
        target.actions = { join: true, leave: false, start: false, cancel: false }
      }
      if (action[2] === 'start') {
        target.status = 0
        state.activeGameId = target.id
      }
      if (action[2] === 'cancel') {
        target.status = 2
        target.actions = { join: false, leave: false, start: false, cancel: false }
      }
      target.version++
      return ok({ version: target.version, request_id: body.request_id })
    }
    return management.handle(url, method, body, csrf)
  }
  return { state, users, games, writes, management, session, handle, game }
}
