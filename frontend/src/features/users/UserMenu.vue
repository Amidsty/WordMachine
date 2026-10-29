<script setup lang="ts">
import { computed, nextTick, onMounted, ref, shallowRef } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import UserName from '../../shared/ui/UserName.vue'
import SkeletonBlock from '../../shared/ui/SkeletonBlock.vue'
import './managementUi.css'
import UserActionDialog from './UserActionDialog.vue'
import RatingDialog from './RatingDialog.vue'
import type { ManagedUser, UserAction } from './service'

const props = defineProps<{ uid: number }>()
const emit = defineEmits<{ close: [] }>()
const services = useServices()
const actor = services.client.session.value?.user
const user = shallowRef<ManagedUser | null>(null)
const action = ref<UserAction | 'rating' | null>(null)
const notice = ref('')
const task = useFormTask()
const originFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
const originHref = originFocus?.closest('a')?.getAttribute('href')
const originControlId = originFocus?.matches('button[data-profile-management]')
  ? originFocus.id
  : undefined
const route = useRoute()
const originPath = route.path
const originCsrf = services.client.session.value?.csrf_token
function close() {
  emit('close')
  void nextTick(() => {
    const session = services.client.session.value
    if (
      route.path !== originPath ||
      session?.csrf_token !== originCsrf ||
      session?.user?.id !== actor?.id ||
      session?.user?.type !== actor?.type ||
      session?.user?.admin_level !== actor?.admin_level
    )
      return
    if (originFocus?.isConnected) originFocus.focus()
    else if (originHref) {
      const replacement = Array.from(document.querySelectorAll<HTMLAnchorElement>('a')).find(
        (link) => link.getAttribute('href') === originHref,
      )
      replacement?.focus()
    } else if (originControlId && document.activeElement === document.body) {
      // A successful write refreshes the public profile and replaces its header.
      // Restore only the same visible control, not a new identity/page or a
      // different focus destination deliberately chosen by the user.
      const replacement = document.getElementById(originControlId)
      if (
        replacement instanceof HTMLButtonElement &&
        !replacement.disabled &&
        !replacement.hidden &&
        getComputedStyle(replacement).display !== 'none'
      )
        replacement.focus()
    }
  })
}
const flags = computed(() => user.value?.capabilities)
const hasActions = computed(
  () =>
    flags.value &&
    [
      flags.value.can_edit_profile,
      flags.value.can_reset_password,
      flags.value.can_ban,
      flags.value.can_restore,
      flags.value.can_set_level,
      flags.value.can_adjust_rating,
    ].some(Boolean),
)
async function load() {
  user.value = null
  await task.run(async (signal) => {
    const result =
      (actor?.admin_level ?? 0) > 0
        ? await services.users.get(props.uid, signal)
        : { ...(await services.people.profile(props.uid, signal)), deleted: false }
    if (
      !signal.aborted &&
      services.client.session.value?.user?.id === actor?.id &&
      result.id === props.uid
    )
      user.value = result
  })
}
onMounted(load)
function back() {
  action.value = null
  void load() // Read-only refresh; never resubmit the cancelled/uncertain operation.
}
function saved() {
  const rating = action.value === 'rating'
  action.value = null
  notice.value = rating
    ? '已收到 Rating 调整回执，会话未撤销。'
    : '用户已更新，目标用户会话已撤销。'
  services.userChanges.value++
  if (rating && props.uid === actor?.id)
    void services.client.loadSession(true).catch(() => undefined)
  void load()
}
</script>

<template>
  <RatingDialog v-if="action === 'rating' && user" :user="user" @close="back" @saved="saved" />
  <UserActionDialog
    v-else-if="action && action !== 'rating' && user"
    :user="user"
    :action="action"
    @close="back"
    @saved="saved"
  />
  <ModalDialog v-else title="用户操作" @close="close">
    <NoticeBanner :message="notice" kind="success" />
    <NoticeBanner :message="task.error.value" />
    <p v-if="task.pending.value" role="status">正在读取用户及可用操作…</p>
    <SkeletonBlock v-if="task.pending.value && !user && !task.error.value" variant="lines" />
    <button
      v-if="task.error.value"
      type="button"
      class="button"
      :disabled="task.pending.value"
      @click="load"
    >
      重新读取用户
    </button>
    <template v-if="user">
      <div class="managed-identity">
        <p>
          <UserName :name="user.username" :rating="user.rating" />（#{{ user.id }}）<span
            v-if="user.id === actor?.id"
          >
            · 当前账号</span
          >
        </p>
        <p>
          Rating：{{ user.rating ?? '记录缺失' }} ·
          {{ user.admin_level ? `管理员 Lv.${user.admin_level}` : '普通用户（0 级）' }} ·
          {{ user.deleted === null ? '状态待审查' : user.deleted ? '已封禁' : '正常' }}
        </p>
        <p class="multiline">{{ user.introduction || '暂无简介' }}</p>
      </div>
      <section
        v-if="user.deleted === false || user.id === actor?.id"
        class="management-section"
        aria-label="资料与本人设置"
      >
        <h3>资料与本人设置</h3>
        <div class="actions">
          <RouterLink v-if="user.deleted === false" :to="`/user/${user.id}/`" @click="emit('close')"
            >查看公开资料</RouterLink
          >
          <RouterLink v-if="user.id === actor?.id" to="/changepw/" @click="emit('close')"
            >修改本人资料 / 密码</RouterLink
          >
        </div>
      </section>
      <section
        v-if="flags?.can_edit_profile || flags?.can_set_level"
        class="management-section"
        aria-label="账号管理"
      >
        <h3>账号管理</h3>
        <div class="actions">
          <button
            v-if="flags?.can_edit_profile"
            type="button"
            class="button"
            @click="action = 'update'"
          >
            编辑资料
          </button>
          <button
            v-if="flags?.can_set_level"
            type="button"
            class="button"
            @click="action = 'level'"
          >
            修改等级
          </button>
        </div>
      </section>
      <section v-if="flags?.can_adjust_rating" class="management-section" aria-label="评分审查">
        <h3>评分审查</h3>
        <p class="hint">私有管理流水不是公开比赛历史；打开审查不会自动调分。</p>
        <button type="button" class="button" @click="action = 'rating'">调整 Rating / 流水</button>
      </section>
      <section
        v-if="flags?.can_reset_password || flags?.can_ban || flags?.can_restore"
        class="management-section"
        aria-label="密码与账号状态"
      >
        <h3>密码与账号状态</h3>
        <p class="hint">以下操作会撤销目标用户会话；恢复账号不会复活旧会话。</p>
        <div class="actions">
          <button
            v-if="flags?.can_reset_password"
            type="button"
            class="button"
            @click="action = 'reset-password'"
          >
            重置密码
          </button>
          <button
            v-if="flags?.can_ban"
            type="button"
            class="button button-danger"
            @click="action = 'delete'"
          >
            封禁用户
          </button>
          <button
            v-if="flags?.can_restore"
            type="button"
            class="button"
            @click="action = 'restore'"
          >
            恢复用户
          </button>
        </div>
      </section>
      <p v-if="!hasActions" class="hint">没有可用的管理员修改操作。</p>
      <p v-else class="hint">
        仅列出当前权限允许的操作。修改等级仅限
        Lv.4/5，目标当前等级和拟授等级都必须低于自己；不能修改自己的等级。
      </p>
      <p class="hint">
        点击操作按钮只打开相应表单，仍需确认才提交。权限以服务器写入时检查为准。关闭或取消不代表撤销已经提交的操作，失败不会自动重发。
      </p>
    </template>
  </ModalDialog>
</template>
