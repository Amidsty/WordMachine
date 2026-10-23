<script setup lang="ts">
import { onMounted, onScopeDispose, ref, shallowRef } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useServices } from '../../app/services'
import { errorMessage } from '../../shared/forms/useFormTask'
import { ApiError } from '../../shared/api/client'
import { usePagedResource } from '../../shared/data/usePagedResource'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import WordDialog from './WordDialog.vue'
import WordRangeDialog from './WordRangeDialog.vue'
import DictionaryDialog from './DictionaryDialog.vue'
import CsvPanel from './CsvPanel.vue'
import PromotionDialog from './PromotionDialog.vue'
import type { CsvLimits, Dictionary, Word } from './service'

const services = useServices()
const route = useRoute()
const dictId = Number(route.params.id)
const dictionary = shallowRef<Dictionary | null>(null)
const csvLimits = shallowRef<CsvLimits | null>(null)
const error = ref('')
const loading = ref(false)
const notice = ref('')
const renaming = ref(false)
const multiplierEditing = ref(false)
const boundsEditing = ref(false)
const difficultyEditing = ref(false)
const applying = ref(false)
const rangeDeleting = ref(false)
const dialog = shallowRef<{ mode: 'create' | 'edit' | 'delete'; word?: Word } | null>(null)
const words = usePagedResource(async (query, signal) => {
  const data = await services.dictionaries.words(dictId, query, signal)
  return {
    ...data,
    items: data.items.map((word, index) => ({
      ...word,
      ordinal: query.query
        ? null
        : (data.pagination.page - 1) * data.pagination.per_page + index + 1,
    })),
  }
})
let controller: AbortController | undefined
let revision = 0
onScopeDispose(() => {
  revision++
  controller?.abort()
})

async function load() {
  const current = ++revision
  controller?.abort()
  controller = new AbortController()
  error.value = ''
  loading.value = true
  try {
    if (!Number.isSafeInteger(dictId) || dictId < 1 || dictId > 2147483647) {
      error.value = '无效的词典编号。'
      return
    }
    const result = await services.dictionaries.get(dictId, controller.signal)
    if (current !== revision) return
    dictionary.value = result.dict
    csvLimits.value = result.csv_limits
    await words.load()
  } catch (cause) {
    if (current === revision) {
      error.value = errorMessage(cause)
      if (cause instanceof ApiError && [401, 403, 404].includes(cause.status))
        dictionary.value = null
    }
  } finally {
    if (current === revision) loading.value = false
  }
}
onMounted(load)
function wordSaved() {
  dialog.value = null
  notice.value = '单词操作已保存。'
  void words.load()
}
function openRange() {
  notice.value = ''
  rangeDeleting.value = true
}
function closeRange() {
  rangeDeleting.value = false
  // A lost write reply may still mean success. Refresh reads only, never resubmit.
  void words.load()
}
function rangeDeleted(count: number) {
  rangeDeleting.value = false
  notice.value = `已删除确认区间内的 ${count} 个单词，已有题目快照不变。`
  void words.load()
}
function closeApplication() {
  applying.value = false
  void load()
}
function applicationSaved() {
  notice.value = '申请已提交，可在系统词典申请记录中核对。'
  closeApplication()
}
function closeDifficulty() {
  difficultyEditing.value = false
  void load()
}
function renamed() {
  renaming.value = false
  multiplierEditing.value = false
  boundsEditing.value = false
  difficultyEditing.value = false
  notice.value = '词典配置已保存。'
  void load()
}
</script>

<template>
  <section aria-labelledby="dictionary-title">
    <RouterLink to="/admin/">返回词典列表</RouterLink>
    <h2 id="dictionary-title">{{ dictionary?.dictname ?? '词典详情' }}</h2>
    <NoticeBanner :message="error" />
    <NoticeBanner :message="notice" kind="success" />
    <button v-if="error" type="button" class="button" @click="load">重试加载</button>
    <p v-if="loading" role="status">正在加载词典…</p>
    <template v-if="dictionary">
      <p>
        Perf 倍率：{{
          dictionary.multiplier ? `×${dictionary.multiplier}` : '未记录'
        }}（仅影响之后创建的新局）
      </p>
      <p>词典难度 D：{{ dictionary.difficulty ?? '未记录' }}（与倍率、Rated 区间独立）</p>
      <p v-if="dictionary.ownerid === null" class="hint">
        系统词典需 Lv.3 起维护。Rated 区间：[{{ dictionary.rated_min }},
        {{ dictionary.rated_max }}]（含端点）。
      </p>
      <p v-else class="hint">个人词典仅可创建 Unrated 比赛。</p>
      <button
        v-if="dictionary.ownerid === services.client.session.value?.user?.id"
        type="button"
        class="button"
        @click="applying = true"
      >
        申请转为系统词典
      </button>
      <RouterLink to="/admin/dictionary-promotions/">查看系统词典申请记录</RouterLink>
      <PromotionDialog
        v-if="applying"
        :dictionary="dictionary"
        @close="closeApplication"
        @saved="applicationSaved"
      />
      <p v-if="!dictionary.can_manage" class="hint">只读词典：可查看、搜索和导出，不可修改。</p>
      <div v-else class="actions">
        <button
          v-if="dictionary.difficulty !== undefined"
          type="button"
          class="button"
          @click="difficultyEditing = true"
        >
          修改词典难度
        </button>
        <button
          v-if="dictionary.ownerid === null"
          type="button"
          class="button"
          @click="boundsEditing = true"
        >
          设置 Rated 区间
        </button>
        <button
          v-if="dictionary.config_version !== undefined"
          type="button"
          class="button"
          @click="multiplierEditing = true"
        >
          修改倍率
        </button>
        <button type="button" class="button" @click="renaming = true">重命名词典</button>
        <button type="button" class="button button-primary" @click="dialog = { mode: 'create' }">
          新增单词
        </button>
        <button type="button" class="button button-danger" @click="openRange">
          按区间批量删除
        </button>
      </div>
      <form class="toolbar" @submit.prevent="words.search">
        <label for="word-search">搜索英文或中文</label>
        <input id="word-search" v-model="words.query.value" type="search" maxlength="100" />
        <button type="submit" class="button">搜索单词</button>
      </form>
      <p class="hint">
        区间使用全词典有效单词按 ID 升序的序号，从 1 开始，两端包含；不是数据库 ID
        或当前页序号。搜索结果不显示全词典序号，清空搜索并查询后可核对。
      </p>
      <NoticeBanner :message="words.error.value" />
      <button v-if="words.error.value" type="button" class="button" @click="words.load">
        重试单词加载
      </button>
      <DataTable
        caption="单词列表"
        :loading="words.loading.value"
        :empty="!words.result.value?.items.length"
      >
        <template #head
          ><tr>
            <th scope="col">全词典序号</th>
            <th scope="col">英文</th>
            <th scope="col">中文</th>
            <th scope="col">操作</th>
          </tr></template
        >
        <tr v-for="word in words.result.value?.items" :key="word.id">
          <td>{{ word.ordinal ?? '—' }}</td>
          <td class="multiline">{{ word.english ?? '（缺失）' }}</td>
          <td class="multiline">{{ word.chinese ?? '（缺失）' }}</td>
          <td>
            <div v-if="dictionary.can_manage" class="actions">
              <button type="button" class="button" @click="dialog = { mode: 'edit', word }">
                编辑单词
              </button>
              <button
                type="button"
                class="button button-danger"
                @click="dialog = { mode: 'delete', word }"
              >
                删除单词
              </button>
            </div>
            <span v-else>只读</span>
          </td>
        </tr>
      </DataTable>
      <PaginationBar
        v-if="words.result.value"
        :pagination="words.result.value.pagination"
        label="单词分页"
        @page="words.goToPage"
      />
      <CsvPanel
        v-if="csvLimits"
        :dict-id="dictId"
        :can-manage="dictionary.can_manage"
        :limits="csvLimits"
        @changed="words.load"
      />
      <WordRangeDialog
        v-if="rangeDeleting && dictionary.can_manage"
        :dict-id="dictId"
        @close="closeRange"
        @saved="rangeDeleted"
      />
      <WordDialog
        v-if="dialog && dictionary.can_manage"
        :dict-id="dictId"
        :mode="dialog.mode"
        :word="dialog.word"
        @close="dialog = null"
        @saved="wordSaved"
      />
      <DictionaryDialog
        v-if="difficultyEditing && dictionary.can_manage"
        mode="difficulty"
        :dictionary="dictionary"
        @close="closeDifficulty"
        @saved="renamed"
      />
      <DictionaryDialog
        v-if="boundsEditing && dictionary.can_manage && dictionary.ownerid === null"
        mode="rated-bounds"
        :dictionary="dictionary"
        @close="boundsEditing = false"
        @saved="renamed"
      />
      <DictionaryDialog
        v-if="multiplierEditing && dictionary.can_manage"
        mode="multiplier"
        :dictionary="dictionary"
        @close="multiplierEditing = false"
        @saved="renamed"
      />
      <DictionaryDialog
        v-if="renaming && dictionary.can_manage"
        mode="rename"
        :dictionary="dictionary"
        @close="renaming = false"
        @saved="renamed"
      />
    </template>
  </section>
</template>
