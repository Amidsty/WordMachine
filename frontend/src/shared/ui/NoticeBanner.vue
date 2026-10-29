<script setup lang="ts">
// Warnings are persistent, polite status messages; errors retain alert semantics.
withDefaults(defineProps<{ message: string; kind?: 'error' | 'success' | 'info' | 'warning' }>(), {
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
