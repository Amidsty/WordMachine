<script setup lang="ts">
import { computed } from 'vue'
import type { GameState } from './contracts'
import { participantIds, personName, personRating, storedPerf, storedText } from './presentation'
import UserLink from '../../shared/ui/UserLink.vue'

const props = defineProps<{ game: GameState; actorId: number }>()
// Projections of accepted records only. No receipt, local answer draft, cached
// last-non-null value or scoring/combination reconstruction enters this view.
const latest = computed(() => {
  const index = props.game.result.length - 1
  return index >= 0 ? { index, answer: props.game.result[index]! } : null
})
const own = computed(() => {
  for (let index = props.game.result.length - 1; index >= 0; index--) {
    const answer = props.game.result[index]!
    if (answer.uid === props.actorId) return { index, answer }
  }
  return null
})
const personal = computed(() => !!own.value || participantIds(props.game).has(props.actorId))
const entries = computed(() => {
  if (!latest.value) return []
  if (own.value?.index === latest.value.index)
    return [{ ...latest.value, label: '我的最近作答 · 本局最新' }]
  return [
    ...(own.value ? [{ ...own.value, label: '我的最近作答' }] : []),
    { ...latest.value, label: '本局最近作答' },
  ]
})
</script>

<template>
  <section class="answer-feedback" aria-labelledby="answer-feedback-title">
    <h2 id="answer-feedback-title">最近已接受作答</h2>
    <p v-if="!latest" class="hint">本局暂无已接受的作答。</p>
    <template v-else>
      <p v-if="personal && !own" class="hint">你尚无已接受的作答记录。</p>
      <article
        v-for="entry in entries"
        :key="entry.index"
        class="feedback-entry"
        :aria-label="entry.label"
      >
        <h3>{{ entry.label }} · 第 {{ entry.index + 1 }} 题</h3>
        <div class="feedback-meta">
          <UserLink
            :id="entry.answer.uid"
            :name="personName(game, entry.answer.uid)"
            :rating="personRating(game, entry.answer.uid)"
          />
          <span
            class="answer-outcome"
            :class="
              entry.answer.result === true
                ? 'answer-correct'
                : entry.answer.result === false
                  ? 'answer-wrong'
                  : 'answer-unknown'
            "
          >
            {{
              entry.answer.result === true
                ? '正确'
                : entry.answer.result === false
                  ? '错误'
                  : '判题未记录'
            }}
          </span>
        </div>
        <p class="feedback-answer multiline">
          提交答案：<bdi>{{ storedText(entry.answer.answer) }}</bdi>
        </p>
        <dl class="feedback-values">
          <div>
            <dt>该次保存 Perf</dt>
            <dd>{{ storedPerf(entry.answer.perf) }}</dd>
          </div>
          <div>
            <dt>该题 Perf 变化</dt>
            <dd>{{ storedPerf(entry.answer.perf_delta, true) }}</dd>
          </div>
        </dl>
      </article>
      <dl class="feedback-values combo-values">
        <div v-if="personal">
          <dt>
            你的个人连击<span v-if="own">（第 {{ own.index + 1 }} 题作答后）</span>
          </dt>
          <dd>{{ own ? (own.answer.usercombo ?? '未记录') : '尚未作答' }}</dd>
        </div>
        <div>
          <dt>房间全局连击（第 {{ latest.index + 1 }} 题作答后）</dt>
          <dd>{{ latest.answer.globalcombo ?? '未记录' }}</dd>
        </div>
      </dl>
      <p class="hint">
        Perf 显示一位小数，不是 Rating
        结算；连击取各自最近一次作答后的记录，错误后归零不代表没有惩罚。
      </p>
    </template>
    <p class="hint">来自已接受的本局记录，不代表原请求回执已确认。完整记录见下方答题记录。</p>
  </section>
</template>

<style scoped>
.answer-feedback {
  min-width: 0;
  margin-top: 1rem;
  padding: 1rem;
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-md);
  background: var(--ui-surface);
  overflow-wrap: anywhere;
}
.answer-feedback h2 {
  margin: 0 0 0.5rem;
}
.feedback-entry {
  padding-block: 0.75rem;
  border-bottom: 1px solid var(--ui-line);
}
.feedback-entry h3 {
  margin: 0 0 0.5rem;
  font-size: 1rem;
}
.feedback-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.5rem 1rem;
}
.feedback-meta > a {
  min-width: 0;
}
.answer-outcome {
  padding: 0.1rem 0.5rem;
  border: 1px solid currentColor;
  border-radius: var(--ui-radius-sm);
}
.answer-correct {
  color: var(--ui-positive);
  background: var(--ui-positive-soft);
}
.answer-wrong {
  color: var(--ui-negative);
  background: var(--ui-negative-soft);
}
.answer-unknown {
  color: var(--ui-text-muted);
}
.feedback-answer {
  margin-block: 0.5rem;
}
.feedback-values {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem 1rem;
  margin: 0.5rem 0 0;
}
.feedback-values dt {
  color: var(--ui-text-muted);
  font-size: 0.875rem;
}
.feedback-values dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}
.combo-values {
  margin-block: 0.75rem;
}
@media (max-width: 400px) {
  .feedback-values {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
