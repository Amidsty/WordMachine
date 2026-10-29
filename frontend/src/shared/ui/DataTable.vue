<script setup lang="ts">
import ResourceFeedback from './ResourceFeedback.vue'

// The caller owns rows and their validity. Never cache rows here: resources may
// deliberately clear them on a new query, read failure or identity change.
withDefaults(defineProps<{ caption: string; loading: boolean; empty: boolean; error?: string }>(), {
  error: '',
})
</script>

<template>
  <ResourceFeedback :caption="caption" :loading="loading" :empty="empty" :error="error" />
  <!-- Independent of loading/error branches so background reads preserve DOM/focus. -->
  <div
    v-if="!empty"
    class="table-scroll"
    tabindex="0"
    role="region"
    :aria-label="caption"
    :aria-busy="loading"
  >
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
