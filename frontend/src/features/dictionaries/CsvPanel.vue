<script setup lang="ts">
import { onScopeDispose, ref } from 'vue'
import { useServices } from '../../app/services'
import { ApiError } from '../../shared/api/client'
import { useFormTask } from '../../shared/forms/useFormTask'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import { csvErrorsSchema, type CsvLimits } from './service'

const props = defineProps<{ dictId: number; canManage: boolean; limits: CsvLimits }>()
const emit = defineEmits<{ changed: [] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const content = ref('')
const notice = ref('')
const lines = ref<{ line: number; message: string }[]>([])
const reading = ref(false)
const importTask = useFormTask()
const exportTask = useFormTask()
let fileRevision = 0
onScopeDispose(() => {
  fileRevision++
})

async function selectFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const revision = ++fileRevision
  importTask.error.value = ''
  if (file.size > props.limits.max_bytes) {
    reading.value = false
    importTask.error.value = 'CSV 文件超过服务器大小限制。'
    return
  }
  reading.value = true
  try {
    const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
    if (revision === fileRevision) content.value = text
  } catch {
    if (revision === fileRevision) importTask.error.value = '无法读取文件，请确认文件为有效 UTF-8。'
  } finally {
    if (revision === fileRevision) reading.value = false
  }
}

async function importCsv() {
  if (!props.canManage || !actorId || reading.value) return
  notice.value = ''
  lines.value = []
  if (new TextEncoder().encode(content.value).length > props.limits.max_bytes) {
    importTask.error.value = 'CSV 文本超过服务器大小限制。'
    return
  }
  await importTask.run(async (signal) => {
    try {
      const result = await services.dictionaries.importCsv(
        props.dictId,
        content.value,
        actorId,
        signal,
      )
      notice.value = `成功导入 ${result.count} 个单词。`
      content.value = ''
      emit('changed')
    } catch (error) {
      if (error instanceof ApiError) {
        const details = csvErrorsSchema.safeParse(error.details)
        if (details.success) lines.value = details.data.errors
      }
      throw error
    }
  })
}

async function exportCsv() {
  await exportTask.run(async (signal) => {
    const result = await services.dictionaries.exportCsv(props.dictId, signal)
    const url = URL.createObjectURL(new Blob([result.content], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = result.filename
    document.body.append(link)
    try {
      link.click()
    } finally {
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    }
  })
}
</script>

<template>
  <section class="csv-panel" aria-labelledby="csv-title">
    <h3 id="csv-title">CSV 导入 / 导出</h3>
    <p class="hint">
      UTF-8，可含 BOM，无表头，两列为英文、中文；支持带引号的逗号和换行。 导入上限
      {{ limits.max_bytes / 1024 }} KiB、{{ limits.max_rows }} 条，任一行错误则整批不写入。
    </p>
    <p class="hint">导出保留原文；不可信 CSV 应以文本列打开，避免电子表格执行公式。</p>
    <NoticeBanner :message="notice" kind="success" />
    <NoticeBanner :message="exportTask.error.value" />
    <button type="button" class="button" :disabled="exportTask.pending.value" @click="exportCsv">
      导出全部 CSV
    </button>
    <form v-if="canManage" class="import-form" @submit.prevent="importCsv">
      <NoticeBanner :message="importTask.error.value" />
      <ul v-if="lines.length" aria-label="CSV 行错误">
        <li v-for="(error, index) in lines" :key="index">
          第 {{ error.line }} 行：{{ error.message }}
        </li>
      </ul>
      <fieldset :disabled="importTask.pending.value">
        <legend class="sr-only">CSV 导入</legend>
        <label for="csv-file">读取 CSV 文件（读取后仍需确认导入）</label>
        <input id="csv-file" type="file" accept=".csv,text/csv" @change="selectFile" />
        <p v-if="reading" role="status">正在读取文件…</p>
        <fieldset :disabled="reading">
          <legend class="sr-only">导入内容</legend>
          <FormField id="csv-content" v-model="content" label="CSV 文本" multiline required />
          <SubmitButton :pending="importTask.pending.value">导入 CSV</SubmitButton>
        </fieldset>
      </fieldset>
    </form>
  </section>
</template>
