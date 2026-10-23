<script setup lang="ts">
import { onMounted, ref, shallowRef } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useServices } from '../../app/services'
import { usePagedResource } from '../../shared/data/usePagedResource'
import { usePolling } from '../../shared/data/usePolling'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import GameCard from './GameCard.vue'
import GameActionDialog from './GameActionDialog.vue'
import CreateGameDialog from './CreateGameDialog.vue'
import {
  actionLabels,
  statusLabels,
  type LobbyAction,
  type LobbyGame,
  type LobbyStatus,
} from './service'

const services = useServices()
const router = useRouter()
const actorId = services.client.session.value?.user?.id
const status = ref<LobbyStatus>('waiting')
const statuses: LobbyStatus[] = ['waiting', 'running', 'finished', 'cancelled']
const notice = ref('')
const activeGameId = ref<number | null>(null)
const autoRefresh = ref(true)
const navigating = ref(false)
const dialog = shallowRef<
  { kind: 'create' } | { kind: 'action'; game: LobbyGame; action: LobbyAction } | null
>(null)
const list = usePagedResource(async (query, signal) => {
  try {
    const data = await services.lobby.list(query, status.value, signal)
    if (!signal.aborted) {
      activeGameId.value = data.activeGameId
      enterActiveGame(data.activeGameId)
    }
    return data
  } catch (error) {
    if (!signal.aborted) activeGameId.value = null
    throw error
  }
})
const polling = usePolling(
  list.refresh,
  () =>
    autoRefresh.value &&
    !dialog.value &&
    services.userMenuTarget.value === null &&
    !navigating.value,
)
// Only a newly accepted read can initiate navigation; resuming must not use cached membership.
function enterActiveGame(id: number | null) {
  if (
    id &&
    !polling.paused.value &&
    !navigating.value &&
    services.client.session.value?.user?.id === actorId
  ) {
    navigating.value = true
    void router.push(`/game/${id}/`)
  }
}
onMounted(list.load)
function selectStatus(value: LobbyStatus) {
  status.value = value
  void list.search()
}
function saved() {
  const current = dialog.value
  dialog.value = null
  if (current?.kind !== 'action') return
  notice.value = `${actionLabels[current.action]}已完成。`
  if (current.action === 'start') {
    navigating.value = true
    void router.push(`/game/${current.game.id}/`)
  } else void list.load()
}
function created(id: number) {
  dialog.value = null
  notice.value = `对局 #${id} 已创建，可在待开始列表查看；当前筛选可能隐藏它。`
  void list.load()
}
</script>

<template>
  <section class="workspace" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">对局大厅</h1>
    <p class="hint">词典由创建者或管理员维护。对局题目快照及历史数据迁移仍在重构中。</p>
    <div class="toolbar">
      <button type="button" class="button button-primary" @click="dialog = { kind: 'create' }">
        创建新对局
      </button>
      <button type="button" class="button" :disabled="list.loading.value" @click="list.load">
        刷新列表
      </button>
      <label class="checkbox-label"
        ><input v-model="autoRefresh" type="checkbox" />自动刷新并进入已开局对局（5 秒）</label
      >
    </div>
    <p class="hint" role="status">
      {{
        polling.paused.value
          ? '自动刷新已暂停（手动关闭、离线、后台或弹窗打开）。'
          : '自动刷新已开启。'
      }}
    </p>
    <NoticeBanner :message="notice" kind="success" />
    <NoticeBanner :message="list.error.value || polling.error.value" />
    <p v-if="activeGameId">
      你有正在进行的对局：<RouterLink :to="`/game/${activeGameId}/`"
        >进入对局 #{{ activeGameId }}</RouterLink
      >
    </p>
    <nav class="section-nav" aria-label="对局状态">
      <button
        v-for="value in statuses"
        :key="value"
        type="button"
        class="button"
        :aria-pressed="status === value"
        @click="selectStatus(value)"
      >
        {{ statusLabels[value] }}
      </button>
    </nav>
    <form class="toolbar" @submit.prevent="list.search">
      <label for="game-search">按比赛名称或词典名称搜索对局</label>
      <input id="game-search" v-model="list.query.value" type="search" maxlength="100" />
      <button type="submit" class="button">搜索对局</button>
    </form>
    <p v-if="list.loading.value && !list.result.value" role="status">正在加载对局…</p>
    <p v-else-if="list.result.value && !list.result.value.items.length">暂无符合条件的对局。</p>
    <div class="game-grid" :aria-busy="list.loading.value">
      <GameCard
        v-for="game in list.result.value?.items"
        :key="game.id"
        :game="game"
        @act="(game, action) => (dialog = { kind: 'action', game, action })"
      />
    </div>
    <PaginationBar
      v-if="list.result.value"
      :pagination="list.result.value.pagination"
      label="对局分页"
      :busy="list.loading.value"
      @page="list.goToPage"
    />
    <CreateGameDialog v-if="dialog?.kind === 'create'" @close="dialog = null" @saved="created" />
    <GameActionDialog
      v-if="dialog?.kind === 'action'"
      :game="dialog.game"
      :action="dialog.action"
      @close="dialog = null"
      @saved="saved"
    />
  </section>
</template>
