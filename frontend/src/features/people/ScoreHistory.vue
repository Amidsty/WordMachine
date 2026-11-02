<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { useAutoRefresh } from '../../app/useAutoRefresh'
import { usePagedResource } from '../../shared/data/usePagedResource'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import { storedNumber, storedPerf } from '../games/presentation'
import type { CombinedHistory } from './history'
import { localHistoryTime } from './historyTime'

const props = defineProps<{ uid: number }>()
const services = useServices()
const title = 'Rating / Perf 历史'
const rows = usePagedResource<CombinedHistory>((query, signal) =>
  services.history.combined(props.uid, query, signal),
)
const displayedRows = computed(() =>
  (rows.result.value?.items ?? []).map((row) => ({
    ...row,
    time: localHistoryTime(row.recorded_at),
    perfTime:
      row.rating && row.perf && row.perf.recorded_at !== row.recorded_at
        ? localHistoryTime(row.perf.recorded_at)
        : null,
    game: row.rating ?? row.perf!,
    available: row.rating ? row.rating.game_available : true,
  })),
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
    <p class="hint">按已保存时间倒序，时间未记录的列在末尾；时间按浏览器本地时区显示。</p>
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
          <th scope="col">模式</th>
          <th scope="col">作答数</th>
          <th scope="col">Perf</th>
          <th scope="col">Rating 前</th>
          <th scope="col">变化</th>
          <th scope="col">Rating 后</th>
          <th scope="col">原因</th>
          <th scope="col">操作者</th>
        </tr></template
      >
      <tr v-for="row in displayedRows" :key="row.key">
        <td class="history-time">
          <time v-if="row.time.datetime" :datetime="row.time.datetime">{{ row.time.text }}</time>
          <span v-else>{{ row.time.text }}</span>
          <small v-if="row.perfTime"
            ><br />Perf：<time v-if="row.perfTime.datetime" :datetime="row.perfTime.datetime">{{
              row.perfTime.text
            }}</time
            ><span v-else>{{ row.perfTime.text }}</span></small
          >
        </td>
        <td>
          <template v-if="row.rating">{{ labels[row.rating.source] }}<br /></template>
          <RouterLink
            v-if="row.game.game_id !== null && row.available"
            :to="`/game/${row.game.game_id}/detail/`"
            ><bdi>{{ row.game.game_name ?? '对局' }}</bdi> #{{ row.game.game_id }}</RouterLink
          >
          <span v-else-if="row.game.game_id !== null"
            >对局 #{{ row.game.game_id }}（记录不可用）</span
          >
        </td>
        <td>
          {{
            row.rating?.source === 'manual'
              ? '—'
              : row.perf
                ? row.perf.rated
                  ? 'Rated'
                  : 'Unrated'
                : row.rating?.source === 'game'
                  ? 'Rated'
                  : '记录缺失'
          }}
        </td>
        <td class="numeric">{{ row.perf?.answered_count ?? '—' }}</td>
        <td class="numeric" :title="row.perf?.perf == null ? undefined : String(row.perf.perf)">
          {{
            row.rating?.source === 'manual'
              ? '不适用'
              : row.perf?.missing_reason === 'no_answers'
                ? '未作答'
                : storedPerf(row.perf?.perf ?? null)
          }}
        </td>
        <td class="numeric">{{ row.rating ? storedNumber(row.rating.before) : '—' }}</td>
        <td class="numeric" :class="changeClass(row.rating?.delta)">
          {{
            row.rating
              ? storedNumber(row.rating.delta, true)
              : row.perf?.rated
                ? '无评分记录'
                : '不计分'
          }}
        </td>
        <td class="numeric">{{ row.rating ? storedNumber(row.rating.after) : '—' }}</td>
        <td class="reason-cell">
          <span
            v-if="row.rating?.source === 'manual' && row.rating.reason !== undefined"
            class="multiline manual-reason"
            >{{ row.rating.reason }}</span
          >
        </td>
        <td>
          <span
            v-if="row.rating?.source === 'manual' && row.rating.actor_id !== undefined"
            class="manual-actor"
            ><RouterLink :to="`/user/${row.rating.actor_id}/`"
              >用户 #{{ row.rating.actor_id }}</RouterLink
            ></span
          >
        </td>
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
