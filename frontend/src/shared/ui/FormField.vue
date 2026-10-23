<script setup lang="ts">
defineProps<{
  id: string
  label: string
  type?: 'text' | 'password'
  multiline?: boolean
  required?: boolean
  autocomplete?: string
  maxlength?: number
  minlength?: number
  hint?: string
  error?: string
}>()
const model = defineModel<string>({ default: '' })
</script>

<template>
  <div class="form-field">
    <label :for="id">{{ label }}</label>
    <textarea
      v-if="multiline"
      :id="id"
      v-model="model"
      :name="id"
      :required="required"
      :maxlength="maxlength"
      :aria-invalid="!!error"
      :aria-describedby="error ? `${id}-error` : hint ? `${id}-hint` : undefined"
      rows="4"
    />
    <input
      v-else
      :id="id"
      v-model="model"
      :name="id"
      :type="type ?? 'text'"
      :required="required"
      :autocomplete="autocomplete"
      :minlength="minlength"
      :maxlength="maxlength"
      :aria-invalid="!!error"
      :aria-describedby="error ? `${id}-error` : hint ? `${id}-hint` : undefined"
    />
    <p v-if="error" :id="`${id}-error`" class="field-error" role="alert">{{ error }}</p>
    <p v-else-if="hint" :id="`${id}-hint`" class="hint">{{ hint }}</p>
  </div>
</template>
