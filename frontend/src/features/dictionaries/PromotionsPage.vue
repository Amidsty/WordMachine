<script setup lang="ts">
import { nextTick, onMounted, ref, shallowRef, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { useAutoRefresh } from '../../app/useAutoRefresh'
import { usePagedResource } from '../../shared/data/usePagedResource'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import PromotionDialog from './PromotionDialog.vue'
import PromotionStatus from './PromotionStatus.vue'
import type { Promotion } from './promotions'
const services = useServices()
const rows = usePagedResource(services.promotions.list)
const selected = shallowRef<Promotion | null>(null)
const listHeading = ref<HTMLHeadingElement>()
onMounted(rows.load)
useAutoRefresh(rows.refresh, () => selected.value === null)
watch(
  () =>
    JSON.stringify([
      services.client.session.value?.user?.id,
      services.client.session.value?.user?.admin_level,
      services.client.session.value?.csrf_token,
    ]),
  () => {
    selected.value = null
    void rows.load()
  },
)
async function close() {
  selected.value = null
  void rows.load()
  // Reloading removes the original row button. Do not steal an intentional new focus.
  await nextTick()
  if (
    listHeading.value?.isConnected &&
    document.visibilityState === 'visible' &&
    document.activeElement === document.body
  )
    listHeading.value.focus()
}
</script>
<template>
  <section class="promotions-page" aria-labelledby="promotion-title">
    <h2 id="promotion-title" ref="listHeading" tabindex="-1">系统词典申请</h2>
    <p>
      在个人词典详情中提交申请。本人可查看自己的记录；Lv.4+ 可查看全部申请并审核。拒绝后可重新申请。
    </p>
    <p class="hint promotion-visibility">
      当前可见范围：{{
        (services.client.session.value?.user?.admin_level ?? 0) >= 4
          ? '全部申请（Lv.4+）'
          : '本人提交的申请'
      }}。申请与审核原因仅在获准访问的申请记录中展示，不是词典公开介绍。
    </p>
    <form class="toolbar" @submit.prevent="rows.search">
      <label for="promotion-search">搜索词典</label
      ><input id="promotion-search" v-model="rows.query.value" maxlength="100" />
      <button type="submit" class="button">搜索申请</button>
      <button
        v-if="rows.error.value"
        type="button"
        class="button"
        :disabled="rows.loading.value"
        @click="rows.load"
      >
        重试读取申请
      </button>
    </form>
    <div class="promotion-records">
      <DataTable
        caption="系统词典申请记录"
        :loading="rows.loading.value"
        :error="rows.error.value"
        :empty="!rows.result.value?.items.length"
      >
        <template #head
          ><tr>
            <th scope="col">词典 / 申请人</th>
            <th scope="col">申请原因</th>
            <th scope="col">状态</th>
            <th scope="col">审核记录</th>
            <th scope="col">操作</th>
          </tr></template
        >
        <tr v-for="row in rows.result.value?.items" :key="row.request_id">
          <td class="promotion-dictionary">
            <RouterLink :to="`/admin/dicts/${row.dict_id}/`"
              ><bdi>{{ row.dictname ?? `词典 #${row.dict_id}` }}</bdi></RouterLink
            >
            <small>词典 #{{ row.dict_id }} · 申请人 #{{ row.applicant_id }}</small>
          </td>
          <td class="multiline">{{ row.reason }}</td>
          <td><PromotionStatus :state="row.state" /></td>
          <td class="multiline">
            {{ row.review_reason ?? '—'
            }}<template v-if="row.state === 1"
              ><br />批准区间：[{{ row.rated_min ?? '未记录' }},
              {{ row.rated_max ?? '未记录' }}]</template
            ><template v-if="row.reviewer_id"
              ><br />审核人 #{{ row.reviewer_id }}（当时 Lv.{{
                row.reviewer_level ?? '未记录'
              }}）</template
            >
          </td>
          <td>
            <button
              v-if="row.state === 0 && (services.client.session.value?.user?.admin_level ?? 0) >= 4"
              type="button"
              class="button"
              @click="selected = row"
            >
              审核申请</button
            ><span v-else>—</span>
          </td>
        </tr>
      </DataTable>
      <PaginationBar
        v-if="rows.result.value"
        :pagination="rows.result.value.pagination"
        label="申请分页"
        @page="rows.goToPage"
      />
    </div>
    <PromotionDialog v-if="selected" :application="selected" @close="close" @saved="close" />
  </section>
</template>

<style scoped>
.promotions-page,
.promotion-records {
  min-width: 0;
}
.toolbar input {
  flex: 1 1 12rem;
  width: auto;
  min-width: 0;
}
.promotion-visibility {
  border-inline-start: 3px solid var(--ui-line);
  padding-inline-start: 1rem;
}
.promotion-records {
  background: var(--ui-surface);
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-md);
  padding: 1rem;
}
.promotion-dictionary {
  min-width: 12rem;
  max-width: 22rem;
}
.promotion-dictionary a {
  font-weight: 600;
}
.promotion-dictionary small {
  display: block;
  color: var(--ui-text-muted);
  margin-top: 0.5rem;
}
.promotion-records :deep(td.multiline) {
  min-width: 12rem;
  max-width: 26rem;
}
.promotion-records :deep(td:last-child) {
  min-width: 7rem;
}
</style>
