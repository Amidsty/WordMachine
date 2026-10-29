<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import { useAutoRefresh } from '../../app/useAutoRefresh'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SkeletonBlock from '../../shared/ui/SkeletonBlock.vue'
import type { RatingState } from '../games/weighted'
const props = defineProps<{ uid: number }>()
const services = useServices(),
  task = useFormTask()
const state = shallowRef<RatingState | null>(null)
async function load() {
  if (task.pending.value) return
  await task.run(async (signal) => {
    try {
      const response = await services.history.account(props.uid, signal)
      if (!signal.aborted) state.value = response.rating_state
    } catch (cause) {
      if (!signal.aborted) state.value = null
      throw cause
    }
  })
}
onMounted(load)
useAutoRefresh(load)
</script>
<template>
  <section aria-label="当前 Rating" class="profile-account">
    <h2>当前 Rating</h2>
    <p class="hint">当前账户的公开读取，不是某场比赛的赛后分数。</p>
    <NoticeBanner :message="task.error.value" />
    <p v-if="task.pending.value && !state" role="status">正在读取公开评分…</p>
    <SkeletonBlock v-if="task.pending.value && !state && !task.error.value" variant="account" />
    <template v-if="state">
      <dl class="profile-account-values">
        <div class="public-rating">
          <dt>Rating：</dt>
          <dd>{{ state.public_rating }}</dd>
        </div>
      </dl>
    </template>
    <button
      v-if="task.error.value"
      type="button"
      class="button"
      :disabled="task.pending.value"
      :aria-busy="task.pending.value"
      @click="load"
    >
      重试读取评分
    </button>
  </section>
</template>

<style scoped>
.profile-account {
  min-width: 0;
  padding: 1.25rem;
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-lg);
  background: var(--ui-surface);
  overflow-wrap: anywhere;
}
.profile-account h2 {
  margin-top: 0;
}
.profile-account-values {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}
.profile-account-values dt {
  color: var(--ui-text-muted);
}
.profile-account-values dd {
  margin: 0.25rem 0 0;
  font-variant-numeric: tabular-nums;
}
.public-rating {
  grid-column: 1 / -1;
}
.public-rating dd {
  font-size: clamp(2rem, 3vw, 2.5rem);
  line-height: 1.2;
  font-weight: 700;
}
</style>
