<script setup lang="ts">
import type { GameState } from './contracts'
import { storedNumber, storedPerf } from './presentation'
import UserLink from '../../shared/ui/UserLink.vue'
defineProps<{ game: GameState }>()
</script>
<template>
  <section class="section-panel" aria-label="加权评分分项">
    <h2>评分分项</h2>
    <p v-if="!game.scoring">
      旧模型：局分、竞技变化、新手额度及内部 Rating 分项未记录，不从旧总分推算。
    </p>
    <template v-else>
      <p>
        规则：{{ game.scoring.perf_version }} / {{ game.scoring.rating_version }} · 冻结难度 D：{{
          game.scoring.difficulty
        }}
        · 冻结词典倍率 M：{{ game.multiplier_snapshot }}
      </p>
      <p v-if="game.scoring.model === 'weighted-v2'" class="hint">
        v2是受控累计表现，不再使用对数赔率反推；同一作答序列的Perf偏移与词典倍率成正比。难度仅作0.75–1.25倍修正，无额外动态高Perf扣分。长局仍会累计，单题有界不等于整局Perf有固定上限。
      </p>
      <p v-else class="hint">v1历史规则可能在极端难度下大幅波动；保留原值，不按v2重算。</p>
      <p class="hint">
        原始局分不等于 Perf；公开 Rating 总变化 = 竞技变化 +
        新手额度。额度总额1500分六场释放，不是每场补到1500。高分涨/跌系数仅调整竞技变化，不调整额度。服务端保存完整精度，以下小数仅用于展示。
      </p>
      <p v-if="!game.rated">Unrated 仅展示练习表现，不更新 Rating、额度或有效场次。</p>
      <p v-if="!game.scoring.players.length">尚未开局，无个人评分快照。</p>
      <div v-for="p in game.scoring.players" :key="p.user_id" class="section-panel">
        <h3>
          <UserLink
            :id="p.user_id"
            :name="game.users.find((u) => u.id === p.user_id)?.username ?? '用户名未记录'"
            :rating="game.users.find((u) => u.id === p.user_id)?.rating"
          />
        </h3>
        <p>
          开局公开 R：{{ p.public_before }} · 内部 U：{{ p.internal_before }} · 剩余额度 H：{{
            p.remaining_before
          }}
          · 已完成新模型 Rated：{{ p.completed_before }}
        </p>
        <p>
          新手政策：{{ p.newcomer_enabled ? '启用' : '关闭' }} · 连击保护 w：{{
            p.streak_protection.toFixed(2)
          }}
          · 更新系数 k：{{ p.rating_protection.toFixed(2) }}
        </p>
        <p>
          冻结涨分系数：{{ p.speed_up.toFixed(4) }} · 冻结扣分系数：{{ p.speed_down.toFixed(4) }}
        </p>
        <p v-if="game.scoring.model === 'weighted-v2'">
          冻结难度涨/扣系数：{{ p.difficulty_up?.toFixed(4) }} /
          {{ p.difficulty_down?.toFixed(4) }} · 全局连击反馈：{{
            p.global_protection?.toFixed(2)
          }}（新手也不归零）
        </p>
        <p>
          原始局分：{{ p.answered_count ? storedPerf(p.raw_points) : '未作答' }} · Perf：{{
            p.answered_count ? storedPerf(p.perf) : '未作答'
          }}
        </p>
        <template v-if="p.settlement">
          <p>
            竞技变化：{{ storedNumber(p.settlement.competitive_delta, true) }} · 新手基础额度：{{
              storedNumber(p.settlement.newcomer_bonus, true)
            }}
            · 公开 Rating 总变化：{{ storedNumber(p.settlement.total_delta, true) }}
          </p>
          <p>
            赛后公开 R：{{ p.settlement.public_after }} · 赛后内部 U：{{
              p.settlement.internal_after
            }}
            · 剩余额度 H：{{ p.settlement.remaining_after }}
          </p>
        </template>
        <p v-else>{{ game.status === 1 ? '未产生 Rating 结算' : '尚未结算 Rating' }}</p>
      </div>
      <details v-if="game.scoring.answers.length">
        <summary>逐题局分与 Perf 增减</summary>
        <p>
          正确奖励使用个人连击；错误惩罚来自房间全局连击中断（先计惩罚再清零），不是个人连击中断。
        </p>
        <table>
          <caption>
            保存的逐题评分
          </caption>
          <thead>
            <tr>
              <th>题序</th>
              <th>抽样</th>
              <th>局分增减</th>
              <th>Perf 增减</th>
              <th>此前个人/全局连击</th>
              <th>连击倍率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in game.scoring.answers" :key="a.position">
              <td>{{ a.position + 1 }}</td>
              <td>{{ a.draw }}</td>
              <td>{{ storedPerf(a.raw_point_delta) }}</td>
              <td>{{ storedPerf(a.perf_delta) }}</td>
              <td>{{ a.self_before }} / {{ a.global_before }}</td>
              <td>{{ a.effective_multiplier.toFixed(4) }}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </template>
  </section>
</template>
