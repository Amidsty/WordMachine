<script setup lang="ts">
import { reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import FormField from '../../shared/ui/FormField.vue'
import FormPanel from '../../shared/ui/FormPanel.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import { confirmationError, newPasswordError } from './validation'

const services = useServices()
const router = useRouter()
const task = useFormTask()
const form = reactive({ username: '', password: '', confirmation: '', introduction: '' })
const passwordError = ref('')
const confirmError = ref('')

async function submit() {
  passwordError.value = newPasswordError(form.password)
  confirmError.value = confirmationError(form.password, form.confirmation)
  if (passwordError.value || confirmError.value) return
  await task.run(async (signal) => {
    await services.auth.register(
      {
        username: form.username.trim(),
        password: form.password,
        introduction: form.introduction.trim(),
      },
      signal,
    )
    // Leaving/replacing this form cancels local acceptance, not server creation.
    signal.throwIfAborted()
    form.password = form.confirmation = ''
    await router.replace({ name: 'login', query: { registered: '1' } })
  })
}
</script>

<template>
  <div class="auth-layout auth-layout--register">
    <aside class="auth-story" aria-label="关于 WordMachine">
      <p class="auth-kicker">WORDMACHINE · 单词竞技台</p>
      <p class="auth-statement">从好奇开始，<br />在作答中前进。</p>
      <p>创建账号，开始练习与对战。</p>
      <p class="hint">Rated 更新 Rating；Unrated 保留练习表现，不更新 Rating。</p>
    </aside>
    <FormPanel title="注册账号" description="创建普通用户账号；注册成功后再登录。">
      <NoticeBanner :message="task.error.value" />
      <form :aria-busy="task.pending.value" @submit.prevent="submit">
        <fieldset :disabled="task.pending.value">
          <legend class="sr-only">注册信息</legend>
          <FormField
            id="username"
            v-model="form.username"
            label="用户名"
            required
            autocomplete="username"
            :minlength="3"
            :maxlength="255"
            hint="3–255 个字符。"
          />
          <FormField
            id="password"
            v-model="form.password"
            label="密码"
            type="password"
            required
            autocomplete="new-password"
            :maxlength="128"
            hint="6–128 个字符，首尾空白会保留。"
            :error="passwordError"
          />
          <FormField
            id="confirmation"
            v-model="form.confirmation"
            label="确认密码"
            type="password"
            required
            autocomplete="new-password"
            :maxlength="128"
            :error="confirmError"
          />
          <FormField
            id="introduction"
            v-model="form.introduction"
            label="个人简介（可选）"
            multiline
            :maxlength="255"
            hint="最多 255 个字符。"
          />
          <SubmitButton :pending="task.pending.value">注册</SubmitButton>
        </fieldset>
      </form>
      <p class="form-footer">已有账号？<RouterLink to="/login/">前往登录</RouterLink></p>
    </FormPanel>
  </div>
</template>
