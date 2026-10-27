<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import type { Session, Snapshot } from '../types'
import { label, shortId, timeText, zoneName } from '../api'
import Icon from '../ui/Icon.vue'
import { currentTask, needsBasket, orderedCount, robotName } from './presentation'
const props = defineProps<{ state: Snapshot; session: Session; busy: boolean; compact?: boolean }>()
defineEmits<{ ready: [session: Session, basketId: string] }>()
const basketId = ref('')
const task = computed(() => currentTask(props.state, props.session))
const delivered = computed(() => props.session.inventory.filter(item => item.delivered).length)
const ordered = computed(() => orderedCount(props.state, props.session.id))
</script>

<template>
  <article class="panel session-card">
    <div class="section-title"><div class="person-heading"><span class="avatar">{{ session.label.slice(0, 1) }}</span><div><h3>{{ session.label }}</h3><small>{{ robotName(session.robot_id) }}</small></div></div><span class="pill" :class="{ bad: session.error, complete: session.state === 'COMPLETED' }">{{ session.state === 'COMPLETED' ? '시연 흐름 완료' : label(session.state) }}</span></div>
    <div class="session-progress"><span :style="{ width: ordered ? Math.min(100, delivered / ordered * 100) + '%' : '0%' }"></span></div>
    <div class="metrics"><article><span>주문</span><strong>{{ ordered }}<small>개</small></strong></article><article><span>적재 실행</span><strong>{{ session.inventory.length }}<small>개</small></strong></article><article><span>인계 실행</span><strong>{{ delivered }}<small>개</small></strong></article></div>
    <p v-if="state.mode === 'hardware'" class="muted">실물 확인: 적재 {{ session.inventory.filter(i => i.physical_loading_confirmed).length }}개 · 하역 {{ session.inventory.filter(i => i.physical_delivery_confirmed).length }}개</p>
    <p v-if="task || session.state !== 'COMPLETED'" class="current-stage"><Icon name="clock" :size="17" />{{ task ? label(task.state) : session.state === 'COMPLETED' ? '시연 흐름 완료' : label(session.state) }}</p>
    <p v-if="task" class="muted">{{ zoneName(task.zone_id) }}<template v-if="!compact"> · {{ label(task.kind) }}</template></p>
    <div v-if="session.error && !compact" class="alert danger" role="alert"><strong>작업 중단</strong><p>{{ session.error }}</p></div>
    <form v-if="!compact && needsBasket(state, session)" class="basket-confirm" @submit.prevent="$emit('ready', session, basketId.trim())">
      <h4>장바구니 준비</h4><p>{{ session.basket_side === 'left' ? '왼쪽' : session.basket_side === 'right' ? '오른쪽' : '방향 미지정' }} 장바구니 · 배정값 <strong>{{ session.basket_id }}</strong></p>
      <label :for="'basket-' + session.id">장바구니 ID</label><input :id="'basket-' + session.id" v-model="basketId" placeholder="장바구니 ID 입력" maxlength="80" required />
      <button class="primary" :disabled="busy || !basketId.trim()">장바구니 준비 확인</button>
    </form>
    <template v-if="!compact"><p class="muted">현재 카트 {{ session.inventory.length - delivered }}/3개<span v-if="session.active_trip"> · {{ state.trips[session.active_trip]?.number }}차 운반</span></p><p v-if="session.state === 'COMPLETED'" class="muted">시연 흐름 완료 {{ timeText(session.completed_at) }} · {{ session.current_task ? '구역 이탈 대기' : '로봇 배정 해제' }}</p><details class="session-details"><summary>작업 정보</summary><small>고객 {{ shortId(session.id) }} · {{ session.basket_side === 'left' ? '왼쪽 인계' : session.basket_side === 'right' ? '오른쪽 인계' : '인계 방향 미지정' }}</small></details></template>
    <RouterLink v-if="compact" class="text-link card-link" :to="{ path: '/admin/orders', query: { customer: session.id } }">주문 상세 보기 <Icon name="arrow" :size="16" /></RouterLink>
  </article>
</template>
