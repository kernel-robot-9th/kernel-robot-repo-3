import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Customer from './Customer.vue'
import Admin from './Admin.vue'
import './style.css'
import { adminPages } from './admin/navigation'

const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/shop' },
  { path: '/shop', component: Customer },
  { path: '/admin', component: Admin },
  ...['overview', 'orders', 'video', 'stock', 'tests', 'diagnostics'].map(section => ({
    path: '/admin/' + section, component: Admin, meta: { section },
  })),
  { path: '/admin/omx', redirect: '/admin/omx/load-a' },
  { path: '/admin/omx/:detail(load-a|load-b|handoff)', component: Admin, meta: { section: 'omx' } },
  { path: '/admin/pinky', redirect: '/admin/pinky/movement' },
  { path: '/admin/pinky/:detail(movement|pinky-1|pinky-2)', component: Admin, meta: { section: 'pinky' } },
  { path: '/admin/:pathMatch(.*)*', redirect: '/admin/overview' },
  { path: '/:pathMatch(.*)*', redirect: '/shop' },
], scrollBehavior: () => ({ top: 0 }) })
router.beforeEach(to => {
  if (to.path === '/admin') return to.hash === '#motion' ? '/admin/pinky/movement' : '/admin/overview'
})
router.afterEach(to => {
  const page = adminPages.find(page => page.section === to.meta.section)
  document.title = page ? `${page.label} · 쇼핑키프로` : '쇼핑키프로 · 로봇 쇼핑'
})
createApp(App).use(router).mount('#app')
