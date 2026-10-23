<script setup lang="ts">
import { computed, nextTick, onMounted, ref, shallowRef } from 'vue'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import UserName from '../../shared/ui/UserName.vue'
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
function close() {
  emit('close')
  void nextTick(() => {
    if (originFocus?.isConnected) originFocus.focus()
    else if (originHref) {
      const replacement = Array.from(document.querySelectorAll<HTMLAnchorElement>('a')).find(
        (link) => link.getAttribute('href') === originHref,
      )
      replacement?.focus()
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
      <div class="actions">
        <RouterLink v-if="user.deleted === false" :to="`/user/${user.id}/`" @click="emit('close')"
          >查看公开资料</RouterLink
        >
        <RouterLink v-if="user.id === actor?.id" to="/changepw/" @click="emit('close')"
          >修改本人资料 / 密码</RouterLink
        >
        <button
          v-if="flags?.can_edit_profile"
          type="button"
          class="button"
          @click="action = 'update'"
        >
          编辑资料
        </button>
        <button v-if="flags?.can_set_level" type="button" class="button" @click="action = 'level'">
          修改等级
        </button>
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
        <button v-if="flags?.can_restore" type="button" class="button" @click="action = 'restore'">
          恢复用户
        </button>
        <button
          v-if="flags?.can_adjust_rating"
          type="button"
          class="button"
          @click="action = 'rating'"
        >
          调整 Rating / 流水
        </button>
      </div>
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
