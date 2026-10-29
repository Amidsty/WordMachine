<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useServices } from '../../app/services'
import { useAutoRefresh } from '../../app/useAutoRefresh'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import { useGameState } from './useGameState'
import GameOverview from './GameOverview.vue'
import GameEndRequests from './GameEndRequests.vue'
import GameNameControl from './GameNameControl.vue'
import GameScores from './GameScores.vue'
import AnswerHistory from './AnswerHistory.vue'
import GameResultSummary from './GameResultSummary.vue'
import SkeletonBlock from '../../shared/ui/SkeletonBlock.vue'

const services = useServices()
const gameId = Number(useRoute().params.id)
const actorId = services.client.session.value?.user?.id ?? 0
const scoresSection = ref<HTMLElement>()
function showScores() {
  scoresSection.value?.focus()
  scoresSection.value?.scrollIntoView({ block: 'start' })
}
const { game, pending, error, refresh } = useGameState((signal) =>
  services.games.get(gameId, signal),
)
const autoRefresh = ref(true)
const renaming = ref(false)
const messaging = ref(false)
const polling = useAutoRefresh(
  refresh,
  () => autoRefresh.value && !renaming.value && !messaging.value,
  5000,
)
onMounted(refresh)
</script>

<template>
  <section class="detail-page" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">
      <template v-if="game?.name"
        ><bdi>{{ game.name }}</bdi> · </template
      >对局详情<span v-if="game"> #{{ game.id }}</span>
    </h1>
    <nav class="actions" aria-label="对局导航">
      <RouterLink to="/" class="button" :class="{ 'button-primary': game?.status !== 0 }"
        >返回大厅</RouterLink
      >
      <RouterLink v-if="game?.status === 0" class="button button-primary" :to="`/game/${game.id}/`"
        >进入对局 / 观战</RouterLink
      >
      <button v-if="game" type="button" class="button" @click="showScores">
        查看所有参赛者与明细
      </button>
    </nav>
    <div class="toolbar">
      <button v-if="error" type="button" class="button" :disabled="pending" @click="refresh">
        重试读取详情
      </button>
      <label class="checkbox-label"
        ><input v-model="autoRefresh" type="checkbox" />自动刷新（5 秒）</label
      >
      <span class="hint">{{
        polling.paused.value ? '自动刷新已暂停' : '后台或离线时自动暂停'
      }}</span>
    </div>
    <NoticeBanner :message="error" />
    <p v-if="pending" role="status">{{ game ? '正在刷新对局…' : '正在加载对局…' }}</p>
    <SkeletonBlock v-if="pending && !game && !error" />
    <template v-if="game">
      <GameResultSummary :game="game" :actor-id="actorId" />
      <section
        id="detail-scores"
        ref="scoresSection"
        class="detail-section"
        tabindex="-1"
        aria-label="所有参赛者与评分明细"
      >
        <GameScores :game="game" />
      </section>
      <div class="detail-history"><AnswerHistory :game="game" /></div>
      <div class="detail-config"><GameOverview :game="game" /></div>
      <section class="detail-operations" aria-labelledby="detail-operations-title">
        <h2 id="detail-operations-title">房间操作</h2>
        <GameNameControl
          :game="game"
          :disabled="messaging"
          @editing="renaming = $event"
          @changed="refresh"
        />
        <GameEndRequests :game="game" :disabled="renaming" @editing="messaging = $event" />
      </section>
    </template>
  </section>
</template>

<style scoped>
.detail-page,
.detail-section {
  min-width: 0;
}
.detail-page h1 {
  overflow-wrap: anywhere;
}
.detail-section,
.detail-history,
.detail-config {
  margin-block: 1.5rem;
  padding: 1rem;
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-md);
  background: var(--ui-surface);
}
.detail-section {
  scroll-margin-block-start: 1rem;
}
.detail-history :deep(h2),
.detail-config :deep(h2) {
  margin-top: 0;
}
</style>
