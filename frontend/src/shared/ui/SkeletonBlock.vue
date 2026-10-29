<script setup lang="ts">
// Decoration only: callers retain their own loading text/live region and decide
// when there is no accepted content. No rows, users, scores or interactive slots.
withDefaults(defineProps<{ variant?: 'lines' | 'table' | 'account' }>(), { variant: 'lines' })
</script>

<template>
  <div class="skeleton-block" :class="`skeleton-block--${variant}`" aria-hidden="true">
    <span v-for="line in 3" :key="line" class="skeleton-line" />
  </div>
</template>

<style scoped>
.skeleton-block {
  display: grid;
  gap: 0.5rem;
  min-width: 0;
  margin-block: 0.5rem 1rem;
}
.skeleton-line {
  display: block;
  height: 0.75rem;
  max-width: 100%;
  border: 1px solid transparent;
  border-radius: var(--ui-radius-sm);
  background: var(--ui-line);
}
.skeleton-line:first-child {
  width: 45%;
}
.skeleton-line:last-child {
  width: 70%;
}
.skeleton-block--table {
  gap: 0.75rem;
}
.skeleton-block--table .skeleton-line {
  width: 100%;
  height: 2rem;
}
.skeleton-block--account .skeleton-line {
  height: 0.5rem;
}
.skeleton-block--account .skeleton-line:first-child {
  height: 1.75rem;
}
/* Deliberately static, including prefers-reduced-motion: no shimmer, timers,
   fake progress or opacity animation. System colors keep the outline visible. */
@media (forced-colors: active) {
  .skeleton-line {
    background: Canvas;
    border-color: GrayText;
  }
}
</style>
