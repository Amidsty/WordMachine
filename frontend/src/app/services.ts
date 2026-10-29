import { inject, ref, type InjectionKey } from 'vue'
import { createApiClient, type ApiClient } from '../shared/api/client'
import { createAuthService } from '../features/auth/service'
import { createPromotionService } from '../features/dictionaries/promotions'
import { createDictionaryService } from '../features/dictionaries/service'
import { createUserManagementService } from '../features/users/service'
import { createLobbyService } from '../features/lobby/service'
import { createPeopleService } from '../features/people/service'
import { createHistoryService } from '../features/people/history'
import { createGameService } from '../features/games/service'
import { createEndRequestService } from '../features/games/endRequests'
import { createSocketService, type SocketFactory } from '../shared/api/socket'

export function createServices(
  client: ApiClient = createApiClient(),
  socketFactory?: SocketFactory,
) {
  return {
    client,
    auth: createAuthService(client),
    dictionaries: createDictionaryService(client),
    promotions: createPromotionService(client),
    users: createUserManagementService(client),
    lobby: createLobbyService(client),
    people: createPeopleService(client),
    history: createHistoryService(client),
    games: createGameService(client),
    endRequests: createEndRequestService(client),
    sessionError: ref(''),
    userMenuTarget: ref<number | null>(null),
    navigationMenu: ref<'primary' | 'account' | null>(null),
    userChanges: ref(0),
    sockets: createSocketService(client, socketFactory),
  }
}
export type AppServices = ReturnType<typeof createServices>
export const servicesKey: InjectionKey<AppServices> = Symbol('wordmachine-services')

export function useServices() {
  const services = inject(servicesKey)
  if (!services) throw new Error('App services have not been provided')
  return services
}
