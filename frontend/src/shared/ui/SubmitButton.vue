<script setup lang="ts">
defineProps<{ pending: boolean }>()
</script>

<template>
  <button type="submit" class="button button-primary" :disabled="pending" :aria-busy="pending">
    <template v-if="pending">提交中…</template>
    <slot v-else />
  </button>
</template>
