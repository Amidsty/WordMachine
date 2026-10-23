<script setup lang="ts">
import { computed, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { ApiError } from '../shared/api/client'
import { useFormTask } from '../shared/forms/useFormTask'
import NoticeBanner from '../shared/ui/NoticeBanner.vue'
import UserLink from '../shared/ui/UserLink.vue'
import UserMenu from '../features/users/UserMenu.vue'
import { useServices } from './services'
import { afterLoginTarget } from './navigation'

const services = useServices()
const route = useRoute()
const router = useRouter()
const user = computed(() => services.client.session.value?.user)
const logoutTask = useFormTask()
const identityKey = computed(
  () =>
    `${user.value?.id ?? 'anonymous'}:${user.value?.type ?? ''}:${user.value?.admin_level ?? 0}:${services.client.session.value?.csrf_token ?? ''}`,
)
watch(
  [() => route.path, identityKey],
  () => {
    services.userMenuTarget.value = null
  },
  { flush: 'sync' },
)

watch(user, (next) => {
  // Deliberate logout/password change owns its destination and explanatory notice.
  const reason = services.client.sessionEndReason.value
  if (reason === 'logout' || reason === 'password_changed') return
  if (!next && route.meta.authenticated)
    void router.replace({ name: 'login', query: { next: afterLoginTarget(route.path) } })
  else if (next && route.meta.root && (next.admin_level ?? 0) === 0)
    void router.replace({ name: 'management', query: { denied: '1' } })
})

async function logout() {
  await logoutTask.run(async () => {
    try {
      await services.auth.logout()
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'unauthenticated') throw error
    }
    await router.replace({ name: 'login' })
  })
}
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <header class="site-header">
    <RouterLink to="/" class="brand">WordMachine</RouterLink>
    <nav aria-label="主导航">
      <RouterLink to="/">主页</RouterLink>
      <RouterLink to="/leaderboard/">排行榜</RouterLink>
      <RouterLink to="/admin/">管理</RouterLink>
      <RouterLink to="/changepw/">修改资料</RouterLink>
      <template v-if="user">
        <RouterLink to="/game-end-requests/">结束请求</RouterLink>
        <UserLink :id="user.id" :name="user.username" :rating="user.rating" />
        <button type="button" class="button" :disabled="logoutTask.pending.value" @click="logout">
          登出
        </button>
      </template>
      <RouterLink v-else to="/login/">登录</RouterLink>
    </nav>
  </header>
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
