<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useServices } from '../../app/services'
import { usePolling } from '../../shared/data/usePolling'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import { useGameState } from './useGameState'
import { useGameFeed } from './useGameFeed'
import { useGameCommand } from './useGameCommand'
import { canManuallyEnd } from './endRequests'
import GameEndRequests from './GameEndRequests.vue'
import GameOverview from './GameOverview.vue'
import GameNameControl from './GameNameControl.vue'
import GameScores from './GameScores.vue'
import AnswerHistory from './AnswerHistory.vue'
import GameTurn from './GameTurn.vue'
import GameSidebar from './GameSidebar.vue'
import GameProgress from './GameProgress.vue'
import GameAnswerFeedback from './GameAnswerFeedback.vue'
import SkeletonBlock from '../../shared/ui/SkeletonBlock.vue'

const services = useServices()
const router = useRouter()
const gameId = Number(useRoute().params.id)
const actorId = services.client.session.value?.user?.id ?? 0
const state = useGameState((signal) => services.games.get(gameId, signal))
const { game, pending, error, refresh } = state
const feed = useGameFeed(services, gameId, actorId, state.accept, state.reconcile)
const command = useGameCommand(feed.send, state.reconcile)
const autoRefresh = ref(true)
const endVersion = ref<number | null>(null)
const renaming = ref(false)
const messaging = ref(false)
const navigationBlocked = computed(
  () => services.navigationMenu.value !== null || services.userMenuTarget.value !== null,
)
const blocked = computed(
  () =>
    !!command.intent.value ||
    command.pending.value ||
    !!error.value ||
    endVersion.value !== null ||
    renaming.value ||
    messaging.value ||
    navigationBlocked.value,
)
const canEnd = computed(
  () =>
    game.value?.status === 0 &&
    canManuallyEnd(game.value.owner?.id, services.client.session.value?.user),
)
const polling = usePolling(
  refresh,
  () =>
    autoRefresh.value &&
    !command.pending.value &&
    endVersion.value === null &&
    !renaming.value &&
    !messaging.value &&
    !navigationBlocked.value,
)
onMounted(refresh)
watch(
  () => [
    game.value?.status,
    command.intent.value,
    command.pending.value,
    endVersion.value,
    renaming.value,
    messaging.value,
    navigationBlocked.value,
  ],
  () => {
    // Only a full accepted state may navigate. An old success receipt is not current state.
    if (
      game.value?.status === 1 &&
      !command.intent.value &&
      !command.pending.value &&
      endVersion.value === null &&
      !renaming.value &&
      !messaging.value &&
      !navigationBlocked.value
    )
      void router.replace(`/game/${gameId}/detail/`)
  },
)
function answer(value: { answer: string; wordId: number; version: number }) {
  if (blocked.value) return
  void command.submit({
    gameId,
    actorId,
    action: 'answer',
    word_id: value.wordId,
    answer: value.answer,
    expected_version: value.version,
  })
}
function restoreCollapsedFocus(event: Event) {
  const details = event.currentTarget as HTMLDetailsElement
  if (!details.open && details.contains(document.activeElement))
    details.querySelector('summary')?.focus()
}
function end() {
  if (endVersion.value === null) return
  const version = endVersion.value
  endVersion.value = null
  void command.submit({ gameId, actorId, action: 'end', expected_version: version })
}
</script>

<template>
  <section class="playing-page" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">
      <bdi>{{ game?.name ?? '对局' }}</bdi> #{{ gameId }}
    </h1>
    <nav class="actions" aria-label="对局导航">
      <RouterLink to="/">返回大厅</RouterLink>
      <RouterLink :to="`/game/${gameId}/detail/`">查看详情</RouterLink>
    </nav>
    <GameProgress v-if="game" :game="game" />
    <div class="sync-toolbar">
      <button
        v-if="error || feed.error.value"
        type="button"
        class="button"
        :disabled="pending"
        @click="refresh"
      >
        重试读取对局
      </button>
      <details class="sync-settings" @toggle="restoreCollapsedFocus">
        <summary>同步设置</summary>
        <div class="toolbar">
          <label class="checkbox-label"
            ><input v-model="feed.enabled.value" type="checkbox" />启用实时连接</label
          >
          <label class="checkbox-label"
            ><input v-model="autoRefresh" type="checkbox" />自动刷新（5 秒）</label
          >
        </div>
      </details>
    </div>
    <p class="hint" role="status">
      {{ feed.ready.value ? '实时连接已订阅' : '实时连接未就绪，新操作将尝试 HTTP' }}；{{
        !autoRefresh
          ? 'HTTP 自动刷新已手动关闭'
          : polling.paused.value
            ? 'HTTP 自动刷新已暂停（后台、离线或正在交互）'
            : 'HTTP 每 5 秒自动刷新，后台或离线时暂停'
      }}。
    </p>
    <NoticeBanner :message="error || feed.error.value" />
    <NoticeBanner :message="command.error.value" />
    <NoticeBanner :message="command.notice.value" kind="success" />
    <p v-if="pending" role="status">正在读取对局…</p>
    <SkeletonBlock v-if="pending && !game && !error" />
    <section
      v-if="command.intent.value"
      class="section-panel original-request"
      aria-label="原请求确认"
    >
      <p>
        {{ command.pending.value ? '正在提交或核对原请求…' : '原请求未确认，请先核对当前状态。' }}
      </p>
      <p>
        操作：{{ command.intent.value.action === 'answer' ? '提交答案' : '提前结束' }}；原版本
        {{ command.intent.value.expected_version }}
      </p>
      <p v-if="command.intent.value.action === 'answer'" class="multiline">
        原答案：{{ command.intent.value.answer }}
      </p>
      <p class="hint">
        刷新页面或离开会丢失本地请求意图。放弃回执不撤销已提交操作，重试仍使用原编号和参数。
      </p>
      <div class="actions">
        <button class="button" :disabled="command.pending.value" @click="command.retry">
          重试原请求
        </button>
        <button class="button" :disabled="command.pending.value" @click="command.dismiss">
          放弃回执并重新操作
        </button>
      </div>
    </section>
    <template v-if="game">
      <div class="playing-layout">
        <div class="answer-area">
          <GameTurn :game="game" :actor-id="actorId" :blocked="blocked" @answer="answer" />
          <GameAnswerFeedback :game="game" :actor-id="actorId" />
        </div>
        <GameSidebar :game="game" :spectators="feed.spectators.value" />
      </div>
      <div class="playing-history">
        <AnswerHistory :game="game" recent-first />
      </div>
      <details class="playing-details" @toggle="restoreCollapsedFocus">
        <summary>本局信息与规则</summary>
        <GameOverview :game="game" />
      </details>
      <details class="playing-details" @toggle="restoreCollapsedFocus">
        <summary>评分详情</summary>
        <GameScores :game="game" />
      </details>
      <!-- Editing controls stay outside collapsed regions; their modal and
           pending state must never become hidden while still blocking play. -->
      <section class="room-operations" aria-labelledby="room-operations-title">
        <h2 id="room-operations-title">房间操作</h2>
        <div class="actions">
          <GameNameControl
            :game="game"
            :disabled="blocked"
            @editing="renaming = $event"
            @changed="state.reconcile"
          />
          <button
            v-if="canEnd"
            type="button"
            class="button button-danger"
            :disabled="blocked"
            @click="endVersion = game.version"
          >
            提前结束对局
          </button>
        </div>
        <GameEndRequests :game="game" :disabled="blocked" @editing="messaging = $event" />
      </section>
    </template>
    <ModalDialog v-if="endVersion !== null" title="提前结束对局" @close="endVersion = null">
      <p>{{ game?.rated ? 'Rated · 按已答题结算 Rating' : 'Unrated · 不更新 Rating' }}</p>
      <p>
        确认按版本
        {{ endVersion }} 提前结束？仅按已接受的答题结算。状态若已变化，服务器将拒绝旧版本的新命令。
      </p>
      <button type="button" class="button button-danger" @click="end">确认结束</button>
    </ModalDialog>
  </section>
</template>

<style scoped>
.playing-page {
  min-width: 0;
}
.playing-page h1 {
  overflow-wrap: anywhere;
}
.sync-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: start;
  gap: 0.5rem 1rem;
  margin-block: 0.75rem;
}
.playing-page summary {
  min-height: 44px;
  padding: 0.55rem 0.25rem;
  cursor: pointer;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.sync-settings .toolbar {
  margin: 0.25rem 0;
}
.original-request {
  border-color: var(--ui-warning);
  background: var(--ui-warning-soft);
}
.playing-history,
.playing-details {
  min-width: 0;
  margin-block: 1rem;
  padding: 1rem;
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-md);
  background: var(--ui-surface);
}
.playing-history :deep(h2) {
  margin-top: 0;
}
.playing-details {
  padding-block: 0.25rem;
}
.playing-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(18rem, 23rem);
  gap: 1.5rem;
  align-items: start;
}
.answer-area {
  min-width: 0;
}
@media (max-width: 900px) {
  .playing-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
