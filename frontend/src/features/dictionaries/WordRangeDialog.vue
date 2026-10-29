<script setup lang="ts">
import { ref, shallowRef } from 'vue'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import type { WordRangePreview } from './service'
import './dictionaryOperations.css'

const props = defineProps<{ dictId: number }>()
const emit = defineEmits<{ close: []; saved: [count: number] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const left = ref('1')
const right = ref('1')
const preview = shallowRef<WordRangePreview | null>(null)
const attempted = ref(false)
const validation = ref('')
const task = useFormTask()

function alive(signal: AbortSignal) {
  return !signal.aborted && services.client.session.value?.user?.id === actorId
}
async function run(operation: (signal: AbortSignal) => Promise<void>) {
  await task.run(async (parent) => {
    const controller = new AbortController()
    const abort = () => controller.abort()
    parent.addEventListener('abort', abort, { once: true })
    if (parent.aborted) abort()
    const timer = setTimeout(abort, 10000)
    try {
      await operation(controller.signal)
    } finally {
      clearTimeout(timer)
      parent.removeEventListener('abort', abort)
    }
  })
}
async function inspect() {
  if (!actorId || task.pending.value || preview.value) return
  const l = Number(left.value),
    r = Number(right.value)
  if (
    ![left.value, right.value].every((value) => /^[1-9]\d*$/.test(value)) ||
    !Number.isSafeInteger(l) ||
    !Number.isSafeInteger(r) ||
    l > r ||
    r > 2147483647
  ) {
    validation.value = '请输入从 1 开始的整数闭区间，满足 1 ≤ l ≤ r ≤ 2147483647。'
    return
  }
  validation.value = ''
  await run(async (signal) => {
    const data = await services.dictionaries.previewRange(props.dictId, l, r, actorId, signal)
    if (alive(signal) && data.dict_id === props.dictId) preview.value = Object.freeze(data)
  })
}
async function remove() {
  if (!actorId || !preview.value || preview.value.dict_id !== props.dictId) return
  const decision = preview.value
  await run(async (signal) => {
    attempted.value = true
    const result = await services.dictionaries.deleteRange(decision, actorId, signal)
    if (alive(signal) && decision.dict_id === props.dictId) emit('saved', result.deleted_count)
  })
}
function back() {
  if (task.pending.value) return
  preview.value = null
  attempted.value = false
  validation.value = task.error.value = ''
}
</script>

<template>
  <ModalDialog
    class="dictionary-operation"
    title="批量删除单词"
    :busy="task.pending.value"
    @close="emit('close')"
  >
    <p v-if="!preview" class="operation-target">词典 #{{ dictId }} · 选择全词表区间</p>
    <p class="hint">
      按整个词典中有效单词的 ID 升序计算序号，从 1
      开始，两端包含。不受搜索和分页影响，也不是填写数据库 ID。
    </p>
    <NoticeBanner :message="validation || task.error.value" />
    <form v-if="!preview" @submit.prevent="inspect">
      <fieldset :disabled="task.pending.value">
        <legend class="sr-only">选择删除区间</legend>
        <div class="operation-fields">
          <FormField id="range-left" v-model="left" label="起始序号 l" required :maxlength="10" />
          <FormField id="range-right" v-model="right" label="终止序号 r" required :maxlength="10" />
        </div>
        <p>这一步只生成预览，不会删除单词。</p>
        <button type="submit" class="button">预览删除范围</button>
      </fieldset>
    </form>
    <template v-else>
      <h3>请确认删除</h3>
      <p class="operation-target">
        词典：<bdi>{{ preview.dictname ?? '（未命名）' }}</bdi
        >（#{{ preview.dict_id }}），当前有效单词共 {{ preview.total }} 个（预览时读取）。
      </p>
      <p role="alert" class="operation-impact">
        <strong
          >将删除第 {{ preview.l }}～{{ preview.r }} 项，共
          {{ preview.count }} 个单词。此操作没有页面撤销入口，请核对后确认。</strong
        >
      </p>
      <p class="hint">
        确认有效期
        {{ preview.expires_in }} 秒，由服务端签发；此处不是倒计时，确认时仍由服务端校验是否过期。
      </p>
      <p class="hint">
        确认时词表或词典信息与预览不一致，必须重新预览。以下最多显示区间前五项及后五项。
      </p>
      <ol class="range-samples" aria-label="区间首尾样本">
        <li
          v-for="word in preview.words"
          :key="word.position"
          :value="word.position"
          class="multiline"
        >
          <bdi>{{ word.english ?? '（英文缺失）' }}</bdi> —
          <bdi>{{ word.chinese ?? '（中文缺失）' }}</bdi>
        </li>
      </ol>
      <p v-if="preview.count > preview.words.length">
        中间省略
        {{ preview.count - preview.words.length }} 项；确认将删除整个区间，并非仅删除预览样本。
      </p>
      <p>
        采用软删除，已有题目快照和历史记录不变；legacy_live
        旧式实时读词典的对局可能受影响，不会为旧局补造题目。
      </p>
      <p class="hint">
        签名确认令牌绑定本次审查，不是 UUID
        成功回执。内容变化、过期或已删除均可能使原确认被拒绝；拒绝不能证明上次未删除，不会自动生成新确认。
      </p>
    </template>
    <p class="hint">请求超过 10 秒未收到响应会停止等待，不代表回滚。不会自动重发。</p>
    <p class="hint">确认丢失时保留原预览，先核对结果再手动处理。重复提交不会删除后移的下一段。</p>
    <p v-if="attempted" class="hint">
      关闭或刷新会丢失本页确认信息；再次预览不代表上次删除被撤销。
    </p>
    <div v-if="preview" class="actions operation-actions">
      <button
        type="button"
        class="button operation-delete"
        :disabled="task.pending.value"
        :aria-busy="task.pending.value"
        @click="remove"
      >
        {{ attempted ? '重试原确认' : '确认删除区间' }}
      </button>
      <button type="button" class="button" :disabled="task.pending.value" @click="back">
        返回输入（不撤销已提交结果）
      </button>
    </div>
  </ModalDialog>
</template>
