<script setup lang="ts">
import { ref } from 'vue'
import { useServices } from '../../app/services'
import { useFormTask } from '../../shared/forms/useFormTask'
import ModalDialog from '../../shared/ui/ModalDialog.vue'
import FormField from '../../shared/ui/FormField.vue'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SubmitButton from '../../shared/ui/SubmitButton.vue'
import type { Dictionary } from './service'
import './dictionaryOperations.css'

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
  <ModalDialog
    class="dictionary-operation"
    :title="titles[mode]"
    :busy="task.pending.value"
    @close="emit('close')"
  >
    <div v-if="dictionary" class="operation-target">
      <p>
        <strong
          ><bdi>{{ dictionary.dictname ?? '（名称缺失）' }}</bdi></strong
        >
      </p>
      <p class="hint">
        词典 #{{ dictionary.id }} ·
        {{ dictionary.ownerid === null ? '系统词典' : `个人词典 · 用户 #${dictionary.ownerid}` }}
      </p>
      <template v-if="['multiplier', 'difficulty', 'rated-bounds'].includes(mode)">
        <p class="hint">本次读取的配置 · 版本 {{ dictionary.config_version ?? '未记录' }}</p>
        <dl class="operation-facts">
          <div>
            <dt>难度 D</dt>
            <dd>{{ dictionary.difficulty ?? '未记录' }}</dd>
          </div>
          <div>
            <dt>Perf 倍率 M</dt>
            <dd>{{ dictionary.multiplier ? `×${dictionary.multiplier}` : '未记录' }}</dd>
          </div>
          <div>
            <dt>Rated 区间</dt>
            <dd>
              {{
                dictionary.ownerid === null
                  ? `[${dictionary.rated_min}, ${dictionary.rated_max}]（含端点）`
                  : '仅 Unrated'
              }}
            </dd>
          </div>
        </dl>
      </template>
    </div>
    <NoticeBanner :message="task.error.value" />
    <form @submit.prevent="submit">
      <fieldset :disabled="task.pending.value">
        <legend class="sr-only">{{ titles[mode] }}</legend>
        <div v-if="mode === 'delete'" class="operation-impact">
          <p><strong>确认删除此词典及其全部单词？</strong></p>
          <p>范围是整个词典，不是当前页或搜索命中项。采用软删除，但本页面没有撤销或恢复入口。</p>
          <p>已有题目快照和历史不会被重写；legacy_live 旧实时对局仍可能受词典删除影响。</p>
          <p>
            删除系统词典可能阻止已有等待 Rated
            局后续报名或开局，不能将“快照保留”理解为所有既有比赛不受影响。
          </p>
        </div>
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
          <div class="operation-fields">
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
          </div>
          <FormField
            id="rated-reason"
            v-model="reason"
            label="修改原因"
            required
            :maxlength="500"
          />
          <p class="hint">
            仅系统词典、Lv.3 及以上可设置。闭区间包含端点；创建、报名、开局按最新区间及全员当前
            Rating
            检查，管理员无准入豁免。新范围可能阻止等待局后续报名或开局；不追溯运行局/历史，也不自动转为
            Unrated。与创建时冻结的 D/M 不同，失败不自动重发。
          </p>
        </template>
        <p v-if="['multiplier', 'difficulty', 'rated-bounds'].includes(mode)" class="hint">
          按本次读取的配置版本提交；配置冲突后需关闭并重新读取、核对，不自动套用新版本重发。关闭不代表撤销已发送的修改。
        </p>
        <p v-else class="hint">
          此操作没有持久成功回执。网络异常或响应损坏时结果可能未知，请关闭后重新读取核对；再次提交不保证幂等，关闭也不代表撤销服务器操作。
        </p>
        <div class="actions operation-actions">
          <button type="button" class="button" @click="emit('close')">取消</button>
          <SubmitButton
            :pending="task.pending.value"
            :class="{ 'operation-delete': mode === 'delete' }"
            >{{ mode === 'delete' ? '确认删除' : '保存词典' }}</SubmitButton
          >
        </div>
      </fieldset>
    </form>
  </ModalDialog>
</template>
