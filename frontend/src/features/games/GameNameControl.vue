<script setup lang="ts">
import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import { newGameRequestId } from '../../shared/api/gameCommand'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import type { GameState } from './contracts'

const props = defineProps<{
  game: Pick<GameState, 'id' | 'version' | 'name' | 'owner'>
  disabled?: boolean
}>()
const emit = defineEmits<{ editing: [value: boolean]; changed: [] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const allowed = computed(
  () =>
    !!actorId &&
    services.client.session.value?.user?.id === actorId &&
    props.game.owner?.id === actorId,
)
const task = useFormTask()
const opened = shallowRef<{ id: number; version: number } | null>(null)
const name = ref('')
let intent: { name: string; expected_version: number; request_id: string } | null = null
let alive = true
onScopeDispose(() => {
  alive = false
})
function close() {
  opened.value = null
  emit('editing', false)
  emit('changed')
}
watch(
  () =>
    JSON.stringify([
      services.client.session.value?.user?.id,
      services.client.session.value?.user?.admin_level,
      services.client.session.value?.csrf_token,
    ]),
  () => {
    alive = false
    if (opened.value) close()
  },
)
function open() {
  if (!allowed.value || props.disabled) return
  alive = true
  opened.value = { id: props.game.id, version: props.game.version }
  name.value = props.game.name ?? ''
  intent = null
  task.error.value = ''
  emit('editing', true)
}
async function submit() {
  const target = opened.value
  if (!target || !actorId || task.pending.value) return
  const value = name.value.trim()
  if (!value || Array.from(value).length > 100 || /[\p{Cc}\p{Cs}\p{Zl}\p{Zp}]/u.test(value)) {
    task.error.value = '比赛名称需为 1–100 个字符，不能含换行或控制字符。'
    return
  }
  await task.run(async (signal) => {
    if (!intent || intent.name !== value)
      intent = Object.freeze({
        name: value,
        expected_version: target.version,
        request_id: newGameRequestId(),
      })
    await services.games.rename(target.id, intent, actorId, signal)
    if (alive && !signal.aborted) close()
  })
}
</script>
<template>
  <button
    v-if="allowed"
    type="button"
    class="button"
    :disabled="disabled || task.pending.value || !!opened"
    @click="open"
  >
    修改比赛名称
  </button>
  <ModalDialog v-if="opened" title="修改比赛名称" :busy="task.pending.value" @close="close">
    <p>房间号 #{{ opened.id }} 保持不变。只修改显示名称，不改变词典、比赛状态或评分。</p>
    <NoticeBanner :message="task.error.value" />
    <form @submit.prevent="submit">
      <fieldset :disabled="task.pending.value">
        <legend class="sr-only">比赛名称</legend>
        <FormField id="game-name" v-model="name" label="新的比赛名称" required :maxlength="200" />
        <p class="hint">
          按打开时版本
          {{ opened.version }}
          提交。若比赛有新进度，请关闭并刷新后重新修改。超时不代表回滚；相同内容手动重试保留原请求，不自动重发。
        </p>
        <SubmitButton :pending="task.pending.value">保存比赛名称</SubmitButton>
        <button type="button" class="button" @click="close">关闭并刷新</button>
      </fieldset>
    </form>
  </ModalDialog>
</template>
