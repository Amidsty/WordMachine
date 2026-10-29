<script setup lang="ts">
import { ref } from 'vue'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import { confirmationError, newPasswordError } from '../auth/validation'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import UserName from '../../shared/ui/UserName.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import './managementUi.css'
import type { ManagedUser, UserAction } from './service'

const props = defineProps<{ user: ManagedUser; action: UserAction }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const level = ref(props.user.admin_level ?? 0)
const reason = ref('')
const username = ref(props.user.username ?? '')
const introduction = ref(props.user.introduction ?? '')
const password = ref('')
const confirmation = ref('')
const passwordError = ref('')
const confirmError = ref('')
const task = useFormTask()
const titles = {
  update: '编辑资料',
  level: '修改等级',
  'reset-password': '重置密码',
  delete: '封禁用户',
  restore: '恢复用户',
}
async function submit() {
  if (!actorId) return
  if (props.action === 'reset-password') {
    passwordError.value = newPasswordError(password.value)
    confirmError.value = confirmationError(password.value, confirmation.value)
    if (passwordError.value || confirmError.value) return
  }
  await task.run(async (signal) => {
    if (props.action === 'level') {
      if (props.user.admin_version === undefined) throw new Error('Missing administrative version')
      await services.users.setLevel(
        props.user.id,
        level.value,
        props.user.admin_version,
        reason.value,
        actorId,
        signal,
      )
    } else if (props.action === 'update') {
      await services.users.update(
        props.user.id,
        { username: username.value, introduction: introduction.value },
        actorId,
        signal,
      )
    } else {
      await services.users.act(props.user.id, props.action, actorId, password.value, signal)
    }
    signal.throwIfAborted()
    password.value = confirmation.value = ''
    emit('saved')
  })
}
</script>

<template>
  <ModalDialog :title="titles[action]" :busy="task.pending.value" @close="emit('close')">
    <div class="managed-identity">
      <p>目标用户：<UserName :name="user.username" :rating="user.rating" />（#{{ user.id }}）</p>
      <p class="hint">
        本次打开时读取 ·
        {{ user.admin_level ? `管理员 Lv.${user.admin_level}` : '普通用户（0 级）' }} ·
        {{ user.deleted === null ? '状态待审查' : user.deleted ? '已封禁' : '正常' }}
      </p>
      <p v-if="action === 'level'" class="hint">
        审查版本：{{ user.admin_version ?? '未记录（不能提交等级修改）' }}
      </p>
    </div>
    <div class="management-impact">
      <p>此操作会撤销该用户的所有会话。</p>
      <p v-if="action === 'delete'">
        封禁保留历史数据。该账号不能继续登录或操作；这不是删除历史比赛或词典记录。
      </p>
      <p v-else-if="action === 'restore'">
        恢复不会复活旧会话；恢复的是账号活动状态，目标用户需重新登录。
      </p>
      <p v-else-if="action === 'reset-password'">
        仅设置目标用户的新密码，不恢复封禁状态，不修改历史成绩。
      </p>
      <p class="hint">
        确认丢失或网络失败不能证明未生效；取消只停止本地等待，不撤销服务端修改。不会自动重发。
      </p>
    </div>
    <NoticeBanner :message="task.error.value" />
    <form class="management-form" @submit.prevent="submit">
      <fieldset :disabled="task.pending.value">
        <legend class="sr-only">{{ titles[action] }}</legend>
        <template v-if="action === 'level'">
          <label for="edit-admin-level">新等级</label>
          <select id="edit-admin-level" v-model="level">
            <option
              v-for="value in (user.capabilities?.max_assignable_level ?? 0) + 1"
              :key="value"
              :value="value - 1"
            >
              {{ value - 1 === 0 ? '普通用户（0 级）' : `管理员 Lv.${value - 1}` }}
            </option>
          </select>
          <FormField
            id="level-reason"
            v-model="reason"
            label="调整原因"
            multiline
            required
            :maxlength="500"
          />
          <p class="hint">
            修改等级仅限
            Lv.4/5，且只能授予低于自己的等级；不能调整自己或同级、上级账户。确认丢失时先刷新核对，不会自动重发。
          </p>
        </template>
        <template v-if="action === 'update'">
          <FormField
            id="edit-username"
            v-model="username"
            label="用户名"
            required
            :maxlength="255"
            hint="新用户名至少 3 个字符；保留原有短用户名不受影响。"
          />
          <FormField
            id="edit-introduction"
            v-model="introduction"
            label="简介"
            multiline
            :maxlength="255"
          />
          <p class="hint">只修改用户名和简介；不修改 Rating、角色、封禁状态或历史记录。</p>
        </template>
        <template v-if="action === 'reset-password'">
          <p class="hint">仅 Lv.5 管理员可重置严格下级的密码；提交时服务器会重新检查权限。</p>
          <FormField
            id="reset-password"
            v-model="password"
            label="新密码"
            type="password"
            autocomplete="new-password"
            required
            :maxlength="128"
            :error="passwordError"
          />
          <FormField
            id="reset-confirmation"
            v-model="confirmation"
            label="确认新密码"
            type="password"
            autocomplete="new-password"
            required
            :maxlength="128"
            :error="confirmError"
          />
        </template>
        <div class="actions">
          <button type="button" class="button" @click="emit('close')">取消</button>
          <SubmitButton
            :pending="task.pending.value"
            :class="{ 'danger-confirm': action !== 'update' }"
            >确认{{ titles[action] }}</SubmitButton
          >
        </div>
      </fieldset>
    </form>
  </ModalDialog>
</template>
