<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, ApiError, label, requestId, timeText, usePolling, zoneName } from './api'
import type { Product, Snapshot } from './types'

const token = ref(sessionStorage.getItem('shopping.customer.token') || '')
const name = ref('')
const products = ref<Product[]>([])
const state = ref<Snapshot | null>(null)
const quantities = ref<Record<string, number>>({})
const tab = ref<'products' | 'shopping'>('products')
const busy = ref(false)
const error = ref('')
const note = ref('')
const expired = ref(false)
const session = computed(() => Object.values(state.value?.sessions || {})[0])
const task = computed(() => session.value?.current_task ? state.value?.tasks[session.value.current_task] : undefined)
const orders = computed(() => Object.values(state.value?.orders || {}))
const ordered = computed(() => orders.value.reduce((n, order) => n + Object.values(order.items).reduce((a, b) => a + b, 0), 0))
const selected = computed(() => Object.values(quantities.value).reduce((a, b) => a + Number(b || 0), 0))
const canOrder = computed(() => session.value && !session.value.checkout_requested && !session.value.error)
// A retry after a lost response MUST reuse the same key and payload.
const pendingOrder = ref<{ request_id: string; items: { sku: string; quantity: number }[] } | null>(
  JSON.parse(sessionStorage.getItem('shopping.pending.order') || 'null'))
const { refresh, connectionError, lastUpdate } = usePolling(async () => {
  if (!token.value || expired.value) return
  try { state.value = await api<Snapshot>('/customer/state', token.value) }
  catch (e) { if (e instanceof ApiError && e.status === 401) expired.value = true; throw e }
})

async function action(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''; note.value = ''
  try { await work(); await refresh() }
  catch (e) { error.value = e instanceof Error ? e.message : '요청을 처리하지 못했습니다.' }
  finally { busy.value = false }
}
async function start() {
  await action(async () => {
    const result = await api<{ token: string }>('/sessions', '', { label: name.value })
    token.value = result.token
    sessionStorage.setItem('shopping.customer.token', result.token)
    expired.value = false
  })
}
async function order() {
  await action(async () => {
    if (!pendingOrder.value) {
      pendingOrder.value = { request_id: requestId(), items: products.value
        .filter(p => quantities.value[p.sku] > 0).map(p => ({ sku: p.sku, quantity: Number(quantities.value[p.sku]) })) }
      sessionStorage.setItem('shopping.pending.order', JSON.stringify(pendingOrder.value))
    }
    try {
      await api('/customer/orders', token.value, pendingOrder.value)
      pendingOrder.value = null; sessionStorage.removeItem('shopping.pending.order')
      quantities.value = {}; note.value = '주문을 접수했습니다. 실제 적재 수량은 별도로 확인합니다.'; tab.value = 'shopping'
    } catch (e) {
      if (e instanceof ApiError && [400, 401, 404, 409, 422].includes(e.status)) {
        pendingOrder.value = null; sessionStorage.removeItem('shopping.pending.order')
      }
      throw e
    }
  })
}
async function checkout() {
  if (!window.confirm('추가 주문을 마감하고 인계를 요청할까요? 접수된 상품 적재 후 인계합니다.')) return
  await action(async () => { await api('/customer/checkout', token.value, {}); tab.value = 'shopping' })
}
function newSession() {
  token.value = ''; state.value = null; expired.value = false; quantities.value = {}; pendingOrder.value = null
  sessionStorage.removeItem('shopping.customer.token'); sessionStorage.removeItem('shopping.pending.order')
}
const productName = (sku: string) => products.value.find(p => p.sku === sku)?.name || sku
onMounted(async () => {
  try { products.value = (await api<{ items: Product[] }>('/products')).items }
  catch (e) { error.value = String(e) }
  await refresh()
})
</script>

<template>
  <main class="customer-page">
    <section class="page-heading"><p class="eyebrow">CUSTOMER</p><h1>상품은 로봇에게,<br />쇼핑은 가볍게.</h1><p>상품 선택부터 고객 장바구니 인계까지 함께합니다.</p></section>
    <div v-if="connectionError" class="alert danger" role="alert">상태 갱신 실패 · {{ connectionError }}<br />마지막 표시 상태입니다. 완료 또는 정지를 뜻하지 않습니다.</div>
    <div v-if="error" class="alert danger" role="alert">{{ error }}</div>
    <div v-if="note" class="alert success" role="status">{{ note }}</div>
    <section v-if="!token" class="panel start-panel">
      <h2>쇼핑 시작</h2><p>고객별로 서로 다른 Pinky를 배정합니다.</p>
      <form @submit.prevent="start"><label for="customer-name">시연 고객 이름</label><input id="customer-name" v-model="name" maxlength="40" required placeholder="예: 고객 A" />
        <button class="primary" :disabled="busy || !name.trim()">로봇 배정받고 시작</button></form>
      <p class="muted">두 고객 시험은 다른 기기 또는 별도 브라우저 세션에서 시작하세요.</p>
    </section>
    <section v-else-if="expired" class="panel"><h2>세션을 다시 시작해주세요</h2><p>관리자가 새 모의 실행을 시작했거나 세션이 유효하지 않습니다.</p><button @click="newSession">새 쇼핑 시작</button></section>
    <template v-else-if="session">
      <section class="assignment"><div><small>{{ session.label }}님의 배정 로봇</small><strong>{{ session.robot_id }}</strong><small>인계 장바구니 {{ session.basket_id }}</small></div><span class="pill">{{ label(session.state) }}</span></section>
      <nav class="tabs" aria-label="고객 메뉴"><button :class="{ active: tab === 'products' }" @click="tab = 'products'">상품 주문</button><button :class="{ active: tab === 'shopping' }" @click="tab = 'shopping'">내 쇼핑</button></nav>
      <section v-if="tab === 'products'">
        <div class="section-title"><h2>지원 상품</h2><span class="muted">모의 상품 · 실제 규격 미정</span></div>
        <div class="product-list">
          <article v-for="(product, index) in products" :key="product.sku" class="product-card">
            <div class="product-symbol" :class="'product-' + index">{{ ['A', 'J', 'S'][index] }}</div>
            <div><span class="eyebrow">{{ zoneName(product.station) }}</span><h3>{{ product.name }}</h3><small>{{ product.sku }}</small></div>
            <label :for="product.sku">수량<input :id="product.sku" v-model.number="quantities[product.sku]" type="number" min="0" max="6" :disabled="!canOrder || busy || !!pendingOrder" /></label>
          </article>
        </div>
        <div class="panel order-summary"><p>선택 <strong>{{ selected }}개</strong> · 누적 주문 {{ ordered }}/{{ state?.capacity }}개</p><p class="muted">6개 제한은 모의 개발용입니다. 실물 적재 용량이 아닙니다.</p>
          <button class="primary" :disabled="busy || !canOrder || (!pendingOrder && selected === 0)" @click="order">{{ pendingOrder ? '접수 확인 재시도 (같은 주문)' : '주문 제출' }}</button>
          <p v-if="pendingOrder" class="muted">응답이 확인되지 않았습니다. 같은 주문 ID로 재확인합니다.</p>
          <p v-if="!canOrder" class="muted">인계 요청 또는 작업 오류로 추가 주문이 제한되었습니다.</p>
        </div>
      </section>
      <section v-else class="shopping-status">
        <div v-if="session.error" class="alert danger" role="alert"><strong>관련 작업이 중단되었습니다.</strong><p>{{ session.error }}</p>관리자 확인이 필요합니다.</div>
        <div class="metrics"><article><span>주문</span><strong>{{ ordered }}<small>개</small></strong></article><article><span>적재 확인</span><strong>{{ session.inventory.length }}<small>개</small></strong></article><article><span>인계 확인</span><strong>{{ session.inventory.filter(i => i.delivered).length }}<small>개</small></strong></article></div>
        <article class="panel"><p class="eyebrow">현재 단계</p><h2>{{ task ? label(task.state) : label(session.state) }}</h2><p v-if="task">{{ zoneName(task.zone_id) }} · {{ label(task.kind) }}</p>
          <p v-if="task?.state === 'WAIT_ZONE'">다른 로봇이 구역을 사용 중이거나 장비 연결을 기다리고 있습니다.</p>
          <p v-if="task?.state === 'WAIT_BASKET'">해당 고객의 장바구니 준비 확인을 기다립니다.</p>
          <p v-if="session.state === 'COMPLETED'">모의 상품 전체의 고객 장바구니 인계가 확인됐습니다. 완료 시각 {{ timeText(session.completed_at) }}</p>
          <small class="muted">마지막 화면 갱신 {{ lastUpdate?.toLocaleTimeString('ko-KR') || '—' }}</small>
        </article>
        <article class="panel"><h2>접수한 주문</h2><p v-if="!orders.length" class="muted">아직 주문한 상품이 없습니다.</p><div v-for="orderItem in orders" :key="orderItem.id" class="order-line"><small>{{ timeText(orderItem.created_at) }}</small><span v-for="(qty, sku) in orderItem.items" :key="sku">{{ productName(String(sku)) }} × {{ qty }}</span></div></article>
        <button class="primary" :disabled="busy || !ordered || session.checkout_requested || !!session.error || !!pendingOrder" @click="checkout">{{ session.checkout_requested ? '인계 요청 접수됨' : '주문 마감 · 인계 요청' }}</button>
        <p class="muted">요청 후에도 상품 인계가 확인될 때까지 쇼핑은 완료되지 않습니다.</p>
        <button v-if="session.state === 'COMPLETED' && !session.current_task" class="secondary" @click="newSession">새 쇼핑 시작</button>
      </section>
    </template>
    <section v-else class="panel" aria-live="polite">고객 상태를 불러오는 중입니다.</section>
  </main>
</template>
