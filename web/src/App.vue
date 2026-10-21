<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
import { onMounted, ref } from 'vue'
import { api, usePolling } from './api'
const mode = ref('unknown')
const { refresh } = usePolling(async () => { try { mode.value = (await api<{mode: string}>('/health')).mode } catch { mode.value = 'unknown' } })
onMounted(refresh)
</script>

<template>
  <div class="mock-strip"><strong>{{ mode === 'mock' ? 'MOCK · 모의 장비' : mode === 'hardware' ? 'HARDWARE · 현장 연결 모드' : '장비 모드 확인 필요' }}</strong><span>{{ mode === 'mock' ? '모의 성공은 실제 로봇 검증을 뜻하지 않습니다.' : '명령 수락·결과·정지 확인을 구분해 표시합니다.' }}</span></div>
  <header class="site-header">
    <RouterLink class="brand" to="/shop"><span class="brand-icon">P</span><span>쇼핑키프로<small>ROBOT SHOPPING LAB</small></span></RouterLink>
    <nav aria-label="화면 선택"><RouterLink to="/shop">고객 화면</RouterLink><RouterLink to="/admin">관리자</RouterLink></nav>
  </header>
  <RouterView />
  <footer class="site-footer">SR-01~14 기본 흐름 개발 · 고객 수령 확인(SR-29)은 별도 옵션입니다.</footer>
</template>
