<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
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
    if (result.reauthenticate) {
      currentPassword.value = newPassword.value = confirmation.value = ''
      // A valid password response deliberately destroys this identity's form.
      // Do not mistake that disposal for a failed write, or navigate a new user.
      if (
        services.client.sessionEndReason.value === 'password_changed' &&
        !services.client.session.value?.authenticated &&
        router.currentRoute.value.name === 'profile'
      )
        await router.replace({ name: 'login', query: { reason: 'password_changed' } })
    } else {
      signal.throwIfAborted()
      currentPassword.value = newPassword.value = confirmation.value = ''
      saved.value = '资料已保存。'
    }
  })
}
</script>

<template>
  <FormPanel
    class="profile-editor"
    title="修改资料"
    description="仅更新简介不需要输入密码。修改密码将退出所有已登录会话。"
  >
    <template v-if="user">
      <div class="profile-account-heading">
        <p>
          当前账号：<UserLink
            :id="user.id"
            :name="user.username"
            :rating="services.client.session.value?.user?.rating"
          />
        </p>
        <RouterLink class="button" :to="`/user/${user.id}/`">查看我的公开资料</RouterLink>
      </div>
      <NoticeBanner :message="saved" kind="success" />
      <NoticeBanner :message="task.error.value" />
      <form :aria-busy="task.pending.value" @submit.prevent="submit">
        <fieldset :disabled="task.pending.value">
          <legend class="sr-only">个人资料</legend>
          <div class="profile-form-groups">
            <section aria-labelledby="profile-basics-title" class="profile-form-group">
              <h2 id="profile-basics-title">个人资料</h2>
              <p class="hint">简介展示在公开资料页；此处不修改用户名。</p>
              <FormField
                id="introduction"
                v-model="introduction"
                label="个人简介"
                multiline
                :maxlength="255"
              />
            </section>
            <section
              aria-labelledby="profile-password-title"
              class="profile-form-group password-group"
            >
              <h2 id="profile-password-title">更改密码（可选）</h2>
              <p class="hint">
                只修改简介时，请将密码栏留空。填写新密码时，需要当前密码与一致的确认密码。
              </p>
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
            </section>
          </div>
          <div class="profile-save">
            <p class="hint">
              一次保存会同时提交简介及已填写的新密码；离开页面不代表撤销已发送的修改。
            </p>
            <SubmitButton :pending="task.pending.value">保存修改</SubmitButton>
          </div>
        </fieldset>
      </form>
    </template>
    <p v-else role="status">登录已失效，正在返回登录页…</p>
  </FormPanel>
</template>

<style scoped>
.profile-editor {
  max-width: 68rem;
}
.profile-account-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-block: 1.5rem;
  overflow-wrap: anywhere;
}
.profile-account-heading p {
  margin: 0;
  min-width: 0;
}
.profile-form-groups {
  display: grid;
  gap: 1.5rem;
}
.profile-form-group {
  min-width: 0;
}
.profile-form-group h2 {
  margin-top: 0;
}
.password-group {
  border-top: 1px solid var(--ui-line);
  padding-top: 1.5rem;
}
.profile-save {
  border-top: 1px solid var(--ui-line);
  padding-top: 1rem;
}
@media (min-width: 900px) {
  .profile-form-groups {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 2rem;
  }
  .password-group {
    border-top: 0;
    border-left: 1px solid var(--ui-line);
    padding: 0 0 0 2rem;
  }
}
</style>
