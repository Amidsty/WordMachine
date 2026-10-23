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
const blocked = computed(
  () =>
    !!command.intent.value ||
    command.pending.value ||
    !!error.value ||
    endVersion.value !== null ||
    renaming.value ||
    messaging.value,
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
    !messaging.value,
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
  ],
  () => {
    // Only a full accepted state may navigate. An old success receipt is not current state.
    if (
      game.value?.status === 1 &&
      !command.intent.value &&
      !command.pending.value &&
      endVersion.value === null &&
      !renaming.value &&
      !messaging.value
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
function end() {
  if (endVersion.value === null) return
  const version = endVersion.value
  endVersion.value = null
  void command.submit({ gameId, actorId, action: 'end', expected_version: version })
}
</script>

<template>
  <section class="workspace" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">
      <bdi>{{ game?.name ?? '对局' }}</bdi> #{{ gameId }}
    </h1>
    <nav class="actions" aria-label="对局导航">
      <RouterLink to="/">返回大厅</RouterLink>
      <RouterLink :to="`/game/${gameId}/detail/`">查看详情</RouterLink>
    </nav>
    <div class="toolbar">
      <button type="button" class="button" :disabled="pending" @click="refresh">刷新对局</button>
      <label class="checkbox-label"
        ><input v-model="feed.enabled.value" type="checkbox" />启用实时连接</label
      >
      <label class="checkbox-label"
        ><input v-model="autoRefresh" type="checkbox" />自动刷新（5 秒）</label
      >
    </div>
    <p class="hint" role="status">
      {{ feed.ready.value ? '实时连接已订阅' : '实时连接未就绪，写操作使用 HTTP' }}；{{
        polling.paused.value ? '自动刷新已暂停' : '后台或离线时暂停轮询'
      }}。
    </p>
    <NoticeBanner :message="error || feed.error.value" />
    <NoticeBanner :message="command.error.value" />
    <NoticeBanner :message="command.notice.value" kind="success" />
    <p v-if="pending" role="status">正在读取对局…</p>
    <section v-if="command.intent.value" class="section-panel" aria-label="原请求确认">
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
          <button
            v-if="canEnd"
            class="button button-danger"
            :disabled="blocked"
            @click="endVersion = game.version"
          >
            提前结束对局
          </button>
        </div>
        <GameSidebar :game="game" :spectators="feed.spectators.value" />
      </div>
      <GameNameControl
        :game="game"
        :disabled="blocked"
        @editing="renaming = $event"
        @changed="state.reconcile"
      />
      <GameEndRequests :game="game" :disabled="blocked" @editing="messaging = $event" />
      <GameOverview :game="game" />
      <GameScores :game="game" />
      <AnswerHistory :game="game" recent-first />
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
