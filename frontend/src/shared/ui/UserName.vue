<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ name: string; rating?: number | null }>()
// Display policy only: use the server's current public Rating, never Perf,
// historical settlements, a role, or a guessed zero for missing data.
const band = computed(() => {
  const rating = props.rating
  if (rating == null || !Number.isFinite(rating)) return 'unknown'
  if (rating < 1200) return 'gray'
  if (rating < 1400) return 'green'
  if (rating < 1600) return 'cyan'
  if (rating < 1900) return 'blue'
  if (rating < 2100) return 'violet'
  if (rating < 2400) return 'orange'
  if (rating < 3000) return 'red'
  return 'legendary'
})
</script>

<template>
  <span
    class="user-name"
    :class="`user-name--${band}`"
    :title="band === 'unknown' ? '当前 Rating 缺失' : `当前 Rating：${rating}`"
    >{{ name }}</span
  >
</template>
