<script setup lang="ts">
import NoticeBanner from './NoticeBanner.vue'
import SkeletonBlock from './SkeletonBlock.vue'

// Presentation only: callers own rows, validity, refresh and identity cleanup.
withDefaults(defineProps<{ caption: string; loading: boolean; empty: boolean; error?: string }>(), {
  error: '',
})
</script>

<template>
  <NoticeBanner :message="error" />
  <p v-if="loading" class="hint table-status" role="status">
    {{ empty ? `${caption}加载中…` : `${caption}正在刷新，当前显示上次读取的记录。` }}
  </p>
  <p v-else-if="error && !empty" class="hint">本次读取失败，当前显示上次读取的记录。</p>
  <p v-else-if="!error && empty" class="hint table-status" role="status">没有符合条件的记录。</p>
  <SkeletonBlock v-if="loading && empty && !error" variant="table" />
</template>
