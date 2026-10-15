import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Customer from './Customer.vue'
import Admin from './Admin.vue'
import './style.css'

const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/', redirect: '/shop' },
  { path: '/shop', component: Customer },
  { path: '/admin', component: Admin },
  { path: '/:pathMatch(.*)*', redirect: '/shop' },
] })
createApp(App).use(router).mount('#app')
