<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { usePagedResource } from '../../shared/data/usePagedResource'
import DataTable from '../../shared/ui/DataTable.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import { storedNumber, storedPerf } from '../games/presentation'
import type { HistoryKind, RatingHistory, PerfHistory } from './history'

const props = defineProps<{ uid: number; kind: HistoryKind }>()
const services = useServices()
const title = computed(() => (props.kind === 'rating' ? 'Rating 历史' : 'Perf 历史'))
const rows = usePagedResource<RatingHistory | PerfHistory>((query, signal) =>
  props.kind === 'rating'
    ? services.history.ratings(props.uid, query, signal)
    : services.history.perfs(props.uid, query, signal),
)
onMounted(rows.load)
watch(services.userChanges, rows.load)
const labels = { legacy: '旧记录', game: 'Rated 比赛', manual: '人工调整' }
</script>

<template>
  <section class="section-panel" :aria-label="title">
    <h2>{{ title }}</h2>
    <p v-if="kind === 'rating'" class="hint">
      按历史记录顺序倒序展示，包含比赛结算和人工调整；不公开人工调整的私有原因及操作者。Unrated
      不产生 Rating 记录。
    </p>
    <p v-else class="hint">
      按房间号倒序展示已结束对局的最终保存 Perf，包含 Rated /
      Unrated；未作答或记录缺失不会补为零。显示保留一位小数，不改变原值。
    </p>
    <button type="button" class="button" :disabled="rows.loading.value" @click="rows.load">
      刷新{{ title }}
    </button>
    <NoticeBanner :message="rows.error.value" />
    <p v-if="rows.result.value">共 {{ rows.result.value.pagination.total }} 条记录</p>
    <DataTable
      :caption="title"
      :loading="rows.loading.value"
      :empty="!rows.result.value?.items.length"
    >
      <template #head
        ><tr>
          <th>来源 / 对局</th>
          <th>时间（UTC）</th>
          <template v-if="kind === 'rating'"
            ><th>变化前</th>
            <th>变化</th>
            <th>变化后</th>
            <th>竞技变化</th>
            <th>新手额度</th>
            <th>规则</th></template
          >
          <template v-else
            ><th>模式</th>
            <th>作答数</th>
            <th>最终 Perf</th>
            <th>规则</th></template
          >
        </tr></template
      >
      <tr
        v-for="(row, index) in rows.result.value?.items"
        :key="`${kind}:${rows.page.value}:${index}`"
      >
        <td>
          <template v-if="'after' in row">{{ labels[row.source] }}<br /></template>
          <RouterLink
            v-if="row.game_id !== null && (!('game_available' in row) || row.game_available)"
            :to="`/game/${row.game_id}/detail/`"
            ><bdi>{{ row.game_name ?? '对局' }}</bdi> #{{ row.game_id }}</RouterLink
          >
          <span v-else-if="row.game_id !== null">对局 #{{ row.game_id }}（记录不可用）</span>
          <span v-else>—</span>
        </td>
        <td>{{ row.recorded_at ?? '时间未记录' }}</td>
        <template v-if="'after' in row"
          ><td>{{ storedNumber(row.before) }}</td>
          <td>{{ storedNumber(row.delta, true) }}</td>
          <td>{{ storedNumber(row.after) }}</td>
          <td>{{ storedNumber(row.competitive_delta, true) }}</td>
          <td>{{ storedNumber(row.newcomer_bonus, true) }}</td>
          <td>{{ row.rule_version ?? '未记录' }}</td></template
        >
        <template v-else
          ><td>{{ row.rated ? 'Rated' : 'Unrated' }}</td>
          <td>{{ row.answered_count }}</td>
          <td :title="row.perf === null ? undefined : String(row.perf)">
            {{ row.missing_reason === 'no_answers' ? '未作答' : storedPerf(row.perf) }}
          </td>
          <td>{{ row.rule_version ?? '未记录' }}</td></template
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
