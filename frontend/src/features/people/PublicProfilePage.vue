<script setup lang="ts">
import { onMounted, shallowRef, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useServices } from '../../app/services'
import type { PublicUser } from '../../shared/api/contracts'
import { ApiError } from '../../shared/api/client'
import { useFormTask } from '../../shared/forms/useFormTask'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import UserLink from '../../shared/ui/UserLink.vue'
import ScoreHistory from './ScoreHistory.vue'
import RatingState from './RatingState.vue'
const services = useServices()
const route = useRoute()
const userId = Number(route.params.id)
const user = shallowRef<PublicUser | null>(null)
const task = useFormTask()
async function load() {
  user.value = null
  await task.run(async (signal) => {
    if (!Number.isSafeInteger(userId) || userId < 1 || userId > 2147483647)
      throw new ApiError('invalid_parameters', '无效的用户编号。')
    const result = await services.people.profile(userId, signal)
    if (!signal.aborted) user.value = result
  })
}
onMounted(load)
watch(services.userChanges, () => {
  void load()
})
</script>

<template>
  <section class="workspace" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">公开资料</h1>
    <NoticeBanner :message="task.error.value" />
    <p v-if="task.pending.value" role="status">正在加载用户资料…</p>
    <button
      v-if="task.error.value"
      type="button"
      class="button"
      :disabled="task.pending.value"
      @click="load"
    >
      重试加载
    </button>
    <template v-if="user">
      <h2 class="multiline">
        <UserLink :id="user.id" :name="user.username" :rating="user.rating" />
        <small>#{{ user.id }}</small>
      </h2>
      <dl>
        <dt>Rating</dt>
        <dd>{{ user.rating ?? '记录缺失' }}</dd>
        <dt>类型</dt>
        <dd>{{ user.type ?? '记录缺失' }}</dd>
      </dl>
      <h2>个人简介</h2>
      <p class="multiline">{{ user.introduction || '该用户还没有个人简介。' }}</p>
      <RouterLink v-if="services.client.session.value?.user?.id === user.id" to="/changepw/"
        >修改我的资料</RouterLink
      >
      <RatingState :key="user.id" :uid="user.id" />
      <ScoreHistory :uid="user.id" kind="rating" />
      <ScoreHistory :uid="user.id" kind="perf" />
    </template>
  </section>
</template>
