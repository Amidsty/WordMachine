<script setup lang="ts">
import { RouterLink } from 'vue-router'
import UserLink from '../../shared/ui/UserLink.vue'
import { actionLabels, gameStatusLabels, type LobbyAction, type LobbyGame } from './service'
defineProps<{ game: LobbyGame }>()
defineEmits<{ act: [game: LobbyGame, action: LobbyAction] }>()
const actions: LobbyAction[] = ['join', 'leave', 'start', 'cancel']
</script>

<template>
  <article class="game-card" :aria-labelledby="`game-title-${game.id}`">
    <header class="card-heading">
      <h2 :id="`game-title-${game.id}`">
        <bdi>{{ game.name ?? '对局' }}</bdi> #{{ game.id }}
      </h2>
      <span>{{ gameStatusLabels[game.status] }}</span>
    </header>
    <p>{{ game.rated ? 'Rated · 更新 Rating' : 'Unrated · 不更新 Rating' }}</p>
    <p>词典：{{ game.dictname ?? '（词典缺失）' }}</p>
    <p>
      本局 Perf 倍率：{{
        game.multiplier_snapshot ? `×${game.multiplier_snapshot}（已固定）` : '旧规则（无倍率快照）'
      }}
    </p>
    <p>
      房主：<UserLink
        :id="game.owner?.id"
        :name="game.owner?.username ?? '（用户缺失）'"
        :rating="game.owner?.rating"
      />；参赛者 {{ game.users.length }} 人
    </p>
    <ul class="participants" aria-label="参赛者">
      <li v-for="user in game.users" :key="user.id">
        <UserLink
          v-if="user.username !== null"
          :id="user.id"
          :name="user.username"
          :rating="user.rating"
        />
        <span v-else>用户 #{{ user.id }}（缺失）</span>
      </li>
    </ul>
    <div class="actions">
      <template v-for="action in actions" :key="action">
        <button
          v-if="game.actions[action]"
          type="button"
          class="button"
          :class="{ 'button-danger': action === 'cancel' }"
          @click="$emit('act', game, action)"
        >
          {{ actionLabels[action] }}
        </button>
      </template>
      <RouterLink v-if="game.status === 0" class="button" :to="`/game/${game.id}/`">{{
        game.is_joined ? '进入对局' : '观战'
      }}</RouterLink>
      <RouterLink class="button" :to="`/game/${game.id}/detail/`">查看详情</RouterLink>
      <span v-if="game.is_joined">已报名</span>
    </div>
  </article>
</template>
