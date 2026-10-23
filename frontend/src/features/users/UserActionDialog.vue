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
    password.value = confirmation.value = ''
    emit('saved')
  })
}
</script>

<template>
  <ModalDialog :title="titles[action]" :busy="task.pending.value" @close="emit('close')">
    <p>目标用户：<UserName :name="user.username" :rating="user.rating" />（#{{ user.id }}）</p>
    <p class="hint">此操作会撤销该用户的所有会话。封禁保留历史数据；恢复不会复活旧会话。</p>
    <NoticeBanner :message="task.error.value" />
    <form @submit.prevent="submit">
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
          <SubmitButton :pending="task.pending.value">确认{{ titles[action] }}</SubmitButton>
        </div>
      </fieldset>
    </form>
  </ModalDialog>
</template>
