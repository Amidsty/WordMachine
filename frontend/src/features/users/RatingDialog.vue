<script setup lang="ts">
import { onMounted, ref, shallowRef } from 'vue'
import { useServices } from '../../app/services'
import { newGameRequestId as newRequestId } from '../../shared/api/gameCommand'
import { errorMessage, useFormTask } from '../../shared/forms/useFormTask'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import UserName from '../../shared/ui/UserName.vue'
import type { ManagedUser, RatingIntent, RatingReview } from './service'

const props = defineProps<{ user: ManagedUser }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const review = shallowRef<RatingReview | null>(null)
const intent = shallowRef<RatingIntent | null>(null)
const amount = ref('')
const reason = ref('')
const password = ref('')
const attempted = ref(false)
const validation = ref('')
const task = useFormTask()

async function load() {
  await task.run(async (signal) => {
    const data = await services.users.reviewRating(props.user.id, signal)
    if (signal.aborted || services.client.session.value?.user?.id !== actorId) return
    review.value = data
    amount.value = String(data.rating)
    intent.value = null
    attempted.value = false
    password.value = validation.value = ''
  })
}
function prepare() {
  if (!review.value || task.pending.value || review.value.running_game || intent.value) return
  const value = Number(amount.value)
  if (
    !/^-?(0|[1-9]\d*)$/.test(amount.value) ||
    !Number.isInteger(value) ||
    value < -2147483648 ||
    value > 2147483647
  ) {
    validation.value = 'Rating 必须是 -2147483648 至 2147483647 的整数。'
    return
  }
  if (value === review.value.rating || !reason.value.trim() || reason.value.trim().length > 500) {
    validation.value = '请填写不同的新 Rating 和 1–500 字的调整原因。'
    return
  }
  try {
    intent.value = Object.freeze({
      request_id: newRequestId(),
      expected_rating: review.value.rating,
      expected_event_id: review.value.rating_event_id,
      new_rating: value,
      reason: reason.value.trim(),
    })
    validation.value = ''
  } catch (error) {
    validation.value = errorMessage(error)
  }
}
async function submit() {
  if (!intent.value || !actorId || !password.value) return
  const original = intent.value
  await task.run(async (signal) => {
    attempted.value = true
    const controller = new AbortController()
    const abort = () => controller.abort()
    signal.addEventListener('abort', abort, { once: true })
    if (signal.aborted) abort()
    const timer = setTimeout(abort, 10000)
    try {
      await services.users.adjustRating(
        props.user.id,
        original,
        password.value,
        actorId,
        controller.signal,
      )
      if (
        !signal.aborted &&
        !controller.signal.aborted &&
        services.client.session.value?.user?.id === actorId
      )
        emit('saved')
    } finally {
      clearTimeout(timer)
      signal.removeEventListener('abort', abort)
      password.value = ''
    }
  })
}
onMounted(() => {
  void load()
})
</script>

<template>
  <ModalDialog title="调整 Rating / 评分流水" :busy="task.pending.value" @close="emit('close')">
    <p>
      目标用户：<UserName :name="user.username" :rating="review?.rating ?? user.rating" />（#{{
        user.id
      }}）
    </p>
    <p class="hint">
      Lv.4/5 可调整自己或严格下级；进行中的对局禁止调分。不会改写旧比赛结果，不会撤销用户会话。
    </p>
    <NoticeBanner :message="validation || task.error.value" />
    <button
      v-if="!review"
      type="button"
      class="button"
      :disabled="task.pending.value"
      @click="load"
    >
      重新加载审查信息
    </button>
    <template v-if="review">
      <p>
        当前 Rating：<strong>{{ review.rating }}</strong> · 余额版本：{{
          review.rating_event_id ?? '尚无统一流水'
        }}
      </p>
      <p v-if="review.rating_state">
        当前内部 Rating：{{ review.rating_state.internal_rating }} · 剩余基础额度：{{
          review.rating_state.remaining_bonus
        }}。本操作只指定公开 Rating，额度保持不变；内部 Rating 同步变化，不套用高分系数。
      </p>
      <p v-else>内部 Rating 和剩余额度未记录，不能推算。</p>
      <p v-if="review.running_game" role="alert">该用户正在进行对局，请在对局结束后重新审查。</p>
      <form v-if="!intent" @submit.prevent="prepare">
        <fieldset :disabled="task.pending.value || review.running_game">
          <legend class="sr-only">填写 Rating 调整</legend>
          <FormField
            id="rating-amount"
            v-model="amount"
            label="新的 Rating（不是增减量）"
            required
            :maxlength="11"
          />
          <FormField
            id="rating-reason"
            v-model="reason"
            label="调整原因（管理流水可见，请勿填写密码）"
            multiline
            required
            :maxlength="500"
          />
          <button type="submit" class="button button-danger">审查修改</button>
        </fieldset>
      </form>
      <form v-else @submit.prevent="submit">
        <fieldset :disabled="task.pending.value">
          <legend>确认本次调整</legend>
          <p>
            <strong>{{ intent.expected_rating }} → {{ intent.new_rating }}</strong
            >（变化 {{ intent.new_rating - intent.expected_rating }}）
          </p>
          <p class="multiline">原因：{{ intent.reason }}</p>
          <p class="hint">请求编号：{{ intent.request_id }}</p>
          <FormField
            id="rating-password"
            v-model="password"
            label="本人当前密码（不是目标用户密码）"
            type="password"
            autocomplete="current-password"
            required
            :maxlength="4096"
          />
          <button type="submit" class="button button-danger">
            {{ attempted ? '重试原请求' : '确认修改 Rating' }}
          </button>
        </fieldset>
        <p class="hint">
          10
          秒未确认会停止等待，但不代表回滚。不会自动重发；手动重试保留原编号、目标、原因及审查版本，仅需重新输入本人密码。
        </p>
        <p v-if="attempted" role="alert">
          结果可能已经提交。关闭或刷新会丢失本页重试信息；建议先重试原请求取得回执，或核对当前状态后再创建新意图。
        </p>
      </form>
      <button type="button" class="button" :disabled="task.pending.value" @click="load">
        {{ intent ? '放弃原请求并重新审查（不撤销已提交结果）' : '刷新审查信息' }}
      </button>
      <h3>统一评分流水（最近 50 条，最新在前）</h3>
      <p class="hint">比赛与人工调整分别记录；升级前的旧历史不补造为事件，仍保留在原比赛历史中。</p>
      <p v-if="!review.events.length">暂无统一评分事件。</p>
      <ol v-else>
        <li v-for="entry in review.events" :key="entry.id">
          <strong>{{ entry.kind === 'manual' ? '人工调整' : `比赛 #${entry.game_id}` }}</strong>
          · {{ entry.rating_before }} → {{ entry.rating_after }}（{{ entry.delta }}）
          <span v-if="entry.actor_id"> · 操作者 #{{ entry.actor_id }}</span>
          <time :datetime="entry.recorded_at"> · {{ entry.recorded_at }}</time>
          <p v-if="entry.reason" class="multiline">{{ entry.reason }}</p>
        </li>
      </ol>
    </template>
  </ModalDialog>
</template>
