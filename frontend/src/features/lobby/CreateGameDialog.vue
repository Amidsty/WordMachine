<script setup lang="ts">
import { onMounted, ref, shallowRef } from 'vue'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import { newGameRequestId } from '../../shared/api/gameCommand'
import { usePagedResource } from '../../shared/data/usePagedResource'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import type { DictionarySummary } from '../dictionaries/service'
const emit = defineEmits<{ close: []; saved: [id: number] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const selected = shallowRef<DictionarySummary | null>(null)
const dictionaries = usePagedResource(services.dictionaries.list)
const task = useFormTask()
const rated = ref(true)
let command: Readonly<{ dictId: number; rated: boolean; requestId: string }> | null = null
onMounted(dictionaries.load)
function select(dictionary: DictionarySummary) {
  selected.value = dictionary
  if (dictionary.ownerid !== null || !dictionary.can_create_rated) rated.value = false
}
async function submit() {
  if (!selected.value || !actorId) {
    task.error.value = '请先选择一个词典。'
    return
  }
  if (rated.value && (selected.value.ownerid !== null || !selected.value.can_create_rated)) {
    task.error.value = 'Rated 仅限系统词典，且你的当前 Rating 必须在区间内。'
    return
  }
  const id = selected.value.id
  if (command?.dictId !== id || command.rated !== rated.value)
    command = Object.freeze({ dictId: id, rated: rated.value, requestId: newGameRequestId() })
  const intent = command
  await task.run(async (signal) => {
    const result = await services.lobby.create(id, actorId, intent.requestId, signal, intent.rated)
    if (!signal.aborted) emit('saved', result.game_id)
  })
}
</script>

<template>
  <ModalDialog title="创建新对局" :busy="task.pending.value" @close="emit('close')">
    <NoticeBanner :message="task.error.value" />
    <fieldset :disabled="task.pending.value">
      <legend class="sr-only">选择词典并创建对局</legend>
      <form class="toolbar" @submit.prevent="dictionaries.search">
        <label for="game-dict-search">按词典名称搜索</label>
        <input
          id="game-dict-search"
          v-model="dictionaries.query.value"
          type="search"
          maxlength="100"
        />
        <button type="submit" class="button">搜索词典</button>
      </form>
      <button
        v-if="dictionaries.error.value"
        type="button"
        class="button"
        @click="dictionaries.load"
      >
        重试词典加载
      </button>
      <DataTable
        caption="可选词典"
        :loading="dictionaries.loading.value"
        :error="dictionaries.error.value"
        :empty="!dictionaries.result.value?.items.length"
      >
        <template #head
          ><tr>
            <th scope="col">选择词典</th>
            <th scope="col">单词数</th>
          </tr></template
        >
        <tr v-for="dictionary in dictionaries.result.value?.items" :key="dictionary.id">
          <td>
            <label class="checkbox-label">
              <input
                type="radio"
                name="game-dictionary"
                :checked="selected?.id === dictionary.id"
                :disabled="dictionary.word_count === 0"
                @change="select(dictionary)"
              />
              {{ dictionary.dictname ?? '（名称缺失）' }} #{{ dictionary.id }} · Perf
              {{ dictionary.multiplier ? `×${dictionary.multiplier}` : '倍率未记录' }}
              ·
              {{
                dictionary.ownerid === null
                  ? `系统词典 · Rated [${dictionary.rated_min}, ${dictionary.rated_max}]`
                  : '个人词典 · 仅 Unrated'
              }}
            </label>
          </td>
          <td>{{ dictionary.word_count }}{{ dictionary.word_count === 0 ? '（空词典）' : '' }}</td>
        </tr>
      </DataTable>
      <PaginationBar
        v-if="dictionaries.result.value"
        :pagination="dictionaries.result.value.pagination"
        :busy="task.pending.value || dictionaries.loading.value"
        label="可选词典分页"
        @page="dictionaries.goToPage"
      />
      <section class="creation-selection" aria-label="已选词典">
        <p>
          当前选择：{{
            selected
              ? `${selected.dictname ?? '名称缺失'} #${selected.id} · Perf ×${selected.multiplier ?? '未记录'}`
              : '尚未选择'
          }}
        </p>
        <p v-if="selected" class="hint">
          难度 D：{{ selected.difficulty ?? '未记录' }} ·
          {{
            selected.ownerid === null
              ? `系统词典 · Rated [${selected.rated_min}, ${selected.rated_max}]`
              : '个人词典 · 仅 Unrated'
          }}
        </p>
        <p class="hint">
          选择独立于当前搜索和分页；D/M 以创建成功后服务端冻结值为准。Rated
          准入区间不冻结，后续报名和开局仍检查最新条件。
        </p>
      </section>
      <form @submit.prevent="submit">
        <label for="game-rated">比赛模式</label>
        <select id="game-rated" v-model="rated">
          <option
            :value="true"
            :disabled="!selected?.can_create_rated || selected.ownerid !== null"
          >
            Rated（更新 Rating）
          </option>
          <option :value="false">Unrated（不更新 Rating）</option>
        </select>
        <p class="hint">
          Rated 仅限系统词典；所有参赛者须符合闭区间。报名和开局时会用最新
          Rating、最新区间重新检查，管理员没有豁免。
        </p>
        <p>创建后不能更改模式。Unrated 保存作答和 Perf，但不更新 Rating。</p>
        <p v-if="task.error.value" class="hint">
          超时不代表创建失败。重试相同词典和模式保留原请求；更换词典或模式会创建新意图，请先核对上次结果，避免另建比赛。
        </p>
        <div class="actions">
          <button type="button" class="button" @click="emit('close')">返回</button>
          <SubmitButton :pending="task.pending.value">创建对局</SubmitButton>
        </div>
      </form>
    </fieldset>
  </ModalDialog>
</template>

<style scoped>
.creation-selection {
  padding: 1rem;
  margin-block: 1rem;
  background: var(--ui-primary-soft);
  border-left: 3px solid var(--ui-primary);
  overflow-wrap: anywhere;
}
.creation-selection p {
  margin-block: 0.4rem;
}
:deep(.checkbox-label) {
  min-width: 12rem;
  align-items: flex-start;
}
</style>
