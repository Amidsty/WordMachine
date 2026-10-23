<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, useId } from 'vue'
defineProps<{ title: string; busy?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()
const titleId = useId()
let previousFocus: HTMLElement | null = null
onMounted(() => {
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  dialog.value?.showModal()
})
onBeforeUnmount(() => {
  dialog.value?.close()
  if (previousFocus?.isConnected) previousFocus.focus()
})
</script>

<template>
  <dialog
    ref="dialog"
    class="modal-dialog"
    :aria-labelledby="titleId"
    :aria-busy="busy"
    @cancel.prevent="!busy && emit('close')"
  >
    <header class="dialog-header">
      <h2 :id="titleId">{{ title }}</h2>
      <button
        type="button"
        class="button"
        aria-label="关闭对话框"
        :disabled="busy"
        @click="emit('close')"
      >
        关闭
      </button>
    </header>
    <slot />
  </dialog>
</template>
