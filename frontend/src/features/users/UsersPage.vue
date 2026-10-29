<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useServices } from '../../app/services'
import { usePagedResource } from '../../shared/data/usePagedResource'
import DataTable from '../../shared/ui/DataTable.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import UserLink from '../../shared/ui/UserLink.vue'
import './managementUi.css'

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
  <section
    v-if="actor && (actor.admin_level ?? 0) > 0"
    class="users-page"
    aria-labelledby="user-list-title"
  >
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
    <button v-if="list.error.value" type="button" class="button" @click="list.load">
      重试加载
    </button>
    <div class="management-surface user-results">
      <p class="hint">列表显示本次查询到的账号，不代表在线人数；操作能力在打开用户小窗时读取。</p>
      <DataTable
        caption="用户列表"
        :loading="list.loading.value"
        :error="list.error.value"
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
          <td class="managed-user-name">
            <UserLink :id="user.id" :name="user.username" :rating="user.rating" />
            <small>#{{ user.id }} <span v-if="user.id === actor.id">· 当前账号</span></small>
          </td>
          <td class="multiline user-introduction">{{ user.introduction || '—' }}</td>
          <td class="user-rating">{{ user.rating ?? '未记录' }}</td>
          <td>
            <span>{{
              user.admin_level ? `管理员 Lv.${user.admin_level}` : '普通用户（0 级）'
            }}</span>
            <small class="user-status" :class="{ 'user-status--banned': user.deleted === true }">{{
              user.deleted === null ? '状态待审查' : user.deleted ? '已封禁' : '正常'
            }}</small>
          </td>
        </tr>
      </DataTable>
      <PaginationBar
        v-if="list.result.value"
        :pagination="list.result.value.pagination"
        label="用户分页"
        @page="list.goToPage"
      />
    </div>
  </section>
</template>

<style scoped>
.users-page,
.user-results {
  min-width: 0;
}
.managed-user-name {
  min-width: 10rem;
  max-width: 20rem;
}
.managed-user-name small,
.user-status {
  display: block;
  margin-top: 0.35rem;
  color: var(--ui-text-muted);
}
.user-introduction {
  min-width: 12rem;
  max-width: 30rem;
}
.user-rating {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.user-status--banned {
  color: var(--ui-negative);
}
.user-results :deep(th:nth-child(3)) {
  text-align: right;
}
</style>
