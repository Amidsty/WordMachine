<script setup lang="ts">
import type { Pagination } from '../api/pagination'
defineProps<{ pagination: Pagination; busy?: boolean; label: string }>()
defineEmits<{ page: [value: number] }>()
</script>

<template>
  <nav class="pagination" :aria-label="label">
    <button
      type="button"
      class="button"
      :disabled="busy || pagination.page <= 1"
      @click="$emit('page', pagination.page - 1)"
    >
      上一页
    </button>
    <span>第 {{ pagination.page }} / {{ pagination.pages }} 页，共 {{ pagination.total }} 条</span>
    <button
      type="button"
      class="button"
      :disabled="busy || pagination.page >= pagination.pages"
      @click="$emit('page', pagination.page + 1)"
    >
      下一页
    </button>
  </nav>
</template>
