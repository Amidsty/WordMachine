<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useServices } from '../../app/services'
import { useAutoRefresh } from '../../app/useAutoRefresh'
import { useFormTask } from '../../shared/forms/useFormTask'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
import SkeletonBlock from '../../shared/ui/SkeletonBlock.vue'
import { storedNumber, storedPerf } from '../games/presentation'
import { localHistoryTime } from './historyTime'
import ScoreChartRecordOptions from './ScoreChartRecordOptions.vue'
import {
  axisNumber,
  chartPoints,
  createHoverIndex,
  geometry,
  nearestHoverKey,
  kindLabels,
  sameScorePoints,
  type ChartMode,
  type ScorePoint,
} from './scoreChart'

const props = defineProps<{ uid: number }>()
const services = useServices()
const task = useFormTask()
const points = shallowRef<ScorePoint[] | null>(null)
const mode = ref<ChartMode>('rated')
const selectedKey = ref('')
const canvas = ref<HTMLElement>()
const width = ref(720)
let observer: ResizeObserver | undefined
const visible = computed(() => chartPoints(points.value ?? [], mode.value))
const undated = computed(() => visible.value.filter((point) => point.recorded_at === null))
const graph = computed(() => geometry(visible.value, width.value))
const hoverIndex = computed(() => createHoverIndex(graph.value.nodes))
let hoverFrame: number | undefined
let hoverPosition: { svg: SVGSVGElement; x: number; y: number } | undefined
function cancelHover() {
  if (hoverFrame !== undefined) cancelAnimationFrame(hoverFrame)
  hoverFrame = undefined
  hoverPosition = undefined
}
function selectPoint(key: string) {
  cancelHover()
  selectedKey.value = key
}
function hover(event: PointerEvent) {
  // Do not turn touch scrolling into selection or prevent its default action.
  if (event.pointerType === 'touch') return
  hoverPosition = { svg: event.currentTarget as SVGSVGElement, x: event.clientX, y: event.clientY }
  if (hoverFrame !== undefined) return
  hoverFrame = requestAnimationFrame(() => {
    hoverFrame = undefined
    const position = hoverPosition
    hoverPosition = undefined
    if (!position?.svg.isConnected) return
    const matrix = position.svg.getScreenCTM()
    if (!matrix || matrix.a * matrix.d - matrix.b * matrix.c === 0) return
    // Invert the SVG transform, including scaling, scrolling and letterboxing.
    const pointer = new DOMPoint(position.x, position.y).matrixTransform(matrix.inverse())
    const plot = graph.value
    if (
      pointer.x < plot.left ||
      pointer.x > plot.right ||
      pointer.y < plot.top ||
      pointer.y > plot.bottom
    )
      return
    const key = nearestHoverKey(hoverIndex.value, pointer.x, pointer.y)
    if (key !== undefined) selectedKey.value = key
  })
}
watch([visible, width], cancelHover, { flush: 'sync' })
const records = computed(() =>
  visible.value.map((point, index) => {
    const time = localHistoryTime(point.recorded_at)
    return {
      key: point.key,
      point,
      index,
      time,
      label: `${index + 1} · ${time.text} · ${kindLabels[point.kind]}${point.game_id === null ? '' : ` #${point.game_id}`}`,
    }
  }),
)
const recordIndex = computed(() => new Map(records.value.map((record) => [record.key, record])))
const nodeIndex = computed(() => new Map(graph.value.nodes.map((node) => [node.point.key, node])))
const selectedRecord = computed(() => recordIndex.value.get(selectedKey.value))
const selected = computed(() => selectedRecord.value?.point)
const selectedNode = computed(() => nodeIndex.value.get(selectedKey.value))
const selectedIndex = computed(() => selectedRecord.value?.index ?? -1)
const plotted = computed(() =>
  graph.value.nodes.some((node) => node.ratingY !== null || node.perfY !== null),
)
const titleId = computed(() => `score-chart-title-${props.uid}`)
const modeId = computed(() => `score-chart-mode-${props.uid}`)
const detailId = computed(() => `score-chart-detail-${props.uid}`)
watch(visible, (rows) => {
  if (!rows.some((row) => row.key === selectedKey.value)) selectedKey.value = rows.at(-1)?.key ?? ''
})
async function load() {
  await task.run(async (signal) => {
    try {
      const result = await services.history.timeline(props.uid, signal)
      if (!signal.aborted && !sameScorePoints(points.value, result.points))
        points.value = result.points
    } catch (cause) {
      if (!signal.aborted) points.value = null
      throw cause
    }
  })
}
onMounted(() => {
  void load()
  if (typeof ResizeObserver !== 'undefined' && canvas.value) {
    observer = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.width > 0)
        width.value = Math.max(240, Math.round(entry.contentRect.width))
    })
    observer.observe(canvas.value)
  }
})
onScopeDispose(() => {
  cancelHover()
  observer?.disconnect()
})
useAutoRefresh(load)
watch(services.userChanges, load)
function move(step: number) {
  selectPoint(
    visible.value[Math.max(0, Math.min(visible.value.length - 1, selectedIndex.value + step))]
      ?.key ?? '',
  )
}
function keyboard(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  cancelHover()
  if (event.key === 'Home') selectedKey.value = visible.value[0]?.key ?? ''
  else if (event.key === 'End') selectedKey.value = visible.value.at(-1)?.key ?? ''
  else move(event.key === 'ArrowLeft' ? -1 : 1)
}
function timeTick(value: number) {
  const ticks = graph.value.timeTicks
  const sameDay =
    ticks.length > 1 &&
    new Date(ticks[0]!.value).toDateString() === new Date(ticks[1]!.value).toDateString()
  return new Intl.DateTimeFormat(
    undefined,
    sameDay
      ? { hour: '2-digit', minute: '2-digit', second: '2-digit' }
      : { year: 'numeric', month: '2-digit', day: '2-digit' },
  ).format(value)
}
function perfText(point: ScorePoint) {
  return point.perf_missing === 'not_applicable'
    ? '不适用'
    : point.perf_missing === 'no_answers'
      ? '未作答'
      : storedPerf(point.perf)
}
</script>

<template>
  <section class="score-chart" :aria-labelledby="titleId">
    <div class="chart-heading">
      <h2 :id="titleId">Rating / Perf 变化</h2>
      <div class="chart-mode">
        <label :for="modeId">对局范围</label>
        <select :id="modeId" v-model="mode">
          <option value="rated">Rated</option>
          <option value="all">Rated + Unrated</option>
        </select>
      </div>
    </div>
    <p class="hint">
      全部历史 · 人工调分始终显示 · 时间按浏览器本地时区。Unrated 的 Rating 沿用此前可确认的值。
    </p>
    <div class="chart-legend" aria-label="图例">
      <span><i class="line-key rating-line" aria-hidden="true"></i>Rating</span>
      <span><i class="line-key perf-line" aria-hidden="true"></i>Perf</span>
      <span><i class="marker-key rated" aria-hidden="true"></i>Rated</span>
      <span><i class="marker-key unrated" aria-hidden="true"></i>Unrated</span>
      <span><i class="marker-key manual" aria-hidden="true"></i>人工调分</span>
    </div>
    <NoticeBanner :message="task.error.value" />
    <p v-if="task.pending.value && points === null" role="status">正在读取完整评分历史…</p>
    <SkeletonBlock v-if="task.pending.value && points === null" />
    <button
      v-if="task.error.value"
      type="button"
      class="button"
      :disabled="task.pending.value"
      @click="load"
    >
      重试读取走势图
    </button>
    <div ref="canvas" class="chart-canvas">
      <template v-if="points !== null">
        <p class="hint">
          当前范围共 {{ visible.length }} 条记录，其中 {{ undated.length }} 条时间未记录。
        </p>
        <svg
          v-if="plotted"
          class="score-plot"
          :viewBox="`0 0 ${width} 326`"
          role="img"
          tabindex="0"
          :aria-labelledby="titleId"
          :aria-describedby="detailId"
          @keydown="keyboard"
          @pointermove="hover"
          @pointerleave="cancelHover"
          @pointercancel="cancelHover"
        >
          <desc>
            横轴为时间，纵轴为分数。Rating 为蓝色实线，Perf
            为紫色虚线。在绘图区横向移动可查看最近记录，也可点击节点，或用左右方向键、Home、End及下方记录选择框浏览。
          </desc>
          <!-- The complete static plot is reused on selection-only updates. -->
          <g v-memo="[graph]" aria-hidden="true">
            <rect
              v-for="(band, index) in graph.bands"
              :key="index"
              :x="graph.left"
              :y="band.y"
              :width="graph.right - graph.left"
              :height="band.height"
              :fill="band.color"
            />
            <g v-for="(tick, index) in graph.ticks" :key="index">
              <line
                :x1="graph.left"
                :x2="graph.right"
                :y1="tick.y"
                :y2="tick.y"
                class="chart-grid"
              />
              <text :x="graph.left - 8" :y="tick.y + 4" text-anchor="end">
                {{ axisNumber(tick.value) }}
              </text>
            </g>
            <line
              :x1="graph.left"
              :x2="graph.left"
              :y1="graph.top"
              :y2="graph.bottom"
              class="chart-axis"
            />
            <line
              :x1="graph.left"
              :x2="graph.right"
              :y1="graph.bottom"
              :y2="graph.bottom"
              class="chart-axis"
            />
            <text
              v-for="(tick, index) in graph.timeTicks"
              :key="index"
              :x="tick.x"
              :y="graph.bottom + 24"
              :text-anchor="graph.timeTicks.length === 1 ? 'middle' : index === 0 ? 'start' : 'end'"
            >
              {{ timeTick(tick.value) }}
            </text>
            <path :d="graph.ratingPath" class="rating-path" data-series="rating" />
            <path :d="graph.perfPath" class="perf-path" data-series="perf" />
            <g
              v-for="node in graph.nodes"
              :key="node.point.key"
              :data-point="node.point.key"
              :class="['chart-point', node.point.kind]"
              @pointerenter="selectPoint(node.point.key)"
              @click="selectPoint(node.point.key)"
            >
              <template v-for="series in ['ratingY', 'perfY'] as const" :key="series">
                <g
                  v-if="node[series] !== null"
                  :data-series="series === 'ratingY' ? 'rating' : 'perf'"
                  :transform="`translate(${node.x} ${node[series]})`"
                >
                  <circle r="11" class="point-hit" />
                  <path
                    v-if="node.point.kind === 'manual'"
                    d="M0,-6 L6,0 L0,6 L-6,0 Z"
                    class="point-mark"
                  />
                  <circle v-else r="4.5" class="point-mark" />
                </g>
              </template>
            </g>
          </g>
          <g
            v-if="selectedNode"
            class="chart-highlight"
            :class="selectedNode.point.kind"
            aria-hidden="true"
          >
            <line
              :x1="selectedNode.x"
              :x2="selectedNode.x"
              :y1="graph.top"
              :y2="graph.bottom"
              class="chart-selection"
            />
            <template v-for="series in ['ratingY', 'perfY'] as const" :key="series">
              <g
                v-if="selectedNode[series] !== null"
                :transform="`translate(${selectedNode.x} ${selectedNode[series]})`"
              >
                <path
                  v-if="selectedNode.point.kind === 'manual'"
                  d="M0,-6 L6,0 L0,6 L-6,0 Z"
                  class="point-mark"
                />
                <circle v-else r="4.5" class="point-mark" />
              </g>
            </template>
          </g>
        </svg>
        <p v-else class="chart-empty">当前范围暂无可定位到时间轴的有效分数。</p>
        <template v-if="visible.length">
          <div class="chart-controls">
            <label :for="`score-chart-record-${uid}`">历史记录</label>
            <select :id="`score-chart-record-${uid}`" v-model="selectedKey" @change="cancelHover">
              <ScoreChartRecordOptions :records="records" />
            </select>
            <button type="button" class="button" :disabled="selectedIndex <= 0" @click="move(-1)">
              上一条
            </button>
            <button
              type="button"
              class="button"
              :disabled="selectedIndex >= visible.length - 1"
              @click="move(1)"
            >
              下一条
            </button>
          </div>
          <div v-if="selected" :id="detailId" class="chart-detail">
            <strong>{{ kindLabels[selected.kind] }}</strong>
            <span>{{ selectedRecord?.time.text }}</span>
            <RouterLink
              v-if="selected.game_available && selected.game_id !== null"
              :to="`/game/${selected.game_id}/detail/`"
              ><bdi>{{ selected.game_name ?? '对局' }}</bdi> #{{ selected.game_id }}</RouterLink
            >
            <span v-else-if="selected.game_id !== null"
              >对局 #{{ selected.game_id }}（记录不可用）</span
            >
            <span data-value="rating"
              >Rating：{{ storedNumber(selected.rating)
              }}<small v-if="selected.rating_origin === 'carried'">（保持不变）</small
              ><small v-else-if="selected.rating_origin === 'unknown'"
                >（无法确认历史余额）</small
              ></span
            >
            <span
              data-value="perf"
              :title="selected.perf === null ? undefined : String(selected.perf)"
              >Perf：{{ perfText(selected) }}</span
            >
          </div>
        </template>
        <details v-if="undated.length" class="undated-records">
          <summary>时间未记录：{{ undated.length }} 条（完整保留，不伪造日期）</summary>
          <p class="hint">
            这些记录无法定位到时间轴，可在上方记录选择框查看详情。以下顺序不代表它们与有日期记录之间的时间先后。
          </p>
          <div class="table-scroll" role="region" aria-label="时间未记录的评分历史" tabindex="0">
            <table>
              <caption>
                时间未记录的全部历史
              </caption>
              <thead>
                <tr>
                  <th scope="col">来源</th>
                  <th scope="col">Rating</th>
                  <th scope="col">Perf</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="point in undated" :key="point.key">
                  <td>
                    {{ kindLabels[point.kind]
                    }}<span v-if="point.game_id !== null"> #{{ point.game_id }}</span>
                  </td>
                  <td>{{ storedNumber(point.rating) }}</td>
                  <td>{{ perfText(point) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>
      </template>
    </div>
  </section>
</template>

<style scoped>
.score-chart {
  min-width: 0;
  margin-top: 1.5rem;
  padding: 1rem;
  border: 1px solid var(--ui-line);
  border-radius: var(--ui-radius-md);
  background: var(--ui-surface);
}
.chart-heading,
.chart-mode,
.chart-legend,
.chart-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.65rem;
}
.chart-heading {
  justify-content: space-between;
}
h2 {
  margin: 0;
}
.chart-mode select {
  width: auto;
}
.chart-legend {
  margin-block: 1rem;
  font-size: 0.875rem;
}
.chart-legend > span {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}
.line-key {
  width: 1.4rem;
  border-top: 2px solid;
}
.rating-line {
  color: #2854d7;
}
.perf-line {
  color: #873f91;
  border-top-style: dashed;
}
.marker-key {
  display: inline-block;
  width: 0.65rem;
  height: 0.65rem;
  border: 2px solid;
  border-radius: 50%;
  background: white;
}
.rated {
  --marker: #bc9000;
  color: #bc9000;
}
.unrated {
  --marker: #737373;
  color: #737373;
}
.manual {
  --marker: #2854d7;
  color: #2854d7;
}
.marker-key.manual {
  border-radius: 0;
  transform: rotate(45deg);
}
.chart-canvas {
  min-width: 0;
}
.score-plot {
  display: block;
  width: 100%;
  height: auto;
  min-height: 260px;
  touch-action: pan-y;
}
.score-plot text {
  font-size: 12px;
  fill: var(--ui-text);
  font-variant-numeric: tabular-nums;
}
.chart-grid {
  stroke: #637083;
  stroke-opacity: 0.2;
}
.chart-axis {
  stroke: #637083;
}
.rating-path,
.perf-path {
  fill: none;
  stroke-width: 2;
  stroke-linejoin: round;
}
.rating-path {
  stroke: #2854d7;
}
.perf-path {
  stroke: #873f91;
  stroke-dasharray: 6 3;
}
.chart-selection {
  stroke: #526178;
  stroke-dasharray: 3 3;
}
.point-mark {
  fill: white;
  stroke: var(--marker);
  stroke-width: 2.5;
}
.point-hit {
  fill: transparent;
  stroke: none;
  cursor: pointer;
}
.chart-highlight {
  pointer-events: none;
}
.chart-highlight .point-mark {
  stroke-width: 3.5;
}
.chart-controls {
  margin-top: 0.5rem;
}
.chart-controls select {
  flex: 1 1 16rem;
  min-width: 0;
  max-width: 100%;
}
.chart-detail {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  min-height: 4rem;
  padding: 0.8rem;
  margin-block: 0.75rem;
  background: var(--ui-surface-muted);
  border-left: 3px solid var(--ui-primary);
  overflow-wrap: anywhere;
}
.chart-detail span[data-value] {
  font-variant-numeric: tabular-nums;
}
.undated-records summary {
  cursor: pointer;
  padding-block: 0.7rem;
}
.undated-records th,
.undated-records td {
  text-align: center;
  white-space: nowrap;
}
@media (forced-colors: active) {
  .point-mark,
  .chart-axis,
  .rating-path,
  .perf-path,
  .chart-selection {
    stroke: CanvasText;
  }
  .point-mark {
    fill: Canvas;
  }
}
</style>
