<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { useAutoRefresh } from '../../app/useAutoRefresh'
import { usePagedResource } from '../../shared/data/usePagedResource'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import UserName from '../../shared/ui/UserName.vue'
import { shortIntroduction } from './leaderboardPresentation'
const services = useServices()
const list = usePagedResource(services.people.leaders)
onMounted(list.load)
useAutoRefresh(list.refresh)
watch(services.userChanges, () => {
  void list.load()
})
</script>

<template>
  <section class="leaderboard-page" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">排行榜</h1>
    <button
      v-if="list.error.value"
      type="button"
      class="button"
      :disabled="list.loading.value"
      @click="list.load"
    >
      重试加载
    </button>
    <div class="leaderboard-results">
      <DataTable
        caption="排行榜"
        :loading="list.loading.value"
        :error="list.error.value"
        :empty="!list.result.value?.items.length"
      >
        <template #head
          ><tr>
            <th scope="col">排名</th>
            <th scope="col">用户</th>
            <th scope="col">简介</th>
            <th scope="col" class="numeric">参赛次数</th>
            <th scope="col" class="numeric">Rating</th>
          </tr></template
        >
        <tr
          v-for="user in list.result.value?.items"
          :key="user.id"
          :class="{ 'is-self': user.id === services.client.session.value?.user?.id }"
        >
          <td>
            <span class="rank-marker" :class="user.rank <= 3 ? `rank-${user.rank}` : undefined">{{
              user.rank
            }}</span>
          </td>
          <td>
            <RouterLink :to="`/user/${user.id}/`"
              ><UserName :name="user.username" :rating="user.rating"
            /></RouterLink>
          </td>
          <td>{{ shortIntroduction(user.introduction) }}</td>
          <td class="participation-count numeric">{{ user.participation_count }}</td>
          <td class="rating-value numeric">{{ user.rating ?? '记录缺失' }}</td>
        </tr>
      </DataTable>
      <PaginationBar
        v-if="list.result.value"
        :pagination="list.result.value.pagination"
        label="排行榜分页"
        @page="list.goToPage"
      />
    </div>
  </section>
</template>

<style scoped>
.leaderboard-page,
.leaderboard-results {
  min-width: 0;
}
.leaderboard-results :deep(table) {
  background: var(--ui-surface);
}
.leaderboard-results :deep(th),
.leaderboard-results :deep(td) {
  border: 1px solid var(--ui-line);
  text-align: center;
  vertical-align: middle;
}
.leaderboard-results :deep(th) {
  background: var(--ui-surface-muted);
}
.leaderboard-results :deep(tbody tr) {
  height: 3.5rem;
}
.leaderboard-results :deep(td:nth-child(2)) {
  min-width: 11rem;
  overflow-wrap: anywhere;
}
.leaderboard-results :deep(td:nth-child(3)) {
  min-width: 14rem;
  max-width: 24rem;
  overflow-wrap: anywhere;
}
.rank-marker {
  display: inline-grid;
  place-items: center;
  min-width: 2.25rem;
  min-height: 2.25rem;
  border: 1px solid transparent;
  border-radius: var(--ui-radius-sm);
  font-variant-numeric: tabular-nums;
}
.rank-1 {
  color: #715000;
  background: #fff5db;
  border-color: #b18b38;
}
.rank-2 {
  color: #455468;
  background: #edf1f5;
  border-color: #8a98aa;
}
.rank-3 {
  color: #794623;
  background: #fbefe6;
  border-color: #b58763;
}
.is-self {
  background: var(--ui-primary-soft);
}
.numeric {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
</style>
