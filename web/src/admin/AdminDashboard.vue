<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { Snapshot } from '../types'
import { zoneName } from '../api'
import Icon from '../ui/Icon.vue'
import SessionCard from './SessionCard.vue'
const props = defineProps<{ state: Snapshot; busy: boolean }>()
const sessions = computed(() => Object.values(props.state.sessions))
const active = computed(() => sessions.value.filter(s => s.state !== 'COMPLETED'))
const completed = computed(() => sessions.value.filter(s => s.state === 'COMPLETED'))
const taskCount = computed(() => Object.values(props.state.tasks).filter(t => !['DONE', 'CANCELLED'].includes(t.state)).length)
</script>

<template>
  <div class="summary-grid">
    <article class="summary-card"><span class="summary-icon"><Icon name="orders" /></span><div><span>진행 고객</span><strong>{{ active.length }}<small>명</small></strong></div></article>
    <article class="summary-card"><span class="summary-icon blue"><Icon name="robot" /></span><div><span>진행 작업</span><strong>{{ taskCount }}<small>건</small></strong></div></article>
    <article class="summary-card"><span class="summary-icon"><Icon name="check" /></span><div><span>인계 완료</span><strong>{{ completed.length }}<small>명</small></strong></div></article>
  </div>
  <div class="section-title"><h2>고객 현황</h2><RouterLink class="text-link" to="/admin/orders">전체 주문 <Icon name="arrow" :size="16" /></RouterLink></div>
  <section v-if="sessions.length" class="session-grid"><SessionCard v-for="session in sessions" :key="session.id" :session="session" :state="state" :busy="busy" compact /></section>
  <section v-else class="panel empty-state"><span class="empty-icon"><Icon name="cart" :size="30" /></span><h3>고객 없음</h3><RouterLink class="button secondary" :to="state.test_only ? '/admin/tests' : '/shop'">{{ state.test_only ? '장비 테스트' : '고객 화면' }} <Icon name="arrow" :size="16" /></RouterLink></section>
  <div class="section-title"><h2>작업 구역</h2></div>
  <section class="zone-grid"><article v-for="(zone, id) in state.zones" :key="id" class="zone-card" :class="{occupied: zone.owner}"><div class="section-title"><span class="zone-icon"><Icon :name="id === 'handoff' ? 'package' : 'arm'" /></span><span class="pill">{{ zone.owner ? '점유 중' : '배정 없음' }}</span></div><h3>{{ zoneName(String(id)) }}</h3><strong>{{ zone.owner ? state.sessions[state.tasks[zone.owner]?.session_id || '']?.label || '작업 중' : '대기' }}</strong><p>대기 {{ zone.queue?.length || 0 }}건</p><RouterLink class="text-link" :to="'/admin/omx/' + id">OMX <Icon name="arrow" :size="15" /></RouterLink></article></section>
</template>
