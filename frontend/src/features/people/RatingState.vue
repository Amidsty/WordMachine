<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import type { RatingState } from '../games/weighted'
const props = defineProps<{ uid: number }>()
const services = useServices(),
  task = useFormTask()
const state = shallowRef<RatingState | null>(null)
async function load() {
  state.value = null
  await task.run(async (signal) => {
    const response = await services.history.account(props.uid, signal)
    if (!signal.aborted) state.value = response.rating_state
  })
}
onMounted(load)
</script>
<template>
  <section aria-label="Rating 与基础额度" class="section-panel">
    <h2>Rating 与基础额度</h2>
    <NoticeBanner :message="task.error.value" />
    <button type="button" class="button" :disabled="task.pending.value" @click="load">
      刷新额度状态
    </button>
    <template v-if="state">
      <p>
        公开 Rating R：{{ state.public_rating }} · 内部 Rating U：{{ state.internal_rating }} ·
        剩余基础额度 H：{{ state.remaining_bonus }}
      </p>
      <p>
        新手政策：{{ state.newcomer_enabled ? '启用' : '关闭' }} · 已完成新模型有效 Rated：{{
          state.completed_games
        }}
        · 下次有效结算释放：{{ state.next_bonus }}
      </p>
      <p class="hint">
        U = R + H。新手额度共1500，按600、350、250、150、100、50释放，不是每局补到1500；无答案或
        Unrated 不发放。旧账号默认不补发，也不以这里的新模型场次数代表全部历史。
      </p>
    </template>
  </section>
</template>
