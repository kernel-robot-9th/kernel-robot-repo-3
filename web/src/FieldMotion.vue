<script setup lang="ts">
import type { Snapshot } from './types'
defineProps<{ state: Snapshot }>()
defineEmits<{ tests: [] }>()
</script>

<template>
  <section class="panel">
    <p class="eyebrow">PINKY · FIELD SETUP</p>
    <h2>실제 이동 연결 준비</h2>
    <p>저장 맵·정차 위치·후진 주차와 실제 주행 어댑터를 현장 설정에 연결해야 합니다.</p>
    <div class="device-grid">
      <article v-for="id in ['pinky-1', 'pinky-2']" :key="id" class="panel">
        <h3>{{ id }}</h3>
        <span class="pill">{{ state.devices?.[id]?.connected ? '주문 중계 통신 연결' : '주문 제어 미연결' }}</span>
        <p>실측 위치 · 정차 · 주차 정렬 미확인</p>
      </article>
    </div>
    <p class="muted">현재 화면에는 실측 위치 수신이 연결되지 않았습니다. 중계의 통신 응답만으로 Pinky 준비·정차를 확인하지 않습니다.</p>
    <button @click="$emit('tests')">장비 테스트에서 중계 응답 확인</button>
  </section>
</template>
