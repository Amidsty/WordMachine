<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useServices } from '../../app/services'
import { afterLoginTarget } from '../../app/navigation'
import { useFormTask } from '../../shared/forms/useFormTask'
import FormField from '../../shared/ui/FormField.vue'
import FormPanel from '../../shared/ui/FormPanel.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'

const services = useServices()
const route = useRoute()
const router = useRouter()
const task = useFormTask()
const username = ref('')
const password = ref('')
const notice = computed(() =>
  route.query.registered === '1'
    ? '注册成功，请登录。'
    : route.query.reason === 'password_changed'
      ? '密码已更新，所有会话已退出，请重新登录。'
      : '',
)

async function submit() {
  if (!username.value.trim() || !password.value) return
  const target = afterLoginTarget(route.query.next)
  await task.run(async (signal) => {
    await services.auth.login(username.value.trim(), password.value, signal)
    password.value = ''
    // Accepting the new identity remounts this form; that is not a cancelled login.
    await router.replace(target)
  })
}
</script>

<template>
  <div class="auth-layout">
    <aside class="auth-story" aria-label="关于 WordMachine">
      <p class="auth-kicker">WORDMACHINE · 单词竞技台</p>
      <p class="auth-statement">从一个单词，<br />开始一场对战。</p>
      <p>专注每一次作答，清楚了解自己的表现。</p>
    </aside>
    <FormPanel title="登录" description="从一个单词，开始一场对战。">
      <NoticeBanner :message="notice" kind="success" />
      <NoticeBanner :message="task.error.value" />
      <form :aria-busy="task.pending.value" @submit.prevent="submit">
        <fieldset :disabled="task.pending.value">
          <legend class="sr-only">登录信息</legend>
          <FormField
            id="username"
            v-model="username"
            label="用户名"
            required
            autocomplete="username"
            :maxlength="255"
          />
          <FormField
            id="password"
            v-model="password"
            label="密码"
            type="password"
            required
            autocomplete="current-password"
            :maxlength="4096"
          />
          <SubmitButton :pending="task.pending.value">登录</SubmitButton>
        </fieldset>
      </form>
      <p class="form-footer">还没有账号？<RouterLink to="/register/">注册账号</RouterLink></p>
    </FormPanel>
  </div>
</template>
