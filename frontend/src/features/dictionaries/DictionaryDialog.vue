<script setup lang="ts">
import { ref } from 'vue'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import type { Dictionary } from './service'

const props = defineProps<{
  mode: 'create' | 'rename' | 'delete' | 'multiplier' | 'rated-bounds' | 'difficulty'
  dictionary?: Dictionary
}>()
const emit = defineEmits<{ close: []; saved: [id?: number] }>()
const services = useServices()
const actorId = services.client.session.value?.user?.id
const name = ref(props.dictionary?.dictname ?? '')
const multiplier = ref(props.dictionary?.multiplier ?? '1.00')
const reason = ref('')
const difficulty = ref(String(props.dictionary?.difficulty ?? ''))
const ratedMin = ref(String(props.dictionary?.rated_min ?? ''))
const ratedMax = ref(String(props.dictionary?.rated_max ?? ''))
const task = useFormTask()
const titles = {
  create: '新建词典',
  rename: '重命名词典',
  delete: '删除词典',
  multiplier: '修改倍率',
  difficulty: '修改词典难度',
  'rated-bounds': '设置 Rated 区间',
}

async function submit() {
  if (!actorId) return
  if (['create', 'rename'].includes(props.mode) && !name.value.trim()) {
    task.error.value = '请输入词典名称。'
    return
  }
  if (
    ['create', 'multiplier'].includes(props.mode) &&
    (!/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?$/.test(multiplier.value.trim()) ||
      Number(multiplier.value) < 0.1 ||
      Number(multiplier.value) > 5)
  ) {
    task.error.value = '倍率需在 0.10–5.00 之间，最多两位小数。'
    return
  }
  if (props.mode === 'multiplier' && props.dictionary?.ownerid === null && !reason.value.trim()) {
    task.error.value = '修改系统词典倍率需填写原因。'
    return
  }
  if (
    props.mode === 'rated-bounds' &&
    (!/^-?(?:0|[1-9][0-9]*)$/.test(ratedMin.value) ||
      !/^-?(?:0|[1-9][0-9]*)$/.test(ratedMax.value) ||
      !Number.isSafeInteger(Number(ratedMin.value)) ||
      !Number.isSafeInteger(Number(ratedMax.value)) ||
      Number(ratedMin.value) < -2147483648 ||
      Number(ratedMax.value) > 2147483647 ||
      Number(ratedMin.value) > Number(ratedMax.value) ||
      !reason.value.trim())
  ) {
    task.error.value = '请填写有效整数区间 -2147483648 ≤ L ≤ R ≤ 2147483647 及修改原因。'
    return
  }
  if (
    props.mode === 'difficulty' &&
    (!/^(?:0|[1-9][0-9]*)$/.test(difficulty.value) ||
      Number(difficulty.value) > 4000 ||
      !reason.value.trim())
  ) {
    task.error.value = '难度需为 0–4000 的整数，并填写修改原因。'
    return
  }
  await task.run(async (signal) => {
    if (props.mode === 'create') {
      const result = await services.dictionaries.create(
        name.value.trim(),
        actorId,
        signal,
        multiplier.value.trim(),
      )
      emit('saved', result.dict_id)
    } else if (props.dictionary) {
      if (props.mode === 'difficulty') {
        if (props.dictionary.config_version === undefined) throw new Error('请刷新词典后重新审查。')
        await services.dictionaries.setDifficulty(
          props.dictionary.id,
          Number(difficulty.value),
          props.dictionary.config_version,
          reason.value.trim(),
          actorId,
          signal,
        )
      } else if (props.mode === 'rated-bounds') {
        if (props.dictionary.config_version === undefined) throw new Error('请刷新词典后重新审查。')
        await services.dictionaries.setRatedBounds(
          props.dictionary.id,
          Number(ratedMin.value),
          Number(ratedMax.value),
          props.dictionary.config_version,
          reason.value.trim(),
          actorId,
          signal,
        )
      } else if (props.mode === 'multiplier') {
        if (props.dictionary.config_version === undefined) throw new Error('请刷新词典后重新审查。')
        await services.dictionaries.setMultiplier(
          props.dictionary.id,
          multiplier.value.trim(),
          props.dictionary.config_version,
          reason.value.trim(),
          actorId,
          signal,
        )
      } else if (props.mode === 'rename')
        await services.dictionaries.rename(props.dictionary.id, name.value.trim(), actorId, signal)
      else await services.dictionaries.remove(props.dictionary.id, actorId, signal)
      emit('saved', props.dictionary.id)
    }
  })
}
</script>

<template>
  <ModalDialog :title="titles[mode]" :busy="task.pending.value" @close="emit('close')">
    <NoticeBanner :message="task.error.value" />
    <form @submit.prevent="submit">
      <fieldset :disabled="task.pending.value">
        <legend class="sr-only">{{ titles[mode] }}</legend>
        <template v-if="mode === 'delete'">
          <p>确认删除词典“{{ dictionary?.dictname ?? '名称缺失' }}”及其全部单词？</p>
          <p class="hint">
            此操作为软删除。新建对局已有题目快照；旧对局仍引用原词典，请先确认影响。
          </p>
        </template>
        <FormField
          v-else-if="mode === 'create' || mode === 'rename'"
          id="dict-name"
          v-model="name"
          label="词典名称"
          required
          :maxlength="255"
        />
        <template v-if="mode === 'create' || mode === 'multiplier'">
          <FormField
            id="dict-multiplier"
            v-model="multiplier"
            label="Perf 倍率"
            required
            :maxlength="16"
            hint="0.10–5.00，最多两位小数；v2线性缩放单题Perf增量，v1仅缩放证据权重；旧局按冻结版本计算。"
          />
          <FormField
            v-if="mode === 'multiplier'"
            id="multiplier-reason"
            v-model="reason"
            label="修改原因（系统词典必填）"
            :required="dictionary?.ownerid === null"
            :maxlength="500"
          />
          <p class="hint">
            仅影响之后创建的新对局，已创建的等待局和进行中对局不变；最终 Rating
            不再重复乘倍率。系统词典需 Lv.3 起维护。
          </p>
        </template>
        <template v-if="mode === 'difficulty'">
          <FormField
            id="dict-difficulty"
            v-model="difficulty"
            label="词典难度 D"
            required
            :maxlength="4"
          />
          <FormField
            id="difficulty-reason"
            v-model="reason"
            label="修改原因"
            required
            :maxlength="500"
          />
          <p class="hint">
            0–4000，默认1500不代表已经标定难度；与倍率及 Rated
            准入区间独立。仅影响之后创建的对局，等待局和运行局快照不变。个人所有者/Lv.5
            可修改，系统词典需 Lv.3+。失败不自动重发；超时请关闭后刷新核对。
          </p>
        </template>
        <template v-if="mode === 'rated-bounds'">
          <FormField
            id="rated-min"
            v-model="ratedMin"
            label="Rated 下界 L"
            required
            :maxlength="11"
          />
          <FormField
            id="rated-max"
            v-model="ratedMax"
            label="Rated 上界 R"
            required
            :maxlength="11"
          />
          <FormField
            id="rated-reason"
            v-model="reason"
            label="修改原因"
            required
            :maxlength="500"
          />
          <p class="hint">
            仅系统词典、Lv.3
            及以上可设置。闭区间包含端点，所有参赛者均须符合；等待局的加入和开局使用最新区间，已开局比赛不追溯。失败不自动重发。
          </p>
        </template>
        <div class="actions">
          <button type="button" class="button" @click="emit('close')">取消</button>
          <SubmitButton :pending="task.pending.value">{{
            mode === 'delete' ? '确认删除' : '保存词典'
          }}</SubmitButton>
        </div>
      </fieldset>
    </form>
  </ModalDialog>
</template>
