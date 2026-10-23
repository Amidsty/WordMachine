<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useServices } from '../../app/services'
import { usePagedResource } from '../../shared/data/usePagedResource'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import UserLink from '../../shared/ui/UserLink.vue'

const services = useServices()
const actor = services.client.session.value?.user
const includeDeleted = ref(false)
const list = usePagedResource((query, signal) =>
  services.users.list(query, includeDeleted.value, signal),
)
onMounted(() => {
  if ((actor?.admin_level ?? 0) > 0) void list.load()
})
watch(services.userChanges, () => {
  void list.load()
})
</script>

<template>
  <section v-if="actor && (actor.admin_level ?? 0) > 0" aria-labelledby="user-list-title">
    <h2 id="user-list-title">用户管理 · Lv.{{ actor.admin_level }}</h2>
    <p class="hint">
      点击用户名打开操作小窗，统一选择资料、等级、密码、封禁/恢复及 Rating
      操作。仅显示你有权执行的按钮；修改等级仅限 Lv.4/5，仍须严格下级，不能修改自己等级。
    </p>
    <form class="toolbar" @submit.prevent="list.search">
      <label for="user-search">按用户名搜索</label>
      <input id="user-search" v-model="list.query.value" type="search" maxlength="100" />
      <button type="submit" class="button">搜索用户</button>
      <label class="checkbox-label"
        ><input
          v-model="includeDeleted"
          type="checkbox"
          @change="list.search"
        />包含已封禁用户</label
      >
    </form>
    <NoticeBanner :message="list.error.value" />
    <button v-if="list.error.value" type="button" class="button" @click="list.load">
      重试加载
    </button>
    <DataTable
      caption="用户列表"
      :loading="list.loading.value"
      :empty="!list.result.value?.items.length"
    >
      <template #head
        ><tr>
          <th scope="col">用户</th>
          <th scope="col">简介</th>
          <th scope="col">Rating</th>
          <th scope="col">角色 / 状态</th>
        </tr></template
      >
      <tr v-for="user in list.result.value?.items" :key="user.id" :data-user-id="user.id">
        <td>
          <UserLink :id="user.id" :name="user.username" :rating="user.rating" /> #{{ user.id }}
          <span v-if="user.id === actor.id">（当前账号）</span>
        </td>
        <td class="multiline">{{ user.introduction || '—' }}</td>
        <td>{{ user.rating ?? '—' }}</td>
        <td>
          {{ user.admin_level ? `管理员 Lv.${user.admin_level}` : '普通用户（0 级）' }} /
          {{ user.deleted === null ? '待审查' : user.deleted ? '已封禁' : '正常' }}
        </td>
      </tr>
    </DataTable>
    <PaginationBar
      v-if="list.result.value"
      :pagination="list.result.value.pagination"
      label="用户分页"
      @page="list.goToPage"
    />
  </section>
</template>
