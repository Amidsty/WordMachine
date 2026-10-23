<script setup lang="ts">
defineProps<{ caption: string; loading: boolean; empty: boolean }>()
</script>

<template>
  <p v-if="loading" role="status">加载中…</p>
  <p v-else-if="empty" role="status">没有符合条件的记录。</p>
  <div v-else class="table-scroll" tabindex="0" role="region" :aria-label="caption">
    <table>
      <caption class="sr-only">
        {{
          caption
        }}
      </caption>
      <thead>
        <slot name="head" />
      </thead>
      <tbody>
        <slot />
      </tbody>
    </table>
  </div>
</template>
