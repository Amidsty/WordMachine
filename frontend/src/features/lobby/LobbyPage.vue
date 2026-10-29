<script setup lang="ts">
import { onMounted, ref, shallowRef, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useServices } from '../../app/services'
import { usePagedResource } from '../../shared/data/usePagedResource'
import { usePolling } from '../../shared/data/usePolling'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SkeletonBlock from '../../shared/ui/SkeletonBlock.vue'
import PaginationBar from '../../shared/ui/PaginationBar.vue'
import GameCard from './GameCard.vue'
import LobbyAccountCard from './LobbyAccountCard.vue'
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
let menuRevision = 0
let needsMenuRead = false
watch(
  services.navigationMenu,
  (next, previous) => {
    menuRevision++
    if (previous && !next) needsMenuRead = true
  },
  { flush: 'sync' },
)
const list = usePagedResource(async (query, signal) => {
  const revision = menuRevision
  if (!services.navigationMenu.value) needsMenuRead = false
  try {
    const data = await services.lobby.list(query, status.value, signal)
    if (!signal.aborted) {
      activeGameId.value = data.activeGameId
      if (revision === menuRevision) enterActiveGame(data.activeGameId)
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
    services.navigationMenu.value === null &&
    !navigating.value,
)
// If a pre-menu GET was still running at resume, usePolling cannot start a
// second refresh yet. Wait for it, then require a new read, never its membership.
watch([list.loading, polling.paused], () => {
  if (needsMenuRead && !list.loading.value && !polling.paused.value) void list.refresh()
})
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
  <section class="workspace lobby-workspace" aria-labelledby="page-title">
    <div class="lobby-welcome">
      <header class="lobby-intro">
        <div>
          <p class="lobby-kicker">WORDMACHINE · 单词竞技台</p>
          <h1 id="page-title" tabindex="-1">对局大厅</h1>
          <p class="hint">让每一次作答，都有清晰的回响。选择一个词典，开始一场对战。</p>
        </div>
        <button type="button" class="button button-primary" @click="dialog = { kind: 'create' }">
          创建新对局
        </button>
      </header>
      <LobbyAccountCard />
    </div>
    <div class="toolbar">
      <button
        v-if="list.error.value"
        type="button"
        class="button"
        :disabled="list.loading.value"
        @click="list.load"
      >
        重试读取列表
      </button>
      <label class="checkbox-label"
        ><input v-model="autoRefresh" type="checkbox" />自动刷新并进入已开局对局（5 秒）</label
      >
    </div>
    <p class="hint" role="status">
      {{
        polling.paused.value
          ? '自动刷新已暂停（手动关闭、离线、后台、弹窗或导航菜单打开）。'
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
    <SkeletonBlock v-if="list.loading.value && !list.result.value && !list.error.value" />
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
