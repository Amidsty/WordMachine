<script setup lang="ts">
import { computed, onScopeDispose, watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { ApiError } from '../shared/api/client'
import { useFormTask } from '../shared/forms/useFormTask'
import NoticeBanner from '../shared/ui/NoticeBanner.vue'
import AppNavigation from './AppNavigation.vue'
import UserMenu from '../features/users/UserMenu.vue'
import { useServices } from './services'
import { afterLoginTarget } from './navigation'

const services = useServices()
const route = useRoute()
const router = useRouter()
const user = computed(() => services.client.session.value?.user)
const logoutTask = useFormTask()
let logoutController: AbortController | undefined
let logoutOrigin: { path: string; identity: string } | undefined
let logoutExitPath: string | undefined
onScopeDispose(() => logoutController?.abort())
const identityKey = computed(
  () =>
    `${user.value?.id ?? 'anonymous'}:${user.value?.type ?? ''}:${user.value?.admin_level ?? 0}:${services.client.session.value?.csrf_token ?? ''}`,
)
watch(
  [() => route.path, identityKey],
  ([path], [previousPath, previousIdentity]) => {
    // The server may revoke Socket/read access before the logout reply arrives.
    // Keep only this deliberate exit's destination, never its private content.
    if (
      logoutOrigin &&
      !user.value &&
      path === logoutOrigin.path &&
      previousPath === path &&
      previousIdentity === logoutOrigin.identity
    )
      logoutExitPath = path
    else if (user.value || path !== logoutExitPath) logoutExitPath = undefined
    logoutOrigin = undefined
    services.userMenuTarget.value = null
    services.navigationMenu.value = null
    logoutController?.abort()
    logoutTask.error.value = ''
  },
  { flush: 'sync' },
)

watch(user, (next) => {
  // Deliberate logout/password change owns its destination and explanatory notice.
  const reason = services.client.sessionEndReason.value
  if (reason === 'logout' || reason === 'password_changed') return
  if (!next && (route.meta.authenticated || logoutExitPath === route.path))
    void router.replace(
      logoutExitPath === route.path
        ? { name: 'login' }
        : { name: 'login', query: { next: afterLoginTarget(route.path) } },
    )
  else if (next && route.meta.root && (next.admin_level ?? 0) === 0)
    void router.replace({ name: 'management', query: { denied: '1' } })
})

async function logout() {
  await logoutTask.run(async () => {
    const path = route.path
    const controller = new AbortController()
    const origin = { path, identity: identityKey.value }
    logoutOrigin = origin
    logoutController = controller
    try {
      await services.auth.logout(controller.signal)
    } catch (error) {
      if (controller.signal.aborted) return
      if (!(error instanceof ApiError) || error.code !== 'unauthenticated') throw error
    } finally {
      if (logoutOrigin === origin) logoutOrigin = undefined
    }
    // A new identity or explicit navigation owns its destination. Aborting a
    // request does not promise that the server rolled back the logout.
    if (!user.value && route.path === path) await router.replace({ name: 'login' })
  })
}
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <AppNavigation
    :key="identityKey"
    :user="user ?? null"
    :pending="logoutTask.pending.value"
    @logout="logout"
  />
  <main id="main" class="page-content">
    <NoticeBanner :message="services.sessionError.value" />
    <NoticeBanner :message="logoutTask.error.value" />
    <!-- Identity changes discard private forms, lists and their timers/requests. -->
    <RouterView :key="`${route.path}:${identityKey}`" />
  </main>
  <UserMenu
    v-if="user && services.userMenuTarget.value !== null"
    :key="`${identityKey}:${services.userMenuTarget.value}`"
    :uid="services.userMenuTarget.value"
    @close="services.userMenuTarget.value = null"
  />
</template>
