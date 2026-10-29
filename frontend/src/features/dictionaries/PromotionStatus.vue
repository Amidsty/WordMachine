<script setup lang="ts">
import type { Promotion } from './promotions'
defineProps<{ state: Promotion['state'] }>()
const labels = ['待审核', '已通过', '已拒绝'] as const
</script>

<template>
  <span class="promotion-status" :class="`promotion-status--${state}`">{{ labels[state] }}</span>
</template>

<style scoped>
.promotion-status {
  display: inline-block;
  padding: 0.2rem 0.6rem;
  border: 1px solid currentColor;
  border-radius: var(--ui-radius-sm);
  white-space: nowrap;
  font-weight: 600;
}
.promotion-status--0 {
  color: var(--ui-warning);
  background: var(--ui-warning-soft);
}
.promotion-status--1 {
  color: var(--ui-positive);
  background: var(--ui-positive-soft);
}
.promotion-status--2 {
  color: var(--ui-text-muted);
  background: var(--ui-surface-muted);
}
</style>
