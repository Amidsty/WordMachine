<script setup lang="ts">
import { onMounted, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { useFormTask, errorMessage } from '../../shared/forms/useFormTask'
import { newGameRequestId } from '../../shared/api/gameCommand'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import type { Dictionary } from './service'
import type { Promotion, PromotionReview, PromotionDecision } from './promotions'

const props = defineProps<{ dictionary?: Dictionary; application?: Promotion }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const task = useFormTask()
const review = shallowRef<PromotionReview | null>(null)
const loading = ref(Boolean(props.application))
const reason = ref(''),
  lower = ref(''),
  upper = ref(''),
  approve = ref('false')
const controller = new AbortController()
let alive = true
onScopeDispose(() => {
  alive = false
  controller.abort()
})
watch(
  () =>
    JSON.stringify([
      services.client.session.value?.user?.id,
      services.client.session.value?.user?.admin_level,
      services.client.session.value?.csrf_token,
    ]),
  () => {
    alive = false
    controller.abort()
    emit('close')
  },
)
onMounted(async () => {
  if (!props.application) return
  try {
    const value = await services.promotions.review(props.application, controller.signal)
    if (alive) review.value = value
  } catch (cause) {
    if (alive) task.error.value = errorMessage(cause)
  } finally {
    if (alive) loading.value = false
  }
})
let intent: { request_id: string; expected_version: number; reason: string } | null = null
async function submit() {
  if (!actorId || loading.value || task.pending.value) return
  if (!reason.value.trim()) {
    task.error.value = '请填写申请或审核原因。'
    return
  }
  const isApproval = approve.value === 'true'
  if (
    props.application &&
    isApproval &&
    (!/^-?(?:0|[1-9][0-9]*)$/.test(lower.value) ||
      !/^-?(?:0|[1-9][0-9]*)$/.test(upper.value) ||
      Number(lower.value) < -2147483648 ||
      Number(upper.value) > 2147483647 ||
      Number(lower.value) > Number(upper.value) ||
      !review.value?.review_token)
  ) {
    task.error.value = '通过时须填写有效整数上下界，并重新确认有效的词典审查。'
    return
  }
  await task.run(async (signal) => {
    if (props.application) {
      if (!review.value || review.value.application.state !== 0)
        throw new Error('申请已处理或尚未加载，请关闭后刷新。')
      const body: PromotionDecision = isApproval
        ? {
            approve: true,
            reason: reason.value.trim(),
            rated_min: Number(lower.value),
            rated_max: Number(upper.value),
            review_token: review.value.review_token!,
          }
        : { approve: false, reason: reason.value.trim() }
      await services.promotions.decide(props.application, body, actorId, signal)
    } else if (props.dictionary) {
      if (props.dictionary.config_version === undefined) throw new Error('请刷新词典后重新申请。')
      if (!intent || intent.reason !== reason.value.trim())
        intent = Object.freeze({
          request_id: newGameRequestId(),
          expected_version: props.dictionary.config_version,
          reason: reason.value.trim(),
        })
      await services.promotions.submit(props.dictionary.id, intent, actorId, signal)
    }
    if (alive && !signal.aborted) emit('saved')
  })
}
</script>

<template>
  <ModalDialog
    :title="application ? '审核系统词典申请' : '申请转为系统词典'"
    :busy="task.pending.value"
    @close="emit('close')"
  >
    <NoticeBanner :message="task.error.value" />
    <p v-if="loading" role="status">正在读取申请与词典审查…</p>
    <template v-if="review">
      <p>申请原因：{{ review.application.reason }}</p>
      <p>
        当前词典：{{ review.dict.dictname }}；Perf 倍率 ×{{ review.dict.multiplier }}；难度 D：{{
          review.dict.difficulty ?? '未记录'
        }}（默认1500不代表已标定）；有效词条 {{ review.word_count ?? '暂不可用' }}。
      </p>
      <RouterLink :to="`/admin/dicts/${review.dict.id}/`" target="_blank"
        >查看词典内容（新标签页）</RouterLink
      >
      <p v-if="!review.review_token" class="hint">
        当前词典不可通过此审查；可以填写原因拒绝。已处理申请不能再次决策。
      </p>
    </template>
    <p v-else-if="dictionary">词典：{{ dictionary.dictname }}</p>
    <p class="hint">
      通过后词典归系统，原所有者不再凭所有权维护；由 Lv.3+ 维护。词条、倍率和已有比赛快照不重写。
    </p>
    <form @submit.prevent="submit">
      <fieldset
        :disabled="
          task.pending.value ||
          loading ||
          (!!application && (!review || review.application.state !== 0))
        "
      >
        <legend class="sr-only">系统词典申请表</legend>
        <template v-if="application">
          <label for="promotion-decision">审核结果</label>
          <select id="promotion-decision" v-model="approve">
            <option value="false">拒绝</option>
            <option value="true" :disabled="!review?.review_token">通过</option>
          </select>
          <template v-if="approve === 'true'">
            <FormField
              id="promotion-lower"
              v-model="lower"
              label="Rated 下界 L"
              required
              :maxlength="11"
            />
            <FormField
              id="promotion-upper"
              v-model="upper"
              label="Rated 上界 R"
              required
              :maxlength="11"
            />
            <p class="hint">闭区间包含端点，必须由审核管理员明确填写，不自动采用默认范围。</p>
          </template>
        </template>
        <FormField
          id="promotion-reason"
          v-model="reason"
          :label="application ? '审核原因' : '申请原因'"
          required
          :maxlength="500"
        />
        <p class="hint">
          失败不会自动重发。超时或关闭不代表回滚；请先查看申请记录。原内容手动重试保留原意图；更改内容前先核对结果。
        </p>
        <SubmitButton :pending="task.pending.value">{{
          application ? '确认审核' : '确认申请'
        }}</SubmitButton>
      </fieldset>
    </form>
    <button type="button" class="button" :disabled="task.pending.value" @click="emit('close')">
      关闭并核对记录
    </button>
  </ModalDialog>
</template>
