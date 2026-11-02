<script setup lang="ts">
import { computed, onMounted, ref, shallowRef, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useServices } from '../../app/services'
import { useAutoRefresh } from '../../app/useAutoRefresh'
import type { PublicUser } from '../../shared/api/contracts'
import { ApiError } from '../../shared/api/client'
import { useFormTask } from '../../shared/forms/useFormTask'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import UserName from '../../shared/ui/UserName.vue'
import SkeletonBlock from '../../shared/ui/SkeletonBlock.vue'
import ScoreHistory from './ScoreHistory.vue'
import ScoreChart from './ScoreChart.vue'
import RatingState from './RatingState.vue'
const services = useServices()
const route = useRoute()
const userId = Number(route.params.id)
const user = shallowRef<PublicUser | null>(null)
const task = useFormTask()
const scoreHistory = ref<HTMLElement>()
// This only exposes a read-only menu entry. Actual actions come from the
// freshly fetched server capabilities, never from public profile data.
const canOpenManagement = computed(() => {
  const level = services.client.session.value?.user?.admin_level ?? 0
  return level >= 1 && level <= 5
})
function manage() {
  if (user.value && canOpenManagement.value) services.userMenuTarget.value = user.value.id
}
function showHistory() {
  const heading = scoreHistory.value?.querySelector<HTMLElement>('h2')
  heading?.focus()
  heading?.scrollIntoView({ block: 'start' })
}
async function load(background = false) {
  if (task.pending.value) return
  if (!background) user.value = null
  await task.run(async (signal) => {
    try {
      if (!Number.isSafeInteger(userId) || userId < 1 || userId > 2147483647)
        throw new ApiError('invalid_parameters', '无效的用户编号。')
      const result = await services.people.profile(userId, signal)
      if (!signal.aborted) user.value = result
    } catch (cause) {
      if (!signal.aborted) user.value = null
      throw cause
    }
  })
}
onMounted(() => load())
useAutoRefresh(() => load(true))
watch(services.userChanges, () => {
  void load()
})
</script>

<template>
  <section class="public-profile" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">公开资料</h1>
    <NoticeBanner :message="task.error.value" />
    <p v-if="task.pending.value && !user" role="status">正在加载用户资料…</p>
    <SkeletonBlock v-if="task.pending.value && !user && !task.error.value" />
    <button
      v-if="task.error.value"
      type="button"
      class="button"
      :disabled="task.pending.value"
      @click="load()"
    >
      重试加载
    </button>
    <template v-if="user">
      <header class="profile-identity">
        <span class="profile-placeholder" aria-hidden="true">W</span>
        <div class="profile-name">
          <h2 class="multiline">
            <UserName :name="user.username" :rating="user.rating" />
          </h2>
          <p class="hint">用户 #{{ user.id }} · 账户类型：{{ user.type ?? '记录缺失' }}</p>
        </div>
        <div
          v-if="canOpenManagement || services.client.session.value?.user?.id === user.id"
          class="profile-actions"
        >
          <RouterLink
            v-if="services.client.session.value?.user?.id === user.id"
            class="button"
            to="/changepw/"
            >修改我的资料</RouterLink
          >
          <button
            v-if="canOpenManagement"
            :id="`profile-manage-${user.id}`"
            data-profile-management
            type="button"
            class="button"
            aria-haspopup="dialog"
            :aria-expanded="services.userMenuTarget.value === user.id"
            @click="manage"
          >
            管理操作
          </button>
        </div>
      </header>
      <nav class="actions profile-navigation" aria-label="资料页内导航">
        <button type="button" class="button" @click="showHistory">查看 Rating / Perf 历史</button>
      </nav>
      <div class="profile-overview">
        <RatingState :key="user.id" :uid="user.id" />
        <section class="profile-introduction" aria-labelledby="profile-introduction-title">
          <h2 id="profile-introduction-title">个人简介</h2>
          <p class="multiline">{{ user.introduction || '该用户还没有个人简介。' }}</p>
        </section>
      </div>
      <ScoreChart :key="user.id" :uid="user.id" />
      <div ref="scoreHistory" class="profile-history">
        <ScoreHistory :key="user.id" :uid="user.id" />
      </div>
    </template>
  </section>
</template>

<style scoped>
.public-profile,
.profile-name,
.profile-overview > * {
  min-width: 0;
}
.profile-identity {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}
.profile-placeholder {
  display: grid;
  place-items: center;
  flex: 0 0 3rem;
  height: 3rem;
  border: 1px solid var(--ui-line);
  border-radius: 50%;
  background: var(--ui-surface);
  color: var(--ui-text-muted);
  font-weight: 700;
}
.profile-name {
  flex: 1 1 12rem;
  overflow-wrap: anywhere;
}
.profile-name h2,
.profile-name p {
  margin: 0;
}
.profile-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-inline-start: auto;
}
.profile-navigation {
  margin-block: 1.5rem;
}
.profile-overview {
  display: grid;
  gap: 1.5rem;
  align-items: start;
}
.profile-introduction {
  overflow-wrap: anywhere;
}
.profile-introduction h2 {
  margin-top: 0;
}
.profile-history {
  margin-top: 1.5rem;
  padding: 1rem;
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-md);
  background: var(--ui-surface);
  min-width: 0;
}
.profile-history :deep(h2) {
  margin-top: 0;
  scroll-margin-block-start: 1rem;
}
@media (min-width: 1024px) {
  .profile-overview {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
}
</style>
