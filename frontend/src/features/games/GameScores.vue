<script setup lang="ts">
import WeightedScores from './WeightedScores.vue'
import { computed } from 'vue'
import type { GameState } from './contracts'
import { personRating, scoreRows, storedNumber, storedPerf } from './presentation'
import UserLink from '../../shared/ui/UserLink.vue'
import DataTable from '../../shared/ui/DataTable.vue'
const props = defineProps<{ game: GameState }>()
const rows = computed(() => scoreRows(props.game))
const unassigned = computed(() => props.game.result.filter((answer) => answer.uid == null).length)
</script>

<template>
  <WeightedScores :game="game" />
  <section aria-labelledby="game-scores-title">
    <h2 id="game-scores-title">作答与评分</h2>
    <p class="hint">
      Perf
      使用最后一条已保存的个人答题记录，仅显示四舍五入后的一位小数；原始数值不变。无答题记录或字段缺失时不补成
      0，也不重算。
    </p>
    <p class="hint">Rating 仅展示本局保存的结算增量和结算后数值，不是用户当前 Rating。</p>
    <p v-if="unassigned" class="notice notice-info">
      {{ unassigned }} 条记录缺少作答者，未归入个人统计。
    </p>
    <DataTable caption="本局作答与评分" :loading="false" :empty="rows.length === 0">
      <template #head>
        <tr>
          <th scope="col">用户</th>
          <th scope="col">正确 / 错误 / 未记录</th>
          <th scope="col">Perf</th>
          <th scope="col">本局 Rating 增量</th>
          <th scope="col">本局结算后 Rating</th>
        </tr>
      </template>
      <tr v-for="row in rows" :key="row.id">
        <td class="multiline">
          <UserLink :id="row.id" :name="row.name" :rating="personRating(game, row.id)" /><small
            v-if="!row.participant"
            >（不在参赛汇总中）</small
          >
        </td>
        <td>{{ row.correct }} / {{ row.wrong }} / {{ row.unknown }}</td>
        <td>{{ row.answered ? storedPerf(row.perf) : '无答题记录' }}</td>
        <template v-if="game.status !== 1">
          <td colspan="2">{{ game.status === 2 ? '已取消，未结算' : '尚未结算' }}</td>
        </template>
        <td v-else-if="!game.rated" colspan="2">Unrated · 不更新 Rating</td>
        <template v-else-if="row.rating">
          <td>{{ storedNumber(row.rating.delta, true) }}</td>
          <td>{{ storedNumber(row.rating.new_rating) }}</td>
        </template>
        <td v-else colspan="2">无本局评分记录</td>
      </tr>
    </DataTable>
  </section>
</template>
