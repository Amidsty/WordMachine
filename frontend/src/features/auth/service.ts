import type { ApiClient } from '../../shared/api/client'
import {
  authenticatedSessionSchema,
  profileSchema,
  registrationSchema,
  successSchema,
} from '../../shared/api/contracts'

export type Registration = { username: string; password: string; introduction: string }
export type ProfileUpdate = {
  introduction: string
  current_password?: string
  new_password?: string
}

export function createAuthService(client: ApiClient) {
  return {
    async login(username: string, password: string, signal?: AbortSignal) {
      const session = await client.request('/api/login', authenticatedSessionSchema, {
        method: 'POST',
        body: { username, password },
        signal,
      })
      signal?.throwIfAborted()
      client.acceptSession(session)
    },
    register(data: Registration, signal?: AbortSignal) {
      return client.request('/api/register', registrationSchema, {
        method: 'POST',
        body: data,
        signal,
      })
    },
    async logout(signal?: AbortSignal) {
      await client.request('/api/logout', successSchema, { method: 'POST', body: {}, signal })
      signal?.throwIfAborted()
      client.acceptSession(null, 'logout')
    },
    async updateProfile(uid: number, data: ProfileUpdate, signal?: AbortSignal) {
      const result = await client.request(`/api/user/${uid}/update`, profileSchema, {
        method: 'POST',
        body: data,
        signal,
        expectedUserId: uid,
      })
      // A disposed form cannot apply its late result to a newer route/identity.
      // This only cancels local reception, not a server-side profile change.
      signal?.throwIfAborted()
      if (result.reauthenticate) client.acceptSession(null, 'password_changed')
      else if (client.session.value?.user?.id === result.user.id) {
        client.acceptSession({ ...client.session.value, authenticated: true, user: result.user })
      }
      return result
    },
  }
}
