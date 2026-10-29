<script setup lang="ts">
import type { GameState } from './contracts'
import { gameStatusLabels } from './contracts'
defineProps<{ game: GameState }>()
</script>

<template>
  <div class="game-progress">
    <p class="game-mode">
      {{ gameStatusLabels[game.status] }} ·
      {{ game.rated ? 'Rated · 更新 Rating' : 'Unrated · 不更新 Rating' }}
    </p>
    <p :id="`game-progress-${game.id}`">
      已作答 {{ game.current_index }} / {{ game.total_words }} 题
    </p>
    <progress
      v-if="game.total_words > 0"
      :value="game.current_index"
      :max="game.total_words"
      :aria-labelledby="`game-progress-${game.id}`"
    />
  </div>
</template>

<style scoped>
.game-progress {
  min-width: 0;
  margin-block: 0.75rem;
}
.game-progress p {
  margin: 0.25rem 0;
}
.game-mode {
  font-weight: 600;
}
progress {
  display: block;
  width: 100%;
  max-width: 32rem;
  height: 0.5rem;
  accent-color: var(--ui-primary);
}
</style>
