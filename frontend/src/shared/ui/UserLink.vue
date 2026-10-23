<script setup lang="ts">
import { computed, inject } from 'vue'
import { RouterLink, routerKey } from 'vue-router'
import { servicesKey } from '../../app/services'
import UserName from './UserName.vue'
const props = defineProps<{ id?: number | null; name: string; rating?: number | null }>()
const services = inject(servicesKey, null)
const router = inject(routerKey, null)
const validId = computed(
  () => Number.isSafeInteger(props.id) && Number(props.id) > 0 && Number(props.id) <= 2147483647,
)
function open(event: MouseEvent, navigate?: (event: MouseEvent) => void) {
  // Preserve Ctrl/Meta/middle-click and anonymous SPA profile navigation.
  if (
    !services?.client.session.value?.user ||
    event.button !== 0 ||
    event.ctrlKey ||
    event.metaKey ||
    event.shiftKey ||
    event.altKey
  ) {
    navigate?.(event)
    return
  }
  event.preventDefault()
  services.userMenuTarget.value = props.id!
}
</script>

<template>
  <RouterLink v-if="validId && router" v-slot="{ href, navigate }" :to="`/user/${id}/`" custom>
    <a
      :href="href"
      :aria-haspopup="services?.client.session.value?.user ? 'dialog' : undefined"
      @click="open($event, navigate)"
      ><UserName :name="name" :rating="rating"
    /></a>
  </RouterLink>
  <a v-else-if="validId" :href="`/user/${id}/`" @click="open($event)"
    ><UserName :name="name" :rating="rating"
  /></a>
  <UserName v-else :name="name" :rating="rating" />
</template>
