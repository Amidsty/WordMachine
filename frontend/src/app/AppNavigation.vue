<script setup lang="ts">
import { nextTick, onMounted, onScopeDispose, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import type { Session } from '../shared/api/contracts'
import UserName from '../shared/ui/UserName.vue'
import { useServices } from './services'

defineProps<{ user: Session['user']; pending: boolean }>()
defineEmits<{ logout: [] }>()
const services = useServices()
const route = useRoute()
const menu = services.navigationMenu
const header = ref<HTMLElement>()
const primaryButton = ref<HTMLButtonElement>()
const accountButton = ref<HTMLButtonElement>()
const compact = ref(false)
const media = window.matchMedia?.('(max-width: 70rem)')
compact.value = media?.matches ?? false
watch(
  services.userMenuTarget,
  (target) => {
    if (target !== null && menu.value === 'account') {
      accountButton.value?.focus()
      menu.value = null
    }
  },
  { flush: 'sync' },
)
function toggle(value: 'primary' | 'account') {
  menu.value = menu.value === value ? null : value
}
function escape(event: KeyboardEvent) {
  if (!menu.value) return
  event.preventDefault()
  const trigger = menu.value === 'primary' ? primaryButton.value : accountButton.value
  // Synchronous focus return: no deferred callback can focus an old identity/page.
  trigger?.focus()
  menu.value = null
}
function outside(event: Event) {
  if (event.target instanceof Node && !header.value?.contains(event.target)) menu.value = null
}
let focusRevision = 0
async function resize() {
  const focused = document.activeElement
  const toTrigger =
    !compact.value && !!header.value?.querySelector('#primary-navigation')?.contains(focused)
  const toLink = compact.value && focused === primaryButton.value
  const path = route.fullPath
  compact.value = media?.matches ?? false
  if (menu.value === 'primary' && !compact.value) menu.value = null
  const revision = ++focusRevision
  await nextTick()
  if (revision !== focusRevision || !header.value?.isConnected || route.fullPath !== path) return
  if (document.activeElement !== focused && document.activeElement !== document.body) return
  if (compact.value && toTrigger) primaryButton.value?.focus()
  else if (!compact.value && toLink)
    header.value.querySelector<HTMLAnchorElement>('#primary-navigation a')?.focus()
}
function samePage(event: MouseEvent) {
  if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return
  const link = event.target instanceof Element ? event.target.closest('a') : null
  if (link?.pathname === route.path) menu.value = null
  // Other destinations close at the route boundary, not before its async guard finishes.
}
onMounted(() => {
  media?.addEventListener('change', resize)
  document.addEventListener('pointerdown', outside)
  document.addEventListener('focusin', outside)
})
onScopeDispose(() => {
  focusRevision++
  media?.removeEventListener('change', resize)
  document.removeEventListener('pointerdown', outside)
  document.removeEventListener('focusin', outside)
})
</script>

<template>
  <header ref="header" class="site-header arena-header" @keydown.esc="escape" @click="samePage">
    <RouterLink to="/" class="brand"
      ><span class="brand-mark" aria-hidden="true">W</span>WordMachine</RouterLink
    >
    <button
      v-if="compact"
      id="primary-toggle"
      ref="primaryButton"
      type="button"
      class="button navigation-toggle"
      aria-controls="primary-navigation"
      :aria-expanded="menu === 'primary'"
      @click="toggle('primary')"
    >
      菜单
    </button>
    <nav
      v-show="!compact || menu === 'primary'"
      id="primary-navigation"
      class="primary-nav"
      :class="{ 'primary-nav--compact': compact }"
      aria-label="主导航"
    >
      <RouterLink v-if="user" to="/">对局大厅</RouterLink>
      <RouterLink v-if="user" to="/admin/">管理中心</RouterLink>
      <RouterLink to="/leaderboard/">排行榜</RouterLink>
      <template v-if="!user">
        <RouterLink to="/login/">登录</RouterLink>
        <RouterLink to="/register/">注册</RouterLink>
      </template>
    </nav>
    <div v-if="user" class="account-navigation">
      <button
        id="account-toggle"
        ref="accountButton"
        type="button"
        class="account-toggle"
        aria-label="我的账号"
        aria-controls="account-navigation"
        :aria-expanded="menu === 'account'"
        @click="toggle('account')"
      >
        <UserName :name="user.username" :rating="user.rating" />
      </button>
      <nav v-if="menu === 'account'" id="account-navigation" aria-label="账号导航">
        <RouterLink class="account-action" :to="`/user/${user.id}/`">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="m3 10 9-7 9 7M5 9v12h5v-7h4v7h5V9" />
          </svg>
          <span>个人主页</span>
        </RouterLink>
        <RouterLink class="account-action" to="/changepw/">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z" />
            <path d="m8 12 3 3 5-6" />
          </svg>
          <span>个人设置</span>
        </RouterLink>
        <button
          type="button"
          class="button account-action"
          :disabled="pending"
          :aria-busy="pending"
          @click="$emit('logout')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M10 4H4v16h6M9 12h12m-4-4 4 4-4 4" />
          </svg>
          <span>{{ pending ? '正在登出…' : '登出' }}</span>
        </button>
      </nav>
    </div>
    <p v-else-if="!services.client.session.value" class="hint session-status" role="status">
      {{ services.sessionError.value ? '会话核验未完成，请重试访问页面。' : '正在核验会话…' }}
    </p>
  </header>
</template>

<style scoped>
.site-header.arena-header {
  align-items: flex-start;
  gap: 0.75rem 1.5rem;
}
.arena-header .brand {
  flex-shrink: 0;
  min-height: 48px;
}
.arena-header .primary-nav {
  flex: 1 1 auto;
  justify-content: center;
  gap: 0.5rem 1rem;
  min-height: 48px;
}
.arena-header .primary-nav--compact {
  order: 4;
  flex-basis: 100%;
  justify-content: flex-start;
  border-top: 1px solid var(--ui-line);
  padding-top: 0.5rem;
}
.arena-header nav a[aria-current='page'] {
  color: var(--ui-primary);
  text-decoration-thickness: 2px;
  text-underline-offset: 0.35em;
}
.navigation-toggle {
  margin-left: auto;
}
.account-navigation {
  position: relative;
  min-width: 0;
  max-width: 100%;
}
.account-toggle {
  display: flex;
  align-items: center;
  min-width: 44px;
  min-height: 44px;
  max-width: 16rem;
  padding: 0.5rem;
  border: 0;
  border-radius: 0;
  background: transparent;
  text-align: start;
}
.account-toggle .user-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.arena-header #account-navigation {
  position: absolute;
  z-index: 10;
  inset-inline-end: 0;
  top: 100%;
  width: max-content;
  max-width: calc(100vw - 2rem);
  max-height: calc(100dvh - 6rem);
  overflow: auto;
  box-shadow: var(--ui-shadow-popover);
  display: grid;
  grid-template-columns: max-content;
  align-items: stretch;
  justify-content: center;
  gap: 0.25rem;
  margin-top: 0.5rem;
  padding: 0.5rem;
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-sm);
  background: var(--ui-surface);
}
.arena-header #account-navigation .account-action {
  display: inline-flex;
  align-items: center;
  justify-content: flex-start;
  gap: 0.5rem;
  min-height: 44px;
  padding: 0.5rem;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--ui-text);
  text-decoration: none;
  white-space: nowrap;
}
.account-action svg {
  flex: 0 0 1.125rem;
  width: 1.125rem;
  height: 1.125rem;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.75;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.arena-header #account-navigation .account-action:not(:disabled):is(:hover, :focus-visible) {
  background: var(--ui-primary-soft);
  color: var(--ui-primary);
}
.session-status {
  margin: 0;
}
@media (max-width: 70rem) {
  .site-header.arena-header {
    column-gap: 0.75rem;
  }
  .arena-header #account-navigation {
    position: static;
    max-width: 100%;
    max-height: none;
    box-shadow: none;
  }
  .account-navigation {
    flex-basis: 100%;
  }
  .account-toggle {
    max-width: 100%;
  }
}
@media (max-width: 400px) {
  .arena-header .brand {
    font-size: 1.125rem;
  }
}
</style>
