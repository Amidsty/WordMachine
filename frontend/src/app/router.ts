import { nextTick } from 'vue'
import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'
import LoginPage from '../features/auth/LoginPage.vue'
import RegisterPage from '../features/auth/RegisterPage.vue'
import ProfilePage from '../features/profile/ProfilePage.vue'
import NotFoundPage from './NotFoundPage.vue'
import { errorMessage } from '../shared/forms/useFormTask'
import type { AppServices } from './services'
import { afterLoginTarget } from './navigation'

export function createAppRouter(
  services: AppServices,
  history: RouterHistory = createWebHistory(),
) {
  const router = createRouter({
    history,
    routes: [
      {
        path: '/',
        name: 'lobby',
        component: () => import('../features/lobby/LobbyPage.vue'),
        meta: { title: '对局大厅', authenticated: true },
      },
      {
        path: '/game/:id(\\d+)/',
        name: 'game-playing',
        component: () => import('../features/games/GamePlayingPage.vue'),
        meta: { title: '对局', authenticated: true },
      },
      {
        path: '/game/:id(\\d+)/detail/',
        name: 'game-detail',
        component: () => import('../features/games/GameDetailPage.vue'),
        meta: { title: '对局详情', authenticated: true },
      },
      {
        path: '/game-end-requests/',
        name: 'game-end-requests',
        component: () => import('../features/games/GameEndRequestsPage.vue'),
        meta: { title: '比赛结束请求', authenticated: true },
      },
      {
        path: '/leaderboard/',
        name: 'leaderboard',
        component: () => import('../features/people/LeaderboardPage.vue'),
        meta: { title: '排行榜' },
      },
      {
        path: '/user/:id(\\d+)/',
        name: 'public-profile',
        component: () => import('../features/people/PublicProfilePage.vue'),
        meta: { title: '公开资料' },
      },
      { path: '/login/', name: 'login', component: LoginPage, meta: { title: '登录' } },
      { path: '/register/', name: 'register', component: RegisterPage, meta: { title: '注册' } },
      {
        path: '/changepw/',
        name: 'profile',
        component: ProfilePage,
        meta: { title: '修改资料', authenticated: true },
      },
      {
        path: '/admin/',
        component: () => import('../features/management/ManagementLayout.vue'),
        meta: { authenticated: true },
        children: [
          {
            path: '',
            name: 'management',
            component: () => import('../features/dictionaries/DictionariesPage.vue'),
            meta: { title: '词典管理' },
          },
          {
            path: 'dicts/:id(\\d+)/',
            name: 'dictionary',
            component: () => import('../features/dictionaries/DictionaryPage.vue'),
            meta: { title: '词典详情' },
          },
          {
            path: 'dictionary-promotions/',
            name: 'dictionary-promotions',
            component: () => import('../features/dictionaries/PromotionsPage.vue'),
            meta: { title: '系统词典申请' },
          },
          {
            path: 'users/',
            name: 'users',
            component: () => import('../features/users/UsersPage.vue'),
            meta: { title: '用户管理', root: true },
          },
        ],
      },
      { path: '/:pathMatch(.*)*', component: NotFoundPage, meta: { title: '页面不存在' } },
    ],
    scrollBehavior: () => ({ top: 0 }),
  })
  router.beforeEach(async (to) => {
    if (!to.name) return true
    try {
      const session = await services.client.loadSession(true)
      services.sessionError.value = ''
      if (to.meta.authenticated && !session.authenticated) {
        return { name: 'login', query: { next: afterLoginTarget(to.path) } }
      }
      if (to.meta.root && (session.user?.admin_level ?? 0) === 0)
        return { name: 'management', query: { denied: '1' } }
    } catch (error) {
      services.sessionError.value = errorMessage(error)
      if (to.meta.authenticated)
        return { name: 'login', query: { next: afterLoginTarget(to.path) } }
    }
    return true
  })
  router.afterEach(async (to) => {
    document.title = `${String(to.meta.title)} - WordMachine`
    await nextTick()
    document.getElementById('page-title')?.focus()
  })
  return router
}
