<script setup lang="ts">
import { onMounted, ref, shallowRef } from 'vue'
import { useServices } from '../../app/services'
import { ApiError } from '../../shared/api/client'
import { newGameRequestId as newRequestId } from '../../shared/api/gameCommand'
import { errorMessage, useFormTask } from '../../shared/forms/useFormTask'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import UserName from '../../shared/ui/UserName.vue'
import SkeletonBlock from '../../shared/ui/SkeletonBlock.vue'
import { storedNumber } from '../games/presentation'
import './managementUi.css'
import type { ManagedUser, RatingIntent, RatingReview } from './service'

const props = defineProps<{ user: ManagedUser }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const review = shallowRef<RatingReview | null>(null)
const intent = shallowRef<RatingIntent | null>(null)
const amount = ref('')
const reason = ref('')
const publishReason = ref(false)
const publishActor = ref(false)
const password = ref('')
const attempted = ref(false)
const validation = ref('')
const readFailed = ref(false)
const readDenied = ref(false)
const task = useFormTask()

async function load() {
  await task.run(async (signal) => {
    readFailed.value = false
    let data: RatingReview
    try {
      data = await services.users.reviewRating(props.user.id, signal)
    } catch (error) {
      if (!signal.aborted) {
        readFailed.value = true
        // Only a confirmed resource-read denial discards private data. A failed
        // write or transient reread must retain the original retryable intent.
        if (
          error instanceof ApiError &&
          ((error.status === 403 && error.code === 'forbidden') ||
            (error.status === 404 && error.code === 'not_found'))
        ) {
          readDenied.value = true
          review.value = intent.value = null
          amount.value = reason.value = password.value = validation.value = ''
          attempted.value = false
          publishReason.value = publishActor.value = false
        }
      }
      throw error
    }
    if (signal.aborted || services.client.session.value?.user?.id !== actorId) return
    readDenied.value = false
    review.value = data
    amount.value = String(data.rating)
    intent.value = null
    attempted.value = false
    publishReason.value = publishActor.value = false
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
      publish_reason: publishReason.value,
      publish_actor: publishActor.value,
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
    <div class="managed-identity">
      <p>
        目标用户：<UserName :name="user.username" :rating="review?.rating ?? user.rating" />（#{{
          user.id
        }}）
      </p>
      <p class="hint">私有管理审查 · 原因和操作者按每条记录的公开选择展示，事件编号仅管理可见</p>
    </div>
    <p class="hint">
      Lv.4/5 可调整自己或严格下级的活动账号，与双方 Rating 高低无关。进行中的对局禁止调分（含
      Unrated 参赛，单纯观战不算）；不会改写旧比赛结果，不会撤销用户会话。
    </p>
    <SkeletonBlock v-if="task.pending.value && !review && !task.error.value" variant="account" />
    <NoticeBanner :message="validation || task.error.value" />
    <p v-if="readDenied" class="management-impact">
      本次读取确认该评分审查不可访问，旧私有详情及本地原请求已清理；这不代表撤销已提交的调整，也不代表全站退出。请核对权限或联系有权管理员。
    </p>
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
      <section class="rating-review" aria-label="本次评分审查">
        <h3>本次读取的评分审查</h3>
        <p v-if="readFailed" class="hint">
          本次审查信息未刷新，以下仍为上次读取的记录；原意图未被替换，权限与版本仍由服务端复核。
        </p>
        <dl class="management-facts">
          <div>
            <dt>当前 Rating</dt>
            <dd class="review-rating">{{ review.rating }}</dd>
          </div>
          <div>
            <dt>余额版本（事件头）</dt>
            <dd>{{ review.rating_event_id ?? '尚无统一流水' }}</dd>
          </div>
        </dl>
        <p
          v-if="review.rating_state && review.rating_state.public_rating !== review.rating"
          class="hint"
        >
          本次读取的评分信息不一致，请重新审查。
        </p>
        <p class="hint">
          本次读取不代表持续同步。填写的是新的
          Rating，而非增减量；此操作不会重算比赛成绩，也不会退出该账号的会话。
        </p>
      </section>
      <p v-if="review.running_game" role="alert">该用户正在进行对局，请在对局结束后重新审查。</p>
      <form v-if="!intent" class="management-form management-section" @submit.prevent="prepare">
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
          <fieldset class="rating-visibility" aria-describedby="rating-visibility-help">
            <legend>公开历史显示设置</legend>
            <label class="checkbox-label"
              ><input
                id="rating-publish-reason"
                v-model="publishReason"
                type="checkbox"
              />公开原因</label
            >
            <label class="checkbox-label"
              ><input
                id="rating-publish-actor"
                v-model="publishActor"
                type="checkbox"
              />公开操作者</label
            >
            <p id="rating-visibility-help" class="hint">
              公开后，任何人（包括未登录访客）都能在该用户的 Rating
              历史看到对应内容。未勾选的内容仅在有权访问的管理流水中显示。
              选择随本次调整保存，提交后不能通过重试修改；公开内容可能被他人保存。
            </p>
          </fieldset>
          <button type="submit" class="button button-danger">审查修改</button>
        </fieldset>
      </form>
      <form v-else class="management-form management-section" @submit.prevent="submit">
        <div class="management-impact">
          <p class="hint">
            10
            秒未确认会停止等待，但不代表回滚。不会自动重发；手动重试保留原编号、目标、原因、公开选择及审查版本，仅需重新输入本人密码。
          </p>
          <p v-if="attempted" role="alert">
            结果可能已经提交。关闭或刷新会丢失本页重试信息；建议先重试原请求取得回执，或核对当前状态后再创建新意图。
          </p>
        </div>
        <fieldset :disabled="task.pending.value">
          <legend>确认本次调整 · 指定绝对公开 R</legend>
          <p>
            <strong>{{ intent.expected_rating }} → {{ intent.new_rating }}</strong
            >（变化 {{ intent.new_rating - intent.expected_rating }}）
          </p>
          <p class="multiline">原因：{{ intent.reason }}</p>
          <p>
            公开原因：{{ intent.publish_reason ? '是（所有访客可见）' : '否（仅管理流水可见）' }}
          </p>
          <p>
            公开操作者：{{
              intent.publish_actor ? `是（所有访客可见：用户 #${actorId}）` : '否（仅管理流水可见）'
            }}
          </p>
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
          <button
            type="submit"
            class="button button-danger danger-confirm"
            :aria-busy="task.pending.value"
          >
            {{ attempted ? '重试原请求' : '确认修改 Rating' }}
          </button>
        </fieldset>
      </form>
      <button type="button" class="button" :disabled="task.pending.value" @click="load">
        {{ intent ? '放弃原请求并重新审查（不撤销已提交结果）' : '重新审查' }}
      </button>
      <section class="management-section rating-ledger" aria-label="私有统一评分流水">
        <h3>统一评分流水（最近最多 50 条，最新在前）</h3>
        <p class="hint">
          比赛与人工调整分别记录；升级前的旧历史不补造为事件，仍保留在原比赛历史中。
        </p>
        <p class="hint">
          这是最近统一事件，不是完整公开历史；无事件不等于没有旧比赛。以下时间为保存的 UTC 记录。
        </p>
        <p v-if="!review.events.length" class="hint">暂无统一评分事件。</p>
        <ol v-else class="rating-events">
          <li v-for="entry in review.events" :key="entry.id">
            <div class="event-heading">
              <strong>{{
                entry.kind === 'manual'
                  ? '人工调整'
                  : entry.game_id === null
                    ? '比赛（编号未记录）'
                    : `比赛 #${entry.game_id}`
              }}</strong>
              <span
                class="event-delta"
                :class="{ 'event-positive': entry.delta > 0, 'event-negative': entry.delta < 0 }"
                >{{ storedNumber(entry.delta, true) }}</span
              >
            </div>
            <p class="event-balance">
              公开 R：{{ entry.rating_before }} → {{ entry.rating_after }}
            </p>
            <p class="hint">
              事件 #{{ entry.id }} · 序号 {{ entry.sequence
              }}<span v-if="entry.actor_id"> · 操作者 #{{ entry.actor_id }}</span>
            </p>
            <time :datetime="entry.recorded_at">{{ entry.recorded_at }}</time>
            <p v-if="entry.reason" class="multiline">{{ entry.reason }}</p>
            <p v-if="entry.kind === 'manual'" class="hint">
              公开原因：{{ entry.publish_reason ? '是' : '否' }} · 公开操作者：{{
                entry.publish_actor ? '是' : '否'
              }}
            </p>
          </li>
        </ol>
      </section>
    </template>
  </ModalDialog>
</template>

<style scoped>
.review-rating {
  font-size: 1.6rem;
}
.rating-ledger,
.rating-review,
.rating-events li {
  overflow-wrap: anywhere;
}
.rating-events {
  list-style: none;
  padding: 0;
}
.rating-events li {
  padding: 1rem 0;
  border-bottom: 1px solid var(--ui-line);
}
.event-heading {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: space-between;
}
.event-delta,
.event-balance {
  font-variant-numeric: tabular-nums;
}
.event-positive {
  color: var(--ui-positive);
}
.event-negative {
  color: var(--ui-negative);
}
.rating-events time {
  font-size: 0.85rem;
  color: var(--ui-text-muted);
}
.rating-events p {
  margin-block: 0.5rem;
}
</style>
