<script setup lang="ts">
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { useServices } from '../../app/services'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
const services = useServices()
const route = useRoute()
</script>

<template>
  <section class="workspace" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">管理中心</h1>
    <nav class="section-nav" aria-label="管理导航">
      <RouterLink to="/admin/">词典管理</RouterLink>
      <RouterLink to="/admin/dictionary-promotions/">系统词典申请</RouterLink>
      <RouterLink
        v-if="(services.client.session.value?.user?.admin_level ?? 0) > 0"
        to="/admin/users/"
        >用户管理</RouterLink
      >
    </nav>
    <NoticeBanner :message="route.query.denied === '1' ? '只有管理员可以管理用户。' : ''" />
    <RouterView />
  </section>
</template>
