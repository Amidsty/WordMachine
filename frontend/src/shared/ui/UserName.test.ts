import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UserName from './UserName.vue'

describe('current Rating name colors', () => {
  it.each([
    [-2147483648, 'gray'],
    [0, 'gray'],
    [1199, 'gray'],
    [1200, 'green'],
    [1399, 'green'],
    [1400, 'cyan'],
    [1599, 'cyan'],
    [1600, 'blue'],
    [1899, 'blue'],
    [1900, 'violet'],
    [2099, 'violet'],
    [2100, 'orange'],
    [2399, 'orange'],
    [2400, 'red'],
    [2999, 'red'],
    [3000, 'legendary'],
    [2147483647, 'legendary'],
  ])('maps %s to %s without changing the name', (rating, band) => {
    const wrapper = mount(UserName, { props: { name: '名字 🐈', rating } })
    expect(wrapper.classes()).toContain(`user-name--${band}`)
    expect(wrapper.text()).toBe('名字 🐈')
    expect(wrapper.attributes('title')).toBe(`当前 Rating：${rating}`)
    wrapper.unmount()
  })

  it.each([undefined, null, NaN, Infinity, -Infinity])('leaves %s unknown, not zero', (rating) => {
    const wrapper = mount(UserName, { props: { name: 'unknown', rating } })
    expect(wrapper.classes()).toContain('user-name--unknown')
    expect(wrapper.attributes('title')).toBe('当前 Rating 缺失')
    wrapper.unmount()
  })

  it('reacts to Rating changes and preserves escaped Unicode text at every tier', async () => {
    const name = '<img src=x onerror=alert(1)> 👩‍💻 e\u0301'
    const wrapper = mount(UserName, { props: { name, rating: 1500 } })
    expect(wrapper.classes()).toContain('user-name--cyan')
    await wrapper.setProps({ rating: 3000 })
    expect(wrapper.classes()).toContain('user-name--legendary')
    expect(wrapper.classes()).not.toContain('user-name--cyan')
    expect(wrapper.text()).toBe(name)
    expect(wrapper.find('img').exists()).toBe(false)
    await wrapper.setProps({ rating: null })
    expect(wrapper.classes()).toContain('user-name--unknown')
    expect(wrapper.text()).toBe(name)
    wrapper.unmount()
  })
})
