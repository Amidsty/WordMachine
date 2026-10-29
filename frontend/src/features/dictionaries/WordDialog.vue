<script setup lang="ts">
import { ref } from 'vue'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import type { Word } from './service'
import './dictionaryOperations.css'

const props = defineProps<{ dictId: number; mode: 'create' | 'edit' | 'delete'; word?: Word }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const english = ref(props.word?.english ?? '')
const chinese = ref(props.word?.chinese ?? '')
const task = useFormTask()
const titles = { create: '新增单词', edit: '编辑单词', delete: '删除单词' }
async function submit() {
  if (!actorId) return
  if (props.mode !== 'create' && !props.word) {
    task.error.value = '未选择单词，请关闭后重试。'
    return
  }
  if (props.mode !== 'delete' && (!english.value.trim() || !chinese.value.trim())) {
    task.error.value = '英文和中文不能为空。'
    return
  }
  await task.run(async (signal) => {
    if (props.mode === 'delete' && props.word)
      await services.dictionaries.removeWord(props.word.id, actorId, signal)
    else
      await services.dictionaries.saveWord(
        props.dictId,
        props.word?.id ?? null,
        { english: english.value.trim(), chinese: chinese.value.trim() },
        actorId,
        signal,
      )
    emit('saved')
  })
}
</script>

<template>
  <ModalDialog
    class="dictionary-operation"
    :title="titles[mode]"
    :busy="task.pending.value"
    @close="emit('close')"
  >
    <p class="operation-target">
      词典 #{{ word?.dictid ?? dictId }}<template v-if="word"> · 词条 #{{ word.id }}</template
      ><template v-else> · 新增词条</template>
    </p>
    <NoticeBanner :message="task.error.value" />
    <form @submit.prevent="submit">
      <fieldset :disabled="task.pending.value">
        <legend class="sr-only">{{ titles[mode] }}</legend>
        <div v-if="mode === 'delete'">
          <dl class="operation-facts">
            <div>
              <dt>英文</dt>
              <dd class="multiline">
                <bdi>{{ word?.english ?? '（英文缺失）' }}</bdi>
              </dd>
            </div>
            <div>
              <dt>中文</dt>
              <dd class="multiline">
                <bdi>{{ word?.chinese ?? '（中文缺失）' }}</bdi>
              </dd>
            </div>
          </dl>
          <div class="operation-impact">
            <p>
              <strong>确认删除这一条单词？</strong>按上述词条 ID
              删除，不删除其他同名词条、当前页或整个词典。
            </p>
            <p>
              采用软删除，本页面没有撤销入口。已有题目快照和历史不变；legacy_live
              旧实时对局可能受影响，不会为旧局补造题目。
            </p>
          </div>
        </div>
        <template v-else>
          <FormField id="word-english" v-model="english" label="英文" required :maxlength="255" />
          <FormField
            id="word-chinese"
            v-model="chinese"
            label="中文"
            multiline
            required
            :maxlength="255"
          />
        </template>
        <p class="hint">
          此操作没有持久成功回执。网络异常或响应损坏时结果可能未知，请关闭后重新读取核对；不自动重发，关闭不代表撤销服务器操作。
        </p>
        <div class="actions operation-actions">
          <button type="button" class="button" @click="emit('close')">取消</button>
          <SubmitButton
            :pending="task.pending.value"
            :class="{ 'operation-delete': mode === 'delete' }"
            >{{ mode === 'delete' ? '确认删除' : '保存单词' }}</SubmitButton
          >
        </div>
      </fieldset>
    </form>
  </ModalDialog>
</template>
