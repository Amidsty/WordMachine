<script setup lang="ts">
// Selection belongs to the parent select. These option VNodes depend only on
// the data, not on each pointer/keyboard selection or pending-read flag.
defineProps<{ records: readonly { key: string; label: string }[] }>()
</script>

<template>
  <option v-for="record in records" :key="record.key" :value="record.key">
    {{ record.label }}
  </option>
</template>
