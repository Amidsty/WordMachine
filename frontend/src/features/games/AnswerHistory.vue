<script setup lang="ts">
import { computed, ref } from 'vue'
import type { GameState } from './contracts'
import {
  answerWord,
  personName,
  personRating,
  storedNumber,
  storedPerf,
  storedText,
} from './presentation'
import UserLink from '../../shared/ui/UserLink.vue'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
const props = defineProps<{ game: GameState; recentFirst?: boolean }>()
const page = ref(1)
const pagination = computed(() => {
  const total = props.game.result.length
  const pages = Math.max(1, Math.ceil(total / 20))
  return { page: Math.min(page.value, pages), per_page: 20, total, pages }
})
const rows = computed(() => {
  const start = (pagination.value.page - 1) * 20
  const total = props.game.result.length
  return Array.from({ length: Math.min(20, total - start) }, (_, offset) => {
    const index = props.recentFirst ? total - start - offset - 1 : start + offset
    const answer = props.game.result[index]!
    return { answer, index, word: answerWord(props.game, answer, index) }
  })
})
</script>

<template>
  <section aria-labelledby="game-answers-title">
    <h2 id="game-answers-title">答题记录{{ recentFirst ? '（最新在前）' : '' }}</h2>
    <p v-if="!game.result.length">暂无答题记录。</p>
    <DataTable v-else caption="已接受的答题记录" :loading="false" :empty="false">
      <template #head>
        <tr>
          <th scope="col">序号</th>
          <th scope="col">作答者</th>
          <th scope="col">中文题面</th>
          <th scope="col">提交答案</th>
          <th scope="col">对应英文</th>
          <th scope="col">已记录结果</th>
          <th scope="col">Perf / 增量</th>
          <th scope="col">个人 / 全局连击</th>
          <th scope="col">规则版本</th>
        </tr>
      </template>
      <tr v-for="{ answer, index, word } in rows" :key="index">
        <td>{{ index + 1 }}</td>
        <td class="multiline">
          <UserLink
            :id="answer.uid"
            :name="personName(game, answer.uid)"
            :rating="personRating(game, answer.uid)"
          />
        </td>
        <td class="multiline">{{ word ? storedText(word.chinese) : '题目引用缺失或不一致' }}</td>
        <td class="multiline">{{ storedText(answer.answer) }}</td>
        <td class="multiline">{{ word ? storedText(word.english) : '无法对应题目' }}</td>
        <td>{{ answer.result === true ? '正确' : answer.result === false ? '错误' : '未记录' }}</td>
        <td>{{ storedPerf(answer.perf) }} / {{ storedPerf(answer.perf_delta, true) }}</td>
        <td>{{ storedNumber(answer.usercombo) }} / {{ storedNumber(answer.globalcombo) }}</td>
        <td>{{ storedText(answer.rating_version) }}</td>
      </tr>
    </DataTable>
    <PaginationBar
      v-if="game.result.length"
      :pagination="pagination"
      label="答题记录分页"
      @page="page = $event"
    />
    <p class="hint">仅对本次已读取的答题记录分页显示；不重新判题，也不补齐历史缺失字段。</p>
  </section>
</template>
