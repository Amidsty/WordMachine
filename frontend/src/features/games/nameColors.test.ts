import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { gameState } from '../../../testing/gameApi'
import { gamePersonSchema } from './contracts'
import GameOverview from './GameOverview.vue'
import GameScores from './GameScores.vue'
import AnswerHistory from './AnswerHistory.vue'
import GameTurn from './GameTurn.vue'

describe('game name colors', () => {
  it('uses current public Rating, not Perf or this/another saved settlement', () => {
    const game = gameState()
    // Current 2400 is red; this game's saved 1507 must stay unchanged and cyan is not used.
    const overview = mount(GameOverview, { props: { game } })
    const scores = mount(GameScores, { props: { game } })
    const answers = mount(AnswerHistory, { props: { game } })
    const turn = mount(GameTurn, {
      props: { game: gameState(4, 0, 0), actorId: 2, blocked: false },
    })
    for (const wrapper of [overview, scores, answers, turn]) {
      expect(wrapper.get('.user-name').classes()).toContain('user-name--red')
      expect(wrapper.find('img').exists()).toBe(false)
      wrapper.unmount()
    }
    expect(game.userrating[0]!.ratinghistory[1]!.new_rating).toBe(1507)
  })

  it('supports old/missing Rating metadata without deriving a color from history', () => {
    expect(gamePersonSchema.parse({ id: 1, username: 'old' }).rating).toBeUndefined()
    expect(gamePersonSchema.safeParse({ id: 1, username: 'old', rating: '2400' }).success).toBe(
      false,
    )
    const game = gameState()
    delete game.users[0]!.rating
    const wrapper = mount(GameScores, { props: { game } })
    expect(wrapper.get('.user-name').classes()).toContain('user-name--unknown')
    expect(wrapper.text()).toContain('1507')
    wrapper.unmount()
  })
})
