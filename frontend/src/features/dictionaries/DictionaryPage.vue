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
import SkeletonBlock from '../../shared/ui/SkeletonBlock.vue'
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
  <section class="dictionary-page" aria-labelledby="dictionary-title">
    <RouterLink to="/admin/">返回词典列表</RouterLink>
    <div class="dictionary-heading">
      <div>
        <h2 id="dictionary-title">
          <bdi>{{ dictionary?.dictname ?? '词典详情' }}</bdi>
        </h2>
        <p v-if="dictionary" class="hint">
          词典 #{{ dictionary.id }} ·
          {{ dictionary.ownerid === null ? '系统词典' : `个人词典 · 用户 #${dictionary.ownerid}` }}
        </p>
      </div>
      <button
        v-if="dictionary?.can_manage"
        type="button"
        class="button button-primary"
        @click="dialog = { mode: 'create' }"
      >
        新增单词
      </button>
    </div>
    <NoticeBanner :message="error" />
    <NoticeBanner :message="notice" kind="success" />
    <button v-if="error" type="button" class="button" @click="load">重试加载</button>
    <p v-if="loading" role="status">正在加载词典…</p>
    <SkeletonBlock v-if="loading && !dictionary && !error" />
    <template v-if="dictionary">
      <p v-if="error" class="hint">
        本次词典信息未刷新，以下仍为上次读取的内容；操作权限仍由服务端复核。
      </p>
      <section class="dictionary-facts" aria-label="词典信息">
        <dl>
          <div>
            <dt>词典难度 D：</dt>
            <dd>{{ dictionary.difficulty ?? '未记录' }}</dd>
          </div>
          <div>
            <dt>Perf 倍率：</dt>
            <dd>{{ dictionary.multiplier ? `×${dictionary.multiplier}` : '未记录' }}</dd>
          </div>
          <div>
            <dt>Rated 区间：</dt>
            <dd>
              {{
                dictionary.ownerid === null
                  ? `[${dictionary.rated_min}, ${dictionary.rated_max}]（含端点）`
                  : '仅 Unrated'
              }}
            </dd>
          </div>
        </dl>
        <p class="hint">
          D/M 在新局创建时冻结；修改不覆盖已建局保存的难度与倍率。Rated
          准入区间与它们独立，不是创建快照。
        </p>
        <p v-if="dictionary.ownerid === null" class="hint">
          系统词典需 Lv.3 起维护。创建、报名、开局均按最新区间检查全体成员当前
          Rating；管理员无准入豁免。范围变更可能阻止等待局后续报名或开局，不追溯运行局，也不自动转为
          Unrated。
        </p>
        <p v-else class="hint">个人词典仅可创建 Unrated 比赛。</p>
      </section>
      <div class="dictionary-workbench">
        <section class="dictionary-words" aria-labelledby="dictionary-words-title">
          <h3 id="dictionary-words-title">单词列表</h3>
          <form class="toolbar" @submit.prevent="words.search">
            <label for="word-search">搜索英文或中文</label>
            <input id="word-search" v-model="words.query.value" type="search" maxlength="100" />
            <button type="submit" class="button">搜索单词</button>
          </form>
          <p class="hint">
            区间使用全词典有效单词按 ID 升序的序号，从 1 开始，两端包含；不是数据库 ID
            或当前页序号。搜索结果不显示全词典序号，清空搜索并查询后可核对。
          </p>
          <button v-if="words.error.value" type="button" class="button" @click="words.load">
            重试单词加载
          </button>
          <DataTable
            caption="单词列表"
            :loading="words.loading.value"
            :error="words.error.value"
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
        </section>
        <aside class="dictionary-maintenance" aria-labelledby="dictionary-maintenance-title">
          <h3 id="dictionary-maintenance-title">比赛配置与维护</h3>
          <p v-if="!dictionary.can_manage" class="hint">只读词典：可查看、搜索和导出，不可修改。</p>
          <div v-else class="actions config-actions">
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
          </div>
          <section class="dictionary-promotion" aria-labelledby="dictionary-promotion-title">
            <h3 id="dictionary-promotion-title">系统词典申请</h3>
            <button
              v-if="dictionary.ownerid === services.client.session.value?.user?.id"
              type="button"
              class="button"
              @click="applying = true"
            >
              申请转为系统词典
            </button>
            <RouterLink to="/admin/dictionary-promotions/">查看系统词典申请记录</RouterLink>
          </section>
          <section
            v-if="dictionary.can_manage"
            class="dictionary-danger"
            aria-labelledby="dictionary-danger-title"
          >
            <h3 id="dictionary-danger-title">危险操作</h3>
            <p class="hint">
              按区间删除针对全词典有效词表的序号，不是当前页或搜索结果。请在原确认流程中核对范围。
            </p>
            <button type="button" class="button button-danger" @click="openRange">
              按区间批量删除
            </button>
            <p class="hint">
              整词典删除入口保留在词典列表中。删除系统词典可能影响等待 Rated 局后续报名与开局。
            </p>
          </section>
          <p class="hint">
            词条改删不重写已有题目快照；legacy_live
            旧局仍可能读取当前词条，不能视为所有旧局都不受影响。
          </p>
        </aside>
      </div>
      <div class="dictionary-transfer">
        <CsvPanel
          v-if="csvLimits"
          :dict-id="dictId"
          :can-manage="dictionary.can_manage"
          :limits="csvLimits"
          @changed="words.load"
        />
      </div>
      <PromotionDialog
        v-if="applying"
        :dictionary="dictionary"
        @close="closeApplication"
        @saved="applicationSaved"
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

<style scoped>
.dictionary-page,
.dictionary-heading > div,
.dictionary-words,
.dictionary-maintenance {
  min-width: 0;
}
.dictionary-heading {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
  justify-content: space-between;
  margin-block: 1rem;
}
.dictionary-heading h2,
.dictionary-heading p {
  margin: 0;
  overflow-wrap: anywhere;
}
.dictionary-facts {
  padding-block: 0.5rem 1rem;
  border-block: 1px solid var(--ui-line);
  margin-bottom: 1.5rem;
}
.dictionary-facts dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
}
.dictionary-facts dt {
  color: var(--ui-text-muted);
}
.dictionary-facts dd {
  margin: 0.25rem 0 0;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
.dictionary-workbench {
  display: grid;
  gap: 1.5rem;
  align-items: start;
}
.dictionary-words,
.dictionary-maintenance,
.dictionary-transfer {
  padding: 1rem;
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-md);
  background: var(--ui-surface);
}
.dictionary-words h3,
.dictionary-maintenance > h3 {
  margin-top: 0;
}
.dictionary-words :deep(td:nth-child(2)),
.dictionary-words :deep(td:nth-child(3)) {
  min-width: 10rem;
  max-width: 25rem;
  overflow-wrap: anywhere;
}
.dictionary-promotion,
.dictionary-danger {
  margin-top: 1.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--ui-line);
}
.dictionary-promotion a {
  display: block;
  margin-top: 0.75rem;
}
.dictionary-danger h3 {
  color: var(--ui-negative);
}
.dictionary-transfer {
  margin-top: 1.5rem;
}
.dictionary-transfer :deep(.csv-panel) {
  margin-top: 0;
}
@media (max-width: 600px) {
  .dictionary-facts dl {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (min-width: 1200px) {
  .dictionary-workbench {
    grid-template-columns: minmax(0, 1fr) 20rem;
  }
}
</style>
