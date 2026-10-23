<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { GameState } from './contracts'
import { personName, personRating, storedText } from './presentation'
import UserLink from '../../shared/ui/UserLink.vue'
import FormField from '../../shared/ui/FormField.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
const props = defineProps<{ game: GameState; actorId: number; blocked: boolean }>()
const emit = defineEmits<{ answer: [value: { answer: string; wordId: number; version: number }] }>()
const answer = ref('')
const form = ref<HTMLFormElement>()
async function focusTurn() {
  await nextTick()
  if (canAnswer.value && !props.blocked && !document.hidden)
    form.value?.querySelector<HTMLInputElement>('input')?.focus()
}
onMounted(focusTurn)
const canAnswer = computed(
  () => props.game.status === 0 && props.game.next_turn === props.actorId && !!props.game.next_word,
)
// Renames/equal-version refreshes and storage conversions must not erase the draft.
watch(
  () => [props.game.current_index, props.game.status, props.game.next_word?.id],
  (next, previous) => {
    if (next.some((value, index) => value !== previous[index])) {
      answer.value = ''
      void focusTurn()
    }
  },
)
function submit() {
  if (props.blocked || !canAnswer.value || !answer.value.trim() || !props.game.next_word) return
  emit('answer', {
    answer: answer.value,
    wordId: props.game.next_word.id,
    version: props.game.version,
  })
}
</script>

<template>
  <section class="section-panel" aria-labelledby="game-turn-title">
    <h2 id="game-turn-title">当前题目</h2>
    <template v-if="game.status === 0 && game.next_word">
      <p class="game-prompt multiline">{{ storedText(game.next_word.chinese) }}</p>
      <p>
        当前轮次：<template v-if="game.next_turn === actorId">你</template
        ><UserLink
          v-else
          :id="game.next_turn"
          :name="personName(game, game.next_turn)"
          :rating="personRating(game, game.next_turn)"
        />
      </p>
      <p v-if="!canAnswer" class="hint">等待其他参赛者作答；观众不能答题。</p>
      <form ref="form" @submit.prevent="submit">
        <fieldset :disabled="blocked || !canAnswer">
          <legend class="sr-only">提交本轮答案</legend>
          <FormField
            id="game-answer"
            v-model="answer"
            label="英文答案"
            autocomplete="off"
            :maxlength="255"
            required
          />
          <SubmitButton :pending="false">提交答案</SubmitButton>
        </fieldset>
      </form>
    </template>
    <p v-else-if="game.status === -1">等待开局；报名、退出、开始或取消请返回大厅操作。</p>
    <p v-else-if="game.status === 2">对局已取消。</p>
    <p v-else-if="game.status === 1">对局已结束，可查看详情。</p>
    <p v-else>本次读取缺少当前题目，请刷新确认。</p>
    <p class="hint">轮次提示仅用于交互，最终权限和判题由服务器验证。</p>
  </section>
</template>
