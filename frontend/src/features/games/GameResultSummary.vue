<script setup lang="ts">
import { computed } from 'vue'
import type { GameState } from './contracts'
import { scoreRows, storedNumber, storedPerf } from './presentation'

const props = defineProps<{ game: GameState; actorId: number }>()
const rows = computed(() => scoreRows(props.game))
const own = computed(() => rows.value.find((row) => row.id === props.actorId && row.participant))
const settlement = computed(
  () => props.game.scoring?.players.find((player) => player.user_id === props.actorId)?.settlement,
)
const hasSettlement = computed(() =>
  props.game.scoring
    ? props.game.scoring.players.some((player) => !!player.settlement)
    : rows.value.some((row) => !!row.rating),
)
const titles = { '-1': '等待开局', '0': '对局进行中', '1': '对局已结束', '2': '对局已取消' }
function changeClass(value: number | null | undefined) {
  return value == null || value === 0
    ? 'change-neutral'
    : value > 0
      ? 'change-positive'
      : 'change-negative'
}
</script>

<template>
  <section class="result-summary" aria-labelledby="result-summary-title">
    <h2 id="result-summary-title">{{ titles[game.status] }}</h2>
    <p class="result-mode">
      {{ game.rated ? 'Rated · 计入 Rating' : 'Unrated · 不更新 Rating' }}
    </p>
    <p v-if="game.status === -1">报名、退出、开局或取消请返回大厅；尚未产生本局结算。</p>
    <p v-else-if="game.status === 0">以下为当前已接受记录；对局尚未结算。</p>
    <p v-else-if="game.status === 2">已取消，未结算。</p>
    <p v-else-if="!game.rated">
      {{
        game.result.length ? '本局练习表现已记录，不更新 Rating。' : '本局未作答，不更新 Rating。'
      }}
    </p>
    <p v-else-if="hasSettlement">已保存 Rating 结算记录；各参赛者以各自记录为准。</p>
    <p v-else>未记录 Rating 结算，不从表现或当前余额推算。</p>

    <section
      v-if="own && (game.status === 0 || game.status === 1)"
      class="personal-result"
      aria-labelledby="personal-result-title"
    >
      <h3 id="personal-result-title">{{ game.status === 0 ? '我的本局表现' : '我的本局结果' }}</h3>
      <dl class="personal-perf">
        <dt>{{ game.status === 0 ? '当前保存 Perf' : '最后保存 Perf' }}</dt>
        <dd>{{ own.answered ? storedPerf(own.perf) : own.rating ? '答题记录缺失' : '未作答' }}</dd>
      </dl>
      <p v-if="own.answered" class="hint">
        已接受作答 {{ own.answered }} 条；正确 {{ own.correct }} / 错误 {{ own.wrong }} / 未记录
        {{ own.unknown }}。Perf 保留一位小数，不是 Rating 变化。
      </p>
      <p v-else-if="own.rating" class="hint">
        已有保存的评分记录，但缺少答题记录；不据此删除结算或补造 Perf。
      </p>
      <template v-if="game.status === 1">
        <p v-if="!game.rated">
          {{ own.answered ? '练习表现已记录，不更新 Rating。' : '未作答，不更新 Rating。' }}
        </p>
        <template v-else-if="game.scoring">
          <template v-if="settlement">
            <dl class="settlement-parts">
              <div>
                <dt>本局 Rating 变化</dt>
                <dd :class="changeClass(settlement.total_delta)">
                  {{ storedNumber(settlement.total_delta, true) }}
                </dd>
              </div>
            </dl>
            <dl class="settlement-balances">
              <div>
                <dt>赛后 Rating</dt>
                <dd>{{ settlement.public_after }}</dd>
              </div>
            </dl>
            <p class="hint">以上为本局结算结果，不是当前 Rating。</p>
          </template>
          <p v-else>无本局 Rating 结算记录。</p>
        </template>
        <template v-else>
          <dl v-if="own.rating" class="settlement-balances legacy-result">
            <div>
              <dt>已保存本局 Rating 变化</dt>
              <dd :class="changeClass(own.rating.delta)">
                {{ storedNumber(own.rating.delta, true) }}
              </dd>
            </div>
            <div>
              <dt>已保存赛后公开 Rating</dt>
              <dd>{{ storedNumber(own.rating.new_rating) }}</dd>
            </div>
          </dl>
          <p v-else>无本局 Rating 结算记录。</p>
          <p class="hint">以上为本局结算结果，不是当前 Rating。</p>
        </template>
      </template>
    </section>
    <p v-else-if="game.status === 0 || game.status === 1" class="hint">
      你不在本局参赛汇总中；此处不生成个人结果，保存记录仍可在下方明细查看。
    </p>
  </section>
</template>

<style scoped>
.result-summary {
  margin-block: 1rem;
  padding: clamp(1rem, 3vw, 2rem);
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-lg);
  background: var(--ui-surface);
  overflow-wrap: anywhere;
}
.result-summary h2 {
  margin: 0;
  font-size: clamp(1.5rem, 3vw, 2rem);
}
.result-mode {
  color: var(--ui-text-muted);
  font-weight: 600;
}
.personal-result {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--ui-line);
}
.personal-result h3 {
  margin: 0 0 0.75rem;
  font-size: 1.125rem;
}
.personal-result dl {
  margin-block: 0.75rem;
}
.personal-result dt {
  color: var(--ui-text-muted);
}
.personal-result dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}
.personal-perf dd,
.settlement-parts dd {
  font-size: clamp(1.5rem, 3vw, 2rem);
  font-weight: 650;
}
.settlement-parts,
.settlement-balances {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 1rem;
}
.settlement-parts > div {
  padding-block: 0.5rem;
  border-bottom: 1px solid var(--ui-line);
}
.legacy-result {
  grid-template-columns: repeat(2, minmax(0, 1fr));
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
@media (max-width: 600px) {
  .settlement-parts,
  .settlement-balances {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
