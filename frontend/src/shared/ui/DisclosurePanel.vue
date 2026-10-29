<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(defineProps<{ label: string; initiallyOpen?: boolean }>(), {
  initiallyOpen: false,
})
// Initial state only. Refreshing parent props must not reset a user's choice.
const initialOpen = props.initiallyOpen
const details = ref<HTMLDetailsElement>()
const summary = ref<HTMLElement>()
function restoreHiddenFocus() {
  const node = details.value
  if (!node || node.open) return
  const active = document.activeElement
  if (active && active !== summary.value && node.contains(active)) summary.value?.focus()
}
function escape(event: KeyboardEvent) {
  if (!details.value?.open) return
  event.stopPropagation()
  details.value.open = false
  restoreHiddenFocus()
}
</script>

<template>
  <details
    ref="details"
    class="disclosure-panel"
    :open="initialOpen"
    @toggle="restoreHiddenFocus"
    @keydown.esc="escape"
  >
    <summary ref="summary">{{ label }}</summary>
    <!-- Deliberately kept mounted: drafts, pending writes and cleanup outlive visibility. -->
    <div class="disclosure-content"><slot /></div>
  </details>
</template>

<style scoped>
.disclosure-panel {
  min-width: 0;
}
summary {
  min-height: 44px;
  padding: 0.65rem 0.5rem;
  cursor: pointer;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.disclosure-content {
  min-width: 0;
  padding-block: 0.5rem;
}
</style>
