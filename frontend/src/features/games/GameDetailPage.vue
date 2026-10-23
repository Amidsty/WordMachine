<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useServices } from '../../app/services'
import { usePolling } from '../../shared/data/usePolling'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import { useGameState } from './useGameState'
import GameOverview from './GameOverview.vue'
import GameEndRequests from './GameEndRequests.vue'
import GameNameControl from './GameNameControl.vue'
import GameScores from './GameScores.vue'
import AnswerHistory from './AnswerHistory.vue'

const services = useServices()
const gameId = Number(useRoute().params.id)
const { game, pending, error, refresh } = useGameState((signal) =>
  services.games.get(gameId, signal),
)
const autoRefresh = ref(true)
const renaming = ref(false)
const messaging = ref(false)
const polling = usePolling(refresh, () => autoRefresh.value && !renaming.value && !messaging.value)
onMounted(refresh)
</script>

<template>
  <section class="workspace" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">
      <template v-if="game?.name"
        ><bdi>{{ game.name }}</bdi> · </template
      >对局详情<span v-if="game"> #{{ game.id }}</span>
    </h1>
    <nav class="actions" aria-label="对局导航">
      <RouterLink to="/">返回大厅</RouterLink>
      <RouterLink v-if="game?.status === 0" :to="`/game/${game.id}/`">进入对局 / 观战</RouterLink>
    </nav>
    <div class="toolbar">
      <button type="button" class="button" :disabled="pending" @click="refresh">刷新详情</button>
      <label class="checkbox-label"
        ><input v-model="autoRefresh" type="checkbox" />自动刷新（5 秒）</label
      >
      <span class="hint">{{
        polling.paused.value ? '自动刷新已暂停' : '后台或离线时自动暂停'
      }}</span>
    </div>
    <NoticeBanner :message="error" />
    <p v-if="pending" role="status">{{ game ? '正在刷新对局…' : '正在加载对局…' }}</p>
    <template v-if="game">
      <GameNameControl
        :game="game"
        :disabled="messaging"
        @editing="renaming = $event"
        @changed="refresh"
      />
      <GameEndRequests :game="game" :disabled="renaming" @editing="messaging = $event" />
      <GameOverview :game="game" />
      <GameScores :game="game" />
      <AnswerHistory :game="game" />
    </template>
  </section>
</template>
