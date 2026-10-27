<script setup lang="ts">
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { computed, onMounted, ref } from 'vue'
import Icon from './ui/Icon.vue'
import { api, usePolling } from './api'
const mode = ref('unknown')
const route = useRoute()
const isAdmin = computed(() => route.path.startsWith('/admin'))
const testOnly = ref(false)
const { refresh } = usePolling(async () => { try { const health = await api<{mode: string; test_only: boolean}>('/health'); mode.value = health.mode; testOnly.value = health.test_only } catch { mode.value = 'unknown' } })
onMounted(refresh)
</script>

<template>
  <a class="skip-link" href="#main-content">본문으로 건너뛰기</a>
  <div class="app-frame" :class="{ 'operations-app': isAdmin }">
  <header class="site-header">
    <div class="brand-group"><RouterLink class="brand" :to="isAdmin ? '/admin/overview' : '/shop'"><span class="brand-icon"><Icon name="robot" :size="25" /></span><span>쇼핑키프로</span></RouterLink><span class="mode-badge" role="status"><span class="mode-dot" :class="{mock: mode === 'mock'}"></span>{{ mode === 'unknown' ? '모드 미확인' : testOnly ? '장비 검사' : mode === 'mock' ? '모의' : '현장' }}</span></div>
    <nav aria-label="화면 선택"><RouterLink to="/shop" :aria-current="!isAdmin ? 'page' : undefined">고객 화면</RouterLink><RouterLink to="/admin/overview" :class="{ 'router-link-active': isAdmin }" :aria-current="isAdmin ? 'page' : undefined">관리자</RouterLink></nav>
  </header>
  <RouterView />
  </div>
</template>
