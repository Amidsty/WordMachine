<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <section class="form-panel" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">{{ title }}</h1>
    <p v-if="description" class="hint">{{ description }}</p>
    <slot />
  </section>
</template>
