<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { usePagedResource } from '../../shared/data/usePagedResource'
import { usePolling } from '../../shared/data/usePolling'
import { useFormTask } from '../../shared/forms/useFormTask'
import { newGameRequestId } from '../../shared/api/gameCommand'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import UserLink from '../../shared/ui/UserLink.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import type { GameState } from './contracts'
import { gameStatusLabels } from './contracts'
import { canManuallyEnd } from './endRequests'

const props = defineProps<{ game?: GameState; disabled?: boolean }>()
const emit = defineEmits<{ editing: [value: boolean] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const includeFinished = ref(false)
const rows = usePagedResource((query, signal) =>
  services.endRequests.list(query, signal, props.game?.id, includeFinished.value),
)
const task = useFormTask()
const opened = ref(false)
const content = ref('')
const notice = ref('')
const intent = ref<Readonly<{ message: string; request_id: string }> | null>(null)
let alive = true
const canSend = computed(
  () =>
    !!actorId &&
    props.game?.status === 0 &&
    !canManuallyEnd(props.game.owner?.id, services.client.session.value?.user),
)
function close() {
  opened.value = false
  emit('editing', false)
  void rows.load()
}
function open() {
  if (!canSend.value || props.disabled) return
  content.value = ''
  intent.value = null
  task.error.value = ''
  notice.value = ''
  opened.value = true
  emit('editing', true)
}
onScopeDispose(() => {
  alive = false
})
watch(
  () =>
    JSON.stringify([
      services.client.session.value?.user?.id,
      services.client.session.value?.user?.admin_level,
      services.client.session.value?.csrf_token,
    ]),
  () => {
    alive = false
    opened.value = false
    emit('editing', false)
  },
)
onMounted(rows.load)
usePolling(rows.refresh, () => !opened.value && (!props.game || props.game.status === 0))
async function submit() {
  if (!props.game || !actorId || !opened.value || task.pending.value) return
  const message = intent.value?.message ?? content.value.trim()
  if (
    !message ||
    Array.from(message).length > 500 ||
    /[\p{Cc}\p{Cs}]/u.test(message.replace(/\n/g, ''))
  ) {
    task.error.value = '留言需为 1–500 个字符，不能含控制字符。'
    return
  }
  const gameId = props.game.id
  await task.run(async (signal) => {
    if (!intent.value) intent.value = Object.freeze({ message, request_id: newGameRequestId() })
    await services.endRequests.send(gameId, intent.value, actorId, signal)
    if (!alive || signal.aborted) return
    notice.value = '结束请求已保存，房主或 Lv.2+ 管理员可查看；不会自动结束比赛。'
    close()
  })
}
</script>
<template>
  <section class="section-panel" aria-label="结束请求">
    <h2>结束请求与留言</h2>
    <p>仅房主或 Lv.2+ 管理员可手动结束。其他用户可发送留言请求处理；不保证对方在线或立即处理。</p>
    <p class="hint">
      房主可查看自己比赛的留言，Lv.2+
      管理员可查看全部；其他用户仅能查看自己发送的留言。每人每局最多一条。
    </p>
    <div class="actions">
      <button
        v-if="canSend"
        type="button"
        class="button"
        :disabled="disabled || task.pending.value"
        @click="open"
      >
        向房主/管理员发送结束请求
      </button>
      <button type="button" class="button" :disabled="rows.loading.value" @click="rows.load">
        刷新结束请求
      </button>
      <RouterLink v-if="game" to="/game-end-requests/">全部可见结束请求</RouterLink>
      <label v-else class="checkbox-label"
        ><input
          v-model="includeFinished"
          type="checkbox"
          @change="rows.goToPage(1)"
        />包含已结束的比赛</label
      >
    </div>
    <NoticeBanner :message="notice" kind="success" />
    <NoticeBanner :message="rows.error.value" />
    <DataTable
      caption="可见的结束请求"
      :loading="rows.loading.value"
      :empty="!rows.result.value?.items.length"
    >
      <template #head
        ><tr>
          <th>比赛</th>
          <th>发送者</th>
          <th>留言</th>
          <th>发送时间 / 当前状态</th>
        </tr></template
      >
      <tr v-for="row in rows.result.value?.items" :key="`${row.sender.id}:${row.request_id}`">
        <td>
          <RouterLink :to="`/game/${row.game_id}/${row.status === 0 ? '' : 'detail/'}`"
            ><bdi>{{ row.game_name ?? '对局' }}</bdi> #{{ row.game_id }}</RouterLink
          >
        </td>
        <td>
          <UserLink
            :id="row.sender.id"
            :name="row.sender.username ?? `用户 #${row.sender.id}`"
            :rating="row.sender.rating"
          />
        </td>
        <td class="multiline">{{ row.message }}</td>
        <td>{{ row.sent_at }}<br />{{ gameStatusLabels[row.status] }}</td>
      </tr>
    </DataTable>
    <PaginationBar
      v-if="rows.result.value && rows.result.value.pagination.pages > 1"
      :pagination="rows.result.value.pagination"
      label="结束请求分页"
      @page="rows.goToPage"
    />
    <ModalDialog v-if="opened" title="发送结束请求" :busy="task.pending.value" @close="close">
      <NoticeBanner :message="task.error.value" />
      <form @submit.prevent="submit">
        <fieldset :disabled="task.pending.value">
          <legend class="sr-only">结束请求留言</legend>
          <label for="end-request-message">结束原因或留言</label>
          <textarea
            id="end-request-message"
            v-model="content"
            :readonly="!!intent"
            rows="4"
            maxlength="1000"
            required
          />
          <p class="hint">
            仅保存请求，不结束比赛或改变轮次。首次提交后内容和编号固定，只能手动重试原请求。超时或关闭不代表失败、撤销或回滚；重新发送前请核对已发送记录。
          </p>
          <SubmitButton :pending="task.pending.value">{{
            intent ? '重试原请求' : '发送结束请求'
          }}</SubmitButton>
          <button type="button" class="button" @click="close">关闭并核对</button>
        </fieldset>
      </form>
    </ModalDialog>
  </section>
</template>
