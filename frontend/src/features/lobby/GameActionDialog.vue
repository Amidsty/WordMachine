<script setup lang="ts">
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import { newGameRequestId } from '../../shared/api/gameCommand'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import { actionLabels, type LobbyGame, type LobbyAction } from './service'
const props = defineProps<{ game: LobbyGame; action: LobbyAction }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const task = useFormTask()
const requestId = newGameRequestId()
async function submit() {
  if (!actorId) return
  await task.run(async (signal) => {
    await services.lobby.act(props.game, props.action, actorId, requestId, signal)
    if (!signal.aborted) emit('saved')
  })
}
</script>

<template>
  <ModalDialog :title="actionLabels[action]" :busy="task.pending.value" @close="emit('close')">
    <div class="game-action-target">
      <p>
        <bdi>{{ game.name ?? '对局' }}</bdi> #{{ game.id }}
      </p>
      <p>确认对对局 #{{ game.id }} 执行“{{ actionLabels[action] }}”？</p>
      <p>{{ game.rated ? 'Rated · 更新 Rating' : 'Unrated · 不更新 Rating' }}</p>
    </div>
    <p v-if="action === 'cancel'" class="hint">
      取消的是整个等待对局，不是仅撤销本人的报名；不会生成比赛结算。
    </p>
    <p v-else-if="action === 'leave'" class="hint">仅撤销本人的报名，不取消整个对局。</p>
    <p class="hint">状态可能已变化，最终权限与结果由服务器确认；网络失败不会自动重复提交。</p>
    <NoticeBanner :message="task.error.value" />
    <form @submit.prevent="submit">
      <fieldset :disabled="task.pending.value">
        <legend class="sr-only">确认对局操作</legend>
        <div class="actions">
          <button type="button" class="button" @click="emit('close')">返回</button>
          <SubmitButton :pending="task.pending.value">确认{{ actionLabels[action] }}</SubmitButton>
        </div>
      </fieldset>
    </form>
  </ModalDialog>
</template>

<style scoped>
.game-action-target {
  padding: 1rem;
  background: var(--ui-surface-muted);
  border-left: 3px solid var(--ui-primary);
  overflow-wrap: anywhere;
}
.game-action-target p {
  margin-block: 0.4rem;
}
</style>
