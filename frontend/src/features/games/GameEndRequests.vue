<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { usePagedResource } from '../../shared/data/usePagedResource'
import { useAutoRefresh } from '../../app/useAutoRefresh'
import { useFormTask } from '../../shared/forms/useFormTask'
import { newGameRequestId } from '../../shared/api/gameCommand'
import ResourceFeedback from '../../shared/ui/ResourceFeedback.vue'
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
useAutoRefresh(rows.refresh, () => alive && !opened.value && !props.disabled, 5000)
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
  <section class="section-panel end-requests" aria-label="结束请求">
    <h2>{{ game ? '本局结束请求与留言' : '结束请求与留言' }}</h2>
    <p>仅房主或 Lv.2+ 管理员可手动结束；发送留言不保证对方在线或及时处理。</p>
    <p v-if="game" class="hint">
      仅显示本场比赛的请求。房主与 Lv.2+ 管理员可查看本局全部留言，其他用户只看本人发送项。
    </p>
    <p v-else class="hint">房主看本人比赛留言，Lv.2+ 看全部；其他用户只看本人发送项。</p>
    <p class="hint">每人每局最多一条。</p>
    <p class="hint">显示比赛当前状态，不表示留言已读、已批准或被采纳；条数是请求数，不是比赛数。</p>
    <form v-if="!game" class="toolbar" @submit.prevent="rows.search">
      <label for="end-request-search">按比赛名称搜索</label>
      <input id="end-request-search" v-model="rows.query.value" type="search" maxlength="100" />
      <button type="submit" class="button">搜索结束请求</button>
    </form>
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
      <button
        v-if="rows.error.value"
        type="button"
        class="button"
        :disabled="rows.loading.value"
        @click="rows.load"
      >
        重试读取结束请求
      </button>
      <label v-if="!game" class="checkbox-label"
        ><input
          v-model="includeFinished"
          type="checkbox"
          @change="rows.goToPage(1)"
        />包含已结束的比赛</label
      >
    </div>
    <NoticeBanner :message="notice" kind="success" />
    <ResourceFeedback
      caption="可见的结束请求"
      :loading="rows.loading.value"
      :error="rows.error.value"
      :empty="!rows.result.value?.items.length"
    />
    <div
      v-if="rows.result.value?.items.length"
      role="region"
      aria-label="可见的结束请求"
      :aria-busy="rows.loading.value"
    >
      <p class="hint">
        本次读取共
        {{ rows.result.value.pagination.total }}
        条可见请求，按服务端顺序逐条展示；同一比赛可能跨页。
      </p>
      <ol class="end-request-list">
        <li
          v-for="row in rows.result.value.items"
          :key="`${row.sender.id}:${row.request_id}`"
          class="end-request-card"
        >
          <div class="request-heading">
            <h3>
              <RouterLink :to="`/game/${row.game_id}/${row.status === 0 ? '' : 'detail/'}`"
                ><bdi>{{ row.game_name ?? '对局' }}</bdi> #{{ row.game_id }}</RouterLink
              >
            </h3>
            <span class="request-game-status">比赛状态：{{ gameStatusLabels[row.status] }}</span>
          </div>
          <p class="request-sender">
            发送者：<UserLink
              :id="row.sender.id"
              :name="row.sender.username ?? `用户 #${row.sender.id}`"
              :rating="row.sender.rating"
            />
          </p>
          <p class="multiline request-message">{{ row.message }}</p>
          <p class="hint">
            发送时间（UTC）：<time :datetime="row.sent_at">{{ row.sent_at }}</time>
          </p>
        </li>
      </ol>
    </div>
    <PaginationBar
      v-if="rows.result.value && rows.result.value.pagination.pages > 1"
      :pagination="rows.result.value.pagination"
      label="结束请求分页"
      @page="rows.goToPage"
    />
    <ModalDialog v-if="opened" title="发送结束请求" :busy="task.pending.value" @close="close">
      <p class="request-target">
        目标比赛：<bdi>{{ game?.name ?? '对局' }}</bdi> #{{ game?.id }}
      </p>
      <p class="hint">
        仅房主、Lv.2+ 管理员及发送者本人可按权限查看。发送不会结束比赛，每人每局最多一条。
      </p>
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
          <div class="actions request-submit">
            <SubmitButton :pending="task.pending.value">{{
              intent ? '重试原请求' : '发送结束请求'
            }}</SubmitButton>
            <button type="button" class="button" @click="close">关闭并核对</button>
          </div>
        </fieldset>
      </form>
    </ModalDialog>
  </section>
</template>

<style scoped>
.end-requests {
  background: var(--ui-surface);
  min-width: 0;
}
.end-requests > h2 {
  margin-top: 0;
}
.end-request-list {
  list-style: none;
  padding: 0;
  margin-block: 1rem;
}
.end-request-card {
  padding: 1.25rem 0;
  border-top: 1px solid var(--ui-line);
  overflow-wrap: anywhere;
}
.request-heading {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.5rem 1rem;
}
.request-heading h3 {
  margin: 0;
  font-size: 1rem;
  min-width: 0;
}
.request-game-status {
  font-size: 0.85rem;
  color: var(--ui-text-muted);
}
.request-sender {
  font-size: 0.9rem;
}
.request-message {
  padding-left: 1rem;
  border-left: 3px solid var(--ui-line);
}
.request-target {
  padding: 1rem;
  background: var(--ui-surface-muted);
  overflow-wrap: anywhere;
}
.request-submit {
  margin-top: 1rem;
}
</style>
