<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useServices } from '../../app/services'
import { usePagedResource } from '../../shared/data/usePagedResource'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import UserLink from '../../shared/ui/UserLink.vue'
const services = useServices()
const list = usePagedResource(services.people.leaders)
onMounted(list.load)
watch(services.userChanges, () => {
  void list.load()
})
</script>

<template>
  <section class="workspace" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">排行榜</h1>
    <p class="hint">
      显示未封禁用户中的前 100 名，按 Rating 降序，同分按用户 ID 升序；不重算历史评分。
    </p>
    <NoticeBanner :message="list.error.value" />
    <button v-if="list.error.value" type="button" class="button" @click="list.load">
      重试加载
    </button>
    <DataTable
      caption="排行榜"
      :loading="list.loading.value"
      :empty="!list.result.value?.items.length"
    >
      <template #head
        ><tr>
          <th scope="col">排名</th>
          <th scope="col">用户</th>
          <th scope="col">简介</th>
          <th scope="col">Rating</th>
        </tr></template
      >
      <tr v-for="user in list.result.value?.items" :key="user.id">
        <td>{{ user.rank }}</td>
        <td>
          <UserLink :id="user.id" :name="user.username" :rating="user.rating" />
          #{{ user.id }}
        </td>
        <td class="multiline">{{ user.introduction || '—' }}</td>
        <td>{{ user.rating ?? '记录缺失' }}</td>
      </tr>
    </DataTable>
    <PaginationBar
      v-if="list.result.value"
      :pagination="list.result.value.pagination"
      label="排行榜分页"
      @page="list.goToPage"
    />
  </section>
</template>
