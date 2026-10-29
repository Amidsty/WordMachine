<script setup lang="ts">
import { computed } from 'vue'
import UserLink from '../../shared/ui/UserLink.vue'
import type { GameSpectator, GameState } from './contracts'
import { participantIds, personRating, scoreRows, storedPerf } from './presentation'

const props = defineProps<{ game: GameState; spectators: GameSpectator[] | null }>()
const rows = computed(() => scoreRows(props.game).filter((row) => row.participant))
// A newer game state may arrive before presence; never list known participants as spectators.
const viewers = computed(() => {
  const members = participantIds(props.game)
  return props.spectators?.filter((user) => !members.has(user.id)) ?? null
})
</script>

<template>
  <aside class="game-sidebar" aria-label="比赛状态栏">
    <section class="section-panel" aria-labelledby="player-status-title">
      <h2 id="player-status-title">参赛者状态</h2>
      <p class="hint">答对 / 答错 · 当前 Perf</p>
      <p v-if="!rows.length" class="hint">暂无参赛者</p>
      <ul v-else class="game-status-list" aria-label="参赛者状态">
        <li
          v-for="row in rows"
          :key="row.id"
          :class="{ 'current-player': game.next_turn === row.id }"
        >
          <UserLink :id="row.id" :name="row.name" :rating="personRating(game, row.id)" />
          <span :aria-label="`答对 ${row.correct}，答错 ${row.wrong}`">
            {{ row.correct }} / {{ row.wrong }}
            <small v-if="row.unknown">（未记录 {{ row.unknown }}）</small>
          </span>
          <span class="perf-value">Perf {{ row.answered ? storedPerf(row.perf) : '未作答' }}</span>
          <small v-if="game.next_turn === row.id" class="turn-label">轮到答题</small>
        </li>
      </ul>
      <p class="hint">Perf 取最后一次已保存的作答；缺失值不补成 0。</p>
    </section>
    <section class="section-panel" aria-labelledby="spectators-title">
      <h2 id="spectators-title">
        观战用户<span v-if="viewers !== null">（{{ viewers.length }}）</span>
      </h2>
      <p v-if="viewers === null" class="hint" role="status">观战名单暂不可用，等待实时连接确认。</p>
      <p v-else-if="!viewers.length" class="hint">暂无在线观战用户</p>
      <ul v-else class="spectator-list" aria-label="观战用户">
        <li v-for="user in viewers" :key="user.id">
          <UserLink
            :id="user.id"
            :name="user.username ?? `用户 #${user.id}（资料缺失）`"
            :rating="user.rating"
          />
        </li>
      </ul>
      <p class="hint">
        显示已连接本比赛页、未参赛的用户；同一账号多页面只列一次。关闭实时连接后不计入。
      </p>
    </section>
  </aside>
</template>

<style scoped>
.game-sidebar {
  min-width: 0;
}
.game-sidebar .section-panel {
  background: var(--ui-surface);
}
.game-sidebar .section-panel:first-child {
  margin-top: 0;
}
.game-sidebar h2 {
  margin-top: 0;
}
.game-status-list,
.spectator-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.game-status-list li {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.4rem 0.75rem;
  padding: 0.75rem 0.5rem;
  border-bottom: 1px solid var(--border);
  overflow-wrap: anywhere;
}
.game-status-list li > a {
  flex: 1 1 5rem;
  min-width: 0;
}
.current-player {
  border-left: 3px solid var(--primary);
}
.perf-value {
  font-variant-numeric: tabular-nums;
}
.turn-label {
  flex-basis: 100%;
}
.spectator-list li {
  padding: 0.5rem;
  overflow-wrap: anywhere;
}
</style>
