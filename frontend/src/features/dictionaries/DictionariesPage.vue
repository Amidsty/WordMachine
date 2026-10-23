<script setup lang="ts">
import { onMounted, ref, shallowRef } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useServices } from '../../app/services'
import { usePagedResource } from '../../shared/data/usePagedResource'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import DictionaryDialog from './DictionaryDialog.vue'
import type { Dictionary } from './service'

const services = useServices()
const router = useRouter()
const list = usePagedResource(services.dictionaries.list)
const notice = ref('')
const dialog = shallowRef<{
  mode: 'create' | 'rename' | 'delete' | 'multiplier' | 'rated-bounds'
  dictionary?: Dictionary
} | null>(null)
onMounted(list.load)
function saved(id?: number) {
  const mode = dialog.value?.mode
  dialog.value = null
  notice.value = '词典操作已保存。'
  if (mode === 'create' && id) void router.push(`/admin/dicts/${id}/`)
  else void list.load()
}
</script>

<template>
  <section aria-labelledby="dict-list-title">
    <h2 id="dict-list-title">词典列表</h2>
    <p class="hint">登录用户可查看词典；个人词典由本人或 Lv.5 维护，系统词典需 Lv.3 起维护。</p>
    <form class="toolbar" @submit.prevent="list.search">
      <label for="dict-search">按词典名称搜索</label>
      <input id="dict-search" v-model="list.query.value" type="search" maxlength="100" />
      <button type="submit" class="button">搜索词典</button>
      <button type="button" class="button button-primary" @click="dialog = { mode: 'create' }">
        新建词典
      </button>
    </form>
    <NoticeBanner :message="notice" kind="success" />
    <NoticeBanner :message="list.error.value" />
    <button v-if="list.error.value" type="button" class="button" @click="list.load">
      重试加载
    </button>
    <DataTable
      caption="词典列表"
      :loading="list.loading.value"
      :empty="!list.result.value?.items.length"
    >
      <template #head
        ><tr>
          <th scope="col">名称</th>
          <th scope="col">归属</th>
          <th scope="col">单词数</th>
          <th scope="col">Perf 倍率</th>
          <th scope="col">Rated 区间</th>
          <th scope="col">操作</th>
        </tr></template
      >
      <tr v-for="dictionary in list.result.value?.items" :key="dictionary.id">
        <td>
          <RouterLink :to="`/admin/dicts/${dictionary.id}/`">{{
            dictionary.dictname ?? '（名称缺失）'
          }}</RouterLink>
        </td>
        <td>{{ dictionary.ownerid === null ? '系统词典' : `用户 #${dictionary.ownerid}` }}</td>
        <td>{{ dictionary.word_count }}</td>
        <td>{{ dictionary.multiplier ? `×${dictionary.multiplier}` : '未记录' }}</td>
        <td>
          {{
            dictionary.ownerid === null
              ? `[${dictionary.rated_min}, ${dictionary.rated_max}]`
              : '仅 Unrated'
          }}
        </td>
        <td>
          <div class="actions">
            <template v-if="dictionary.can_manage">
              <button
                v-if="dictionary.ownerid === null"
                type="button"
                class="button"
                @click="dialog = { mode: 'rated-bounds', dictionary }"
              >
                设置 Rated 区间
              </button>
              <button
                v-if="dictionary.config_version !== undefined"
                type="button"
                class="button"
                @click="dialog = { mode: 'multiplier', dictionary }"
              >
                修改倍率
              </button>
              <button type="button" class="button" @click="dialog = { mode: 'rename', dictionary }">
                重命名
              </button>
              <button
                type="button"
                class="button button-danger"
                @click="dialog = { mode: 'delete', dictionary }"
              >
                删除词典
              </button>
            </template>
            <span v-else>只读</span>
          </div>
        </td>
      </tr>
    </DataTable>
    <PaginationBar
      v-if="list.result.value"
      :pagination="list.result.value.pagination"
      label="词典分页"
      @page="list.goToPage"
    />
    <DictionaryDialog
      v-if="dialog"
      :mode="dialog.mode"
      :dictionary="dialog.dictionary"
      @close="dialog = null"
      @saved="saved"
    />
  </section>
</template>
