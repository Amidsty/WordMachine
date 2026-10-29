<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { useServices } from '../../app/services'
import NoticeBanner from '../../shared/ui/NoticeBanner.vue'
const services = useServices()
const route = useRoute()
const dictionaryCurrent = computed(() => route.name === 'management' || route.name === 'dictionary')
</script>

<template>
  <section class="management-page" aria-labelledby="page-title">
    <h1 id="page-title" tabindex="-1">管理中心</h1>
    <nav class="section-nav" aria-label="管理导航">
      <RouterLink
        to="/admin/"
        active-class=""
        exact-active-class=""
        :class="{ 'is-current': dictionaryCurrent }"
        :aria-current="
          dictionaryCurrent ? (route.name === 'dictionary' ? 'location' : 'page') : undefined
        "
        >词典管理</RouterLink
      >
      <RouterLink to="/admin/dictionary-promotions/" active-class="" exact-active-class="is-current"
        >系统词典申请</RouterLink
      >
      <RouterLink
        v-if="(services.client.session.value?.user?.admin_level ?? 0) > 0"
        to="/admin/users/"
        active-class=""
        exact-active-class="is-current"
        >用户管理</RouterLink
      >
    </nav>
    <NoticeBanner :message="route.query.denied === '1' ? '只有管理员可以管理用户。' : ''" />
    <RouterView />
  </section>
</template>

<style scoped>
.management-page {
  min-width: 0;
}
.section-nav {
  margin-bottom: 1.5rem;
}
.section-nav .is-current {
  text-decoration: underline;
}
</style>
