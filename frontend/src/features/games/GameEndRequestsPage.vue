<script setup lang="ts">
import GameEndRequests from './GameEndRequests.vue'
</script>
<template>
  <section class="end-requests-page" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">比赛结束请求</h1>
    <p class="hint">私有留言收件箱 · 没有未读计数或自动结束规则</p>
    <GameEndRequests />
  </section>
</template>
<style scoped>
.end-requests-page {
  min-width: 0;
}
</style>
