<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { useAutoRefresh } from '../../app/useAutoRefresh'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { ApiError } from '../../shared/api/client'
import { errorMessage } from '../../shared/forms/useFormTask'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SkeletonBlock from '../../shared/ui/SkeletonBlock.vue'
import type { RatingState } from '../games/weighted'

const services = useServices()
// This card belongs to the mounted lobby identity, not a general public-profile
// cache. App's identity key mounts a new card for a new account/session/role.
const identity = services.client.session.value
const uid = identity?.user?.id
const currentIdentity = computed(() => {
  const next = services.client.session.value
  return (
    uid !== undefined &&
    next?.user?.id === uid &&
    next?.csrf_token === identity?.csrf_token &&
    next?.user?.type === identity?.user?.type &&
    (next?.user?.admin_level ?? 0) === (identity?.user?.admin_level ?? 0)
  )
})
const state = shallowRef<RatingState | null>(null)
const pending = ref(false)
const error = ref('')
let controller = new AbortController()
function discard() {
  controller.abort()
  state.value = null
  pending.value = false
  error.value = ''
}
watch(
  currentIdentity,
  (current) => {
    if (!current) discard()
    else {
      // A synchronous identity A -> B -> A may occur before App re-renders.
      // Start a fresh read rather than reviving A's cancelled response/cache.
      controller = new AbortController()
      void load()
    }
  },
  { flush: 'sync' },
)
onScopeDispose(discard)
async function load() {
  if (!uid || !currentIdentity.value || controller.signal.aborted || pending.value) return
  const signal = controller.signal
  pending.value = true
  error.value = ''
  // Keep accepted content during a background read; clear it on actual failure.
  // Never backfill from the session or label a failed read as zero/empty.
  try {
    const response = await services.history.account(uid, signal)
    if (!signal.aborted && currentIdentity.value) state.value = response.rating_state
  } catch (cause) {
    if (!signal.aborted && currentIdentity.value) {
      state.value = null
      error.value =
        cause instanceof ApiError
          ? errorMessage(cause)
          : '网络异常，无法读取公开评分；稍后会自动重试。'
    }
  } finally {
    if (!signal.aborted) pending.value = false
  }
}
onMounted(load)
useAutoRefresh(load, () => currentIdentity.value)
</script>

<template>
  <section v-if="currentIdentity" class="lobby-account" aria-labelledby="lobby-account-title">
    <h2 id="lobby-account-title">我的公开 Rating</h2>
    <div class="account-readout" :aria-busy="pending">
      <p v-if="pending && !state" class="hint" role="status">正在读取公开评分…</p>
      <NoticeBanner :message="error" />
      <SkeletonBlock v-if="pending && !state && !error" variant="account" />
      <dl v-if="state" class="account-values">
        <div class="account-public">
          <dt class="sr-only">Rating</dt>
          <dd>{{ state.public_rating }}</dd>
        </div>
      </dl>
    </div>

    <div class="account-actions">
      <button
        v-if="error"
        type="button"
        class="button"
        :disabled="pending"
        :aria-busy="pending"
        @click="load"
      >
        重试读取评分
      </button>
      <RouterLink :to="`/user/${uid}/`">查看个人资料</RouterLink>
    </div>
  </section>
</template>

<style scoped>
.lobby-account {
  min-width: 0;
  padding: 1rem 1.25rem;
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-md);
  background: var(--ui-surface);
}
.lobby-account h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}
.account-readout {
  min-block-size: 4.5rem;
}
.account-values {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem 1rem;
  margin: 0.5rem 0;
}
.account-values > div {
  min-width: 0;
}
.account-values dt {
  color: var(--ui-text-muted);
  font-size: 0.875rem;
}
.account-values dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
.account-values .account-public {
  grid-column: 1 / -1;
}
.account-public dd {
  font-size: clamp(2rem, 2.5vw, 2.25rem);
  line-height: 1.2;
  font-weight: 650;
}
.account-explanation {
  margin: 0.75rem 0;
}
.account-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 1rem;
}
.account-actions a {
  display: inline-flex;
  align-items: center;
  min-height: 44px;
}
</style>
