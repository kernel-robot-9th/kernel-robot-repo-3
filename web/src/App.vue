<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="mock-strip"><strong>MOCK · 모의 장비</strong><span>실제 로봇 동작을 검증한 화면이 아닙니다.</span></div>
  <header class="site-header">
    <RouterLink class="brand" to="/shop"><span class="brand-icon">P</span><span>쇼핑키프로<small>ROBOT SHOPPING LAB</small></span></RouterLink>
    <nav aria-label="화면 선택"><RouterLink to="/shop">고객 화면</RouterLink><RouterLink to="/admin">관리자</RouterLink></nav>
  </header>
  <RouterView />
  <footer class="site-footer">SR-01~14 기본 흐름 개발 · 고객 수령 확인(SR-29)은 별도 옵션입니다.</footer>
</template>
