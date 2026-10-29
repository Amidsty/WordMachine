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
import SkeletonBlock from '../../shared/ui/SkeletonBlock.vue'
import PromotionStatus from './PromotionStatus.vue'
import './dictionaryOperations.css'
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
    class="dictionary-operation promotion-dialog"
    :title="application ? '审核系统词典申请' : '申请转为系统词典'"
    :busy="task.pending.value"
    @close="emit('close')"
  >
    <NoticeBanner :message="task.error.value" />
    <p v-if="loading" role="status">正在读取申请与词典审查…</p>
    <SkeletonBlock v-if="loading && !review && !task.error.value" />
    <template v-if="review">
      <section class="promotion-application" aria-labelledby="promotion-application-title">
        <h3 id="promotion-application-title">
          申请记录 <PromotionStatus :state="review.application.state" />
        </h3>
        <p class="hint">
          词典 #{{ review.application.dict_id }} · 申请人 #{{ review.application.applicant_id }}
        </p>
        <p class="multiline">申请原因：{{ review.application.reason }}</p>
        <template v-if="review.application.state !== 0">
          <p class="multiline">审核原因：{{ review.application.review_reason ?? '未记录' }}</p>
          <p v-if="review.application.reviewer_id" class="hint">
            审核人 #{{ review.application.reviewer_id }} · 当时 Lv.{{
              review.application.reviewer_level ?? '未记录'
            }}
          </p>
          <p v-if="review.application.state === 1">
            保存的批准区间：[{{ review.application.rated_min ?? '未记录' }},
            {{ review.application.rated_max ?? '未记录' }}]
          </p>
          <p class="hint">申请已处理，仅供查看；不能在此发起新的审核决策。</p>
        </template>
      </section>
      <section class="operation-target" aria-labelledby="promotion-review-title">
        <h3 id="promotion-review-title">本次词典审查</h3>
        <p>
          <strong
            ><bdi>{{ review.dict.dictname ?? '（名称缺失）' }}</bdi></strong
          >
        </p>
        <p class="hint">
          词典 #{{ review.dict.id }} ·
          {{
            review.dict.ownerid === null ? '系统词典' : `个人词典 · 用户 #${review.dict.ownerid}`
          }}
          ·
          {{
            review.dict.deleted === 0
              ? '未删除'
              : review.dict.deleted === 1
                ? '已删除'
                : '状态待审查'
          }}
        </p>
        <dl class="operation-facts">
          <div>
            <dt>难度 D</dt>
            <dd>{{ review.dict.difficulty ?? '未记录' }}</dd>
          </div>
          <div>
            <dt>Perf 倍率 M</dt>
            <dd>×{{ review.dict.multiplier }}</dd>
          </div>
          <div>
            <dt>有效词条</dt>
            <dd>{{ review.word_count ?? '暂不可用' }}</dd>
          </div>
          <div>
            <dt>配置版本</dt>
            <dd>{{ review.dict.config_version }}</dd>
          </div>
        </dl>
        <p class="hint">
          以上为本次读取的词典信息，不是持续同步；默认难度1500不代表已标定。批准区间须另行明确填写，不从当前配置或申请人
          Rating 推导。
        </p>
        <RouterLink :to="`/admin/dicts/${review.dict.id}/`" target="_blank" rel="noopener"
          >查看词典内容（新标签页）</RouterLink
        >
      </section>
      <p
        v-if="review.application.state === 0 && !review.review_token"
        class="hint promotion-unavailable"
      >
        本次审查未提供有效通过令牌，不能批准；仍可按权限填写原因拒绝，不会自动重新审查。
      </p>
    </template>
    <div v-else-if="dictionary" class="operation-target">
      <p>
        <strong
          ><bdi>{{ dictionary.dictname ?? '（名称缺失）' }}</bdi></strong
        >
      </p>
      <p class="hint">
        词典 #{{ dictionary.id }} · 当前所有者 #{{ dictionary.ownerid ?? '未记录' }}
      </p>
      <dl class="operation-facts">
        <div>
          <dt>难度 D</dt>
          <dd>{{ dictionary.difficulty ?? '未记录' }}</dd>
        </div>
        <div>
          <dt>Perf 倍率 M</dt>
          <dd>{{ dictionary.multiplier ? `×${dictionary.multiplier}` : '未记录' }}</dd>
        </div>
      </dl>
      <p class="hint">仅当前所有者可提交申请，Lv.5 不可代他人申请；提交不等于已转为系统词典。</p>
    </div>
    <p v-else-if="!loading" class="hint">审查读取未成功，不开放审核决策；请关闭并核对记录。</p>
    <p class="hint">
      通过后词典归系统，原所有者不再凭所有权维护；由 Lv.3+
      维护。词条、难度、倍率和已有比赛快照不重写，也不自动改变已有比赛的 Rated / Unrated 模式。
    </p>
    <form
      v-if="!review || review.application.state === 0"
      class="promotion-decision"
      @submit.prevent="submit"
    >
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
            <div class="operation-fields">
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
            </div>
            <p class="hint">
              闭区间包含端点，必须由审核管理员明确填写，不自动采用默认范围。转为系统后的 Rated
              创建、报名、开局仍按最新范围与全员当前 Rating 检查，管理员无豁免。
            </p>
          </template>
        </template>
        <FormField
          id="promotion-reason"
          v-model="reason"
          :label="application ? '审核原因' : '申请原因'"
          required
          :maxlength="500"
        />
        <p v-if="application" class="hint">
          审核按本次读取的申请与词典审查提交；通过携带原审查令牌，拒绝只提交拒绝决定和原因。冲突或超时先核对记录，不自动取新令牌批准，也不生成另一个审批
          UUID。
        </p>
        <p v-else class="hint">
          原内容手动重试沿用本页原申请标识与版本；更改原因前先核对申请记录，不将新申请当作撤销旧申请。
        </p>
        <p class="hint">失败不会自动重发。超时或关闭不代表回滚，请先查看申请记录。</p>
        <p v-if="application && review" class="promotion-choice">
          拟定决策：<strong>{{ approve === 'true' ? '通过' : '拒绝' }}</strong
          >（提交前仍可修改）
        </p>
        <SubmitButton :pending="task.pending.value">{{
          application ? '确认审核' : '确认申请'
        }}</SubmitButton>
      </fieldset>
    </form>
    <div class="operation-actions">
      <button type="button" class="button" :disabled="task.pending.value" @click="emit('close')">
        关闭并核对记录
      </button>
    </div>
  </ModalDialog>
</template>

<style scoped>
.promotion-application {
  margin-bottom: 1.5rem;
}
.promotion-application h3 {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.promotion-decision {
  border-top: 1px solid var(--ui-line);
  padding-top: 1rem;
}
.promotion-decision label[for='promotion-decision'] {
  display: block;
  margin-bottom: 0.5rem;
}
#promotion-decision {
  width: 100%;
  min-height: 3rem;
  margin-bottom: 1rem;
  padding: 0.6rem;
  font: inherit;
  color: var(--ui-text);
  background: var(--ui-surface);
  border: 1px solid var(--ui-control-line);
  border-radius: var(--ui-radius-sm);
}
.promotion-unavailable {
  border-inline-start: 3px solid var(--ui-warning);
  padding-inline-start: 1rem;
}
.promotion-choice {
  background: var(--ui-surface-muted);
  padding: 0.75rem;
  border-radius: var(--ui-radius-sm);
}
</style>
