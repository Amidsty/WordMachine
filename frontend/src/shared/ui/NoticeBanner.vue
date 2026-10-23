<script setup lang="ts">
withDefaults(defineProps<{ message: string; kind?: 'error' | 'success' | 'info' }>(), {
  kind: 'error',
})
</script>

<template>
  <p
    v-if="message"
    :class="['notice', `notice-${kind}`]"
    :role="kind === 'error' ? 'alert' : 'status'"
  >
    {{ message }}
  </p>
</template>
