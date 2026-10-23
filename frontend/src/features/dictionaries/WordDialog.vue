<script setup lang="ts">
import { ref } from 'vue'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import type { Word } from './service'

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
  <ModalDialog :title="titles[mode]" :busy="task.pending.value" @close="emit('close')">
    <NoticeBanner :message="task.error.value" />
    <form @submit.prevent="submit">
      <fieldset :disabled="task.pending.value">
        <legend class="sr-only">{{ titles[mode] }}</legend>
        <p v-if="mode === 'delete'">确认删除单词“{{ word?.english ?? '内容缺失' }}”？</p>
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
        <div class="actions">
          <button type="button" class="button" @click="emit('close')">取消</button>
          <SubmitButton :pending="task.pending.value">{{
            mode === 'delete' ? '确认删除' : '保存单词'
          }}</SubmitButton>
        </div>
      </fieldset>
    </form>
  </ModalDialog>
</template>
