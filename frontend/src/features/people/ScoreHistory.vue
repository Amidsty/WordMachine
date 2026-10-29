<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { useAutoRefresh } from '../../app/useAutoRefresh'
import { usePagedResource } from '../../shared/data/usePagedResource'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import { storedNumber, storedPerf } from '../games/presentation'
import type { HistoryKind, RatingHistory, PerfHistory } from './history'
import { localHistoryTime } from './historyTime'

const props = defineProps<{ uid: number; kind: HistoryKind }>()
const services = useServices()
const title = computed(() => (props.kind === 'rating' ? 'Rating 历史' : 'Perf 历史'))
const rows = usePagedResource<RatingHistory | PerfHistory>((query, signal) =>
  props.kind === 'rating'
    ? services.history.ratings(props.uid, query, signal)
    : services.history.perfs(props.uid, query, signal),
)
const displayedRows = computed(() =>
  (rows.result.value?.items ?? []).map((row) => ({ row, time: localHistoryTime(row.recorded_at) })),
)
onMounted(rows.load)
useAutoRefresh(rows.refresh)
watch(services.userChanges, rows.load)
const labels = { legacy: '旧记录', game: 'Rated 比赛', manual: '人工调整' }
function changeClass(value: number | null | undefined) {
  return value == null || value === 0
    ? 'change-neutral'
    : value > 0
      ? 'change-positive'
      : 'change-negative'
}
</script>

<template>
  <section class="score-history" :aria-label="title">
    <h2 tabindex="-1">{{ title }}</h2>
    <p v-if="kind === 'rating'" class="hint">
      按历史记录顺序倒序展示，包含比赛结算和人工调整；仅显示操作者为该次调整选择公开的原因和身份。Unrated
      不产生 Rating 记录。
    </p>
    <p v-else class="hint">
      按房间号倒序展示已结束对局的最终保存 Perf，包含 Rated /
      Unrated；未作答或记录缺失不会补为零。显示保留一位小数，不改变原值。
    </p>
    <p class="hint">时间按浏览器的本地时区显示。</p>
    <button
      v-if="rows.error.value"
      type="button"
      class="button"
      :disabled="rows.loading.value"
      @click="rows.load"
    >
      重试读取{{ title }}
    </button>
    <p v-if="rows.result.value">共 {{ rows.result.value.pagination.total }} 条记录</p>
    <DataTable
      :caption="title"
      :loading="rows.loading.value"
      :error="rows.error.value"
      :empty="!rows.result.value?.items.length"
    >
      <template #head
        ><tr>
          <th scope="col">时间</th>
          <th scope="col">来源</th>
          <template v-if="kind === 'rating'"
            ><th scope="col">变化前</th>
            <th scope="col">变化</th>
            <th scope="col">变化后</th>
            <th scope="col">原因</th>
            <th scope="col">操作者</th></template
          >
          <template v-else
            ><th scope="col">模式</th>
            <th scope="col">作答数</th>
            <th scope="col">最终 Perf</th></template
          >
        </tr></template
      >
      <tr
        v-for="({ row, time }, index) in displayedRows"
        :key="`${kind}:${rows.page.value}:${index}`"
      >
        <td class="history-time">
          <time v-if="time.datetime" :datetime="time.datetime">{{ time.text }}</time>
          <span v-else>{{ time.text }}</span>
        </td>
        <td>
          <template v-if="'after' in row">{{ labels[row.source] }}<br /></template>
          <RouterLink
            v-if="row.game_id !== null && (!('game_available' in row) || row.game_available)"
            :to="`/game/${row.game_id}/detail/`"
            ><bdi>{{ row.game_name ?? '对局' }}</bdi> #{{ row.game_id }}</RouterLink
          >
          <span v-else-if="row.game_id !== null">对局 #{{ row.game_id }}（记录不可用）</span>
          <span v-else-if="!('after' in row) || row.source !== 'manual'">—</span>
        </td>
        <template v-if="'after' in row"
          ><td class="numeric">{{ storedNumber(row.before) }}</td>
          <td class="numeric" :class="changeClass(row.delta)">
            {{ storedNumber(row.delta, true) }}
          </td>
          <td class="numeric">{{ storedNumber(row.after) }}</td>
          <td class="reason-cell">
            <span
              v-if="row.source === 'manual' && row.reason !== undefined"
              class="multiline manual-reason"
              >{{ row.reason }}</span
            >
          </td>
          <td>
            <span v-if="row.source === 'manual' && row.actor_id !== undefined" class="manual-actor">
              <RouterLink :to="`/user/${row.actor_id}/`">用户 #{{ row.actor_id }}</RouterLink>
            </span>
          </td>
        </template>
        <template v-else
          ><td>{{ row.rated ? 'Rated' : 'Unrated' }}</td>
          <td class="numeric">{{ row.answered_count }}</td>
          <td class="numeric" :title="row.perf === null ? undefined : String(row.perf)">
            {{ row.missing_reason === 'no_answers' ? '未作答' : storedPerf(row.perf) }}
          </td></template
        >
      </tr>
    </DataTable>
    <PaginationBar
      v-if="rows.result.value && rows.result.value.pagination.pages > 1"
      :pagination="rows.result.value.pagination"
      :label="`${title}分页`"
      @page="rows.goToPage"
    />
  </section>
</template>

<style scoped>
.score-history {
  min-width: 0;
}
th,
td {
  border: 1px solid var(--ui-line);
}
th {
  background: var(--ui-surface-muted);
}
.history-time {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.reason-cell {
  max-width: 28rem;
  overflow-wrap: anywhere;
}
.manual-reason {
  display: inline-block;
  min-width: 8rem;
  max-width: 28rem;
}
.manual-actor {
  white-space: nowrap;
}
.numeric {
  text-align: right;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.change-positive {
  color: var(--ui-positive);
}
.change-negative {
  color: var(--ui-negative);
}
.change-neutral {
  color: var(--ui-text);
}
</style>
