<script setup lang="ts">
import { onMounted, shallowRef, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { usePagedResource } from '../../shared/data/usePagedResource'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import PromotionDialog from './PromotionDialog.vue'
import type { Promotion } from './promotions'
const services = useServices()
const rows = usePagedResource(services.promotions.list)
const selected = shallowRef<Promotion | null>(null)
const labels = ['待审核', '已通过', '已拒绝']
onMounted(rows.load)
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
function close() {
  selected.value = null
  void rows.load()
}
</script>
<template>
  <section aria-labelledby="promotion-title">
    <h2 id="promotion-title">系统词典申请</h2>
    <p>
      在个人词典详情中提交申请。本人可查看自己的记录；Lv.4+ 可查看全部申请并审核。拒绝后可重新申请。
    </p>
    <form class="toolbar" @submit.prevent="rows.search">
      <label for="promotion-search">搜索词典</label
      ><input id="promotion-search" v-model="rows.query.value" maxlength="100" />
      <button type="submit" class="button">搜索申请</button>
      <button type="button" class="button" @click="rows.load">刷新申请</button>
    </form>
    <NoticeBanner :message="rows.error.value" />
    <DataTable
      caption="系统词典申请记录"
      :loading="rows.loading.value"
      :empty="!rows.result.value?.items.length"
    >
      <template #head
        ><tr>
          <th>词典 / 申请人</th>
          <th>申请原因</th>
          <th>状态</th>
          <th>审核记录</th>
          <th>操作</th>
        </tr></template
      >
      <tr v-for="row in rows.result.value?.items" :key="row.request_id">
        <td>
          <RouterLink :to="`/admin/dicts/${row.dict_id}/`">{{
            row.dictname ?? `词典 #${row.dict_id}`
          }}</RouterLink
          ><br />申请人 #{{ row.applicant_id }}
        </td>
        <td class="multiline">{{ row.reason }}</td>
        <td>{{ labels[row.state] }}</td>
        <td class="multiline">
          {{ row.review_reason ?? '—'
          }}<template v-if="row.state === 1"
            ><br />批准区间：[{{ row.rated_min }}, {{ row.rated_max }}]</template
          ><template v-if="row.reviewer_id"
            ><br />审核人 #{{ row.reviewer_id }}（当时 Lv.{{ row.reviewer_level }}）</template
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
    <PromotionDialog v-if="selected" :application="selected" @close="close" @saved="close" />
  </section>
</template>
