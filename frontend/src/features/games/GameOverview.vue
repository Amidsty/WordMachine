<script setup lang="ts">
import { computed } from 'vue'
import { gameStatusLabels, type GameState } from './contracts'
import { participantIds, storedText } from './presentation'
import UserLink from '../../shared/ui/UserLink.vue'
const props = defineProps<{ game: GameState }>()
const participantCount = computed(() => participantIds(props.game).size)
</script>

<template>
  <section aria-labelledby="game-overview-title">
    <h2 id="game-overview-title">对局信息</h2>
    <p>{{ game.rated ? 'Rated · 更新 Rating' : 'Unrated · 不更新 Rating' }}（创建时固定）</p>
    <dl class="game-facts">
      <div>
        <dt>比赛名称</dt>
        <dd class="multiline">
          <bdi>{{ game.name ?? `对局 #${game.id}` }}</bdi>
        </dd>
      </div>
      <div>
        <dt>房间号</dt>
        <dd>#{{ game.id }}</dd>
      </div>
      <div>
        <dt>状态</dt>
        <dd>{{ gameStatusLabels[game.status] }}</dd>
      </div>
      <div>
        <dt>词典</dt>
        <dd class="multiline">{{ storedText(game.dictname) }}</dd>
        <dt>本局 Perf 倍率</dt>
        <dd>
          {{
            game.multiplier_snapshot
              ? `×${game.multiplier_snapshot}（创建时固定）`
              : '旧局（无倍率快照）'
          }}
        </dd>
      </div>
      <div>
        <dt>房主</dt>
        <dd class="multiline">
          <UserLink
            :id="game.owner?.id"
            :name="storedText(game.owner?.username)"
            :rating="game.owner?.rating"
          />
        </dd>
      </div>
      <div>
        <dt>参赛记录</dt>
        <dd>{{ participantCount }} 人</dd>
      </div>
      <div>
        <dt>答题进度</dt>
        <dd>{{ game.current_index }} / {{ game.total_words }} 题</dd>
      </div>
      <div>
        <dt>对局版本</dt>
        <dd>{{ game.version }}</dd>
      </div>
    </dl>
    <p v-if="game.question_source === 'snapshot'" class="notice notice-info">
      题目来自创建时快照，不受后续词典修改影响。
    </p>
    <p v-else class="notice notice-info">
      旧对局：题目来自现有词典，可能与原题不同，尚未恢复历史快照。
    </p>
    <p v-if="game.next_answer_perf_rule_version === 'weighted-perf-v1'" class="hint">
      后续使用加权 Perf：个人连击奖励、房间全局连击中断惩罚；新手额度与竞技 Rating 分开结算。
    </p>
    <p v-else-if="game.next_answer_perf_rule_version" class="hint">
      后续作答使用累计 Perf：答错从上一条个人 Perf
      扣减，不重置初始分。旧答题记录保持原值，各条规则版本见答题历史。
    </p>
    <p class="hint">未作答题目不公开英文答案；提前结束也不例外。</p>
  </section>
</template>
