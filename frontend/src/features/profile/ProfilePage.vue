<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import FormField from '../../shared/ui/FormField.vue'
import FormPanel from '../../shared/ui/FormPanel.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import UserLink from '../../shared/ui/UserLink.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import { newPasswordError, confirmationError } from '../auth/validation'
import type { ProfileUpdate } from '../auth/service'

const services = useServices()
const router = useRouter()
const user = services.client.session.value?.user
const introduction = ref(user?.introduction ?? '')
const currentPassword = ref('')
const newPassword = ref('')
const confirmation = ref('')
const passwordError = ref('')
const confirmError = ref('')
const saved = ref('')
const task = useFormTask()

async function submit() {
  if (!user) return
  saved.value = ''
  passwordError.value = newPassword.value
    ? newPasswordError(newPassword.value, user.admin_level ?? 0)
    : ''
  confirmError.value = confirmationError(newPassword.value, confirmation.value)
  if (passwordError.value || confirmError.value) return
  if (newPassword.value && !currentPassword.value) {
    task.error.value = '修改密码时需要输入当前密码。'
    return
  }
  const data: ProfileUpdate = { introduction: introduction.value.trim() }
  if (newPassword.value) {
    data.current_password = currentPassword.value
    data.new_password = newPassword.value
  }
  await task.run(async (signal) => {
    const result = await services.auth.updateProfile(user.id, data, signal)
    currentPassword.value = newPassword.value = confirmation.value = ''
    if (result.reauthenticate)
      await router.replace({ name: 'login', query: { reason: 'password_changed' } })
    else saved.value = '资料已保存。'
  })
}
</script>

<template>
  <FormPanel
    title="修改资料"
    description="仅更新简介不需要输入密码。修改密码将退出所有已登录会话。"
  >
    <template v-if="user">
      <p>
        当前账号：<UserLink
          :id="user.id"
          :name="user.username"
          :rating="services.client.session.value?.user?.rating"
        />
      </p>
      <NoticeBanner :message="saved" kind="success" />
      <NoticeBanner :message="task.error.value" />
      <form :aria-busy="task.pending.value" @submit.prevent="submit">
        <fieldset :disabled="task.pending.value">
          <legend class="sr-only">个人资料</legend>
          <FormField
            id="introduction"
            v-model="introduction"
            label="个人简介"
            multiline
            :maxlength="255"
          />
          <h2>更改密码（可选）</h2>
          <FormField
            id="currentPassword"
            v-model="currentPassword"
            label="当前密码"
            type="password"
            autocomplete="current-password"
            :required="!!newPassword"
            :maxlength="4096"
          />
          <FormField
            id="newPassword"
            v-model="newPassword"
            label="新密码"
            type="password"
            autocomplete="new-password"
            :maxlength="128"
            :hint="
              user.admin_level === 5
                ? '16–128 个字符，包含大小写字母、数字和符号；首尾空白会保留。'
                : '6–128 个字符，首尾空白会保留。'
            "
            :error="passwordError"
          />
          <FormField
            id="confirmation"
            v-model="confirmation"
            label="确认新密码"
            type="password"
            autocomplete="new-password"
            :required="!!newPassword"
            :maxlength="128"
            :error="confirmError"
          />
          <SubmitButton :pending="task.pending.value">保存修改</SubmitButton>
        </fieldset>
      </form>
    </template>
    <p v-else role="status">登录已失效，正在返回登录页…</p>
  </FormPanel>
</template>
