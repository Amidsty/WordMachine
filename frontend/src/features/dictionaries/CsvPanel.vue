<script setup lang="ts">
import { onScopeDispose, ref } from 'vue'
import { useServices } from '../../app/services'
import { ApiError } from '../../shared/api/client'
import { useFormTask } from '../../shared/forms/useFormTask'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import DisclosurePanel from '../../shared/ui/DisclosurePanel.vue'
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
      signal.throwIfAborted()
      notice.value = `成功导入 ${result.count} 个单词。`
      content.value = ''
      emit('changed')
    } catch (error) {
      signal.throwIfAborted()
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
    signal.throwIfAborted()
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
      词典 #{{ dictId }} · 文件读取、导入请求与导出请求各自独立，没有自动上传或后台重试。
    </p>
    <NoticeBanner
      kind="warning"
      message="导出保留原文；不可信 CSV 应以文本列打开，避免电子表格执行公式。"
    />
    <NoticeBanner :message="exportTask.error.value" />
    <div v-if="notice" class="csv-import-result">
      <p class="hint">上次已确认的导入结果，不代表当前草稿已提交；词条列表以重新读取为准。</p>
      <NoticeBanner :message="notice" kind="success" />
    </div>
    <NoticeBanner :message="importTask.error.value" />
    <div v-if="lines.length" class="csv-errors">
      <p class="hint">
        以下为上次导入尝试返回的错误明细，不代表当前草稿已重新校验。最多50条，解析可能提前停止，不代表全部错误。行号是记录起始物理行，不是记录序号。
      </p>
      <ul aria-label="CSV 行错误">
        <li v-for="(error, index) in lines" :key="index">
          第 {{ error.line }} 行：{{ error.message }}
        </li>
      </ul>
    </div>
    <p v-if="reading || importTask.pending.value || exportTask.pending.value" class="hint">
      CSV 仍有文件读取或请求正在处理；收起不取消操作，离页也不代表服务端回滚。
    </p>
    <DisclosurePanel label="CSV 文件与文本操作" initially-open>
      <div class="csv-workspace" :class="{ 'csv-workspace--editable': canManage }">
        <section class="csv-export" aria-labelledby="csv-export-title">
          <h4 id="csv-export-title">导出全部词条</h4>
          <p>
            下载该词典全部有效词条，按服务端 ID
            顺序；不是当前搜索结果或当前页，也不是数据库全量备份。
          </p>
          <p class="hint">导出不受导入的字节/记录数上限截短。下载不会导入或修改词条。</p>
          <button
            type="button"
            class="button"
            :disabled="exportTask.pending.value"
            :aria-busy="exportTask.pending.value"
            @click="exportCsv"
          >
            导出全部 CSV
          </button>
        </section>
        <form
          v-if="canManage"
          class="import-form"
          aria-labelledby="csv-import-title"
          @submit.prevent="importCsv"
        >
          <h4 id="csv-import-title">导入词条</h4>
          <p class="hint">
            UTF-8，可含 BOM，无表头，两列依次为英文、中文；支持带引号的逗号和换行。
          </p>
          <dl class="csv-limits">
            <div>
              <dt>导入大小上限</dt>
              <dd>{{ limits.max_bytes }} 字节（{{ limits.max_bytes / 1024 }} KiB）</dd>
            </div>
            <div>
              <dt>导入记录上限</dt>
              <dd>{{ limits.max_rows }} 条非空 CSV 记录</dd>
            </div>
          </dl>
          <p class="hint">
            记录数不等于文本换行数；记录解析和整批是否写入以服务端为准。CSV
            校验发现错误时整批不写入，不会自动跳过错误项导入其余内容。
          </p>
          <fieldset :disabled="importTask.pending.value">
            <legend class="sr-only">CSV 导入</legend>
            <div class="csv-file-step">
              <label for="csv-file">读取 CSV 文件（读取后仍需确认导入）</label>
              <input
                id="csv-file"
                type="file"
                accept=".csv,text/csv"
                aria-describedby="csv-file-help"
                @change="selectFile"
              />
              <p id="csv-file-help" class="hint">
                可选：读取只在本地填入下方文本，不会自动导入。读取失败不会替换现有草稿，请核对文本，不要将旧草稿当作新文件内容。
              </p>
              <p v-if="reading" role="status">正在读取文件…</p>
            </div>
            <fieldset :disabled="reading">
              <legend class="sr-only">导入内容</legend>
              <FormField
                id="csv-content"
                v-model="content"
                label="CSV 文本"
                multiline
                required
                hint="可直接粘贴或编辑原文；提交前核对内容，本页不预估可导入条数。"
              />
              <p class="hint">
                导入没有持久成功回执。网络异常或响应损坏时结果可能未知，请先重新读取词条核对，不要直接重复导入；离开页面不代表服务器回滚。
              </p>
              <SubmitButton :pending="importTask.pending.value">导入 CSV</SubmitButton>
            </fieldset>
          </fieldset>
        </form>
      </div>
    </DisclosurePanel>
  </section>
</template>

<style scoped>
.csv-panel,
.csv-workspace > * {
  min-width: 0;
}
.csv-panel p,
.csv-panel dd,
.csv-panel li {
  overflow-wrap: anywhere;
}
.csv-workspace {
  display: grid;
  gap: 1.5rem;
  align-items: start;
}
.csv-export {
  padding: 1rem;
  background: var(--ui-surface-muted);
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-sm);
}
.csv-export h4,
.import-form h4 {
  margin-top: 0;
}
.import-form {
  margin: 0;
}
.csv-limits {
  display: grid;
  gap: 1rem;
}
.csv-limits dt {
  color: var(--ui-text-muted);
}
.csv-limits dd {
  margin: 0.25rem 0 0;
  font-variant-numeric: tabular-nums;
}
.csv-file-step {
  padding-block: 1rem;
  border-block: 1px solid var(--ui-line);
  margin-bottom: 1rem;
}
.csv-file-step label {
  display: block;
  margin-bottom: 0.5rem;
}
.csv-errors {
  border-inline-start: 3px solid var(--ui-negative);
  padding-inline-start: 1rem;
}
.csv-errors ul {
  padding-inline-start: 1.25rem;
}
.csv-panel :deep(textarea) {
  min-height: 12rem;
  font-family: var(--ui-font-mono);
}
@media (min-width: 1000px) {
  .csv-workspace--editable {
    grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
  }
  .csv-limits {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
