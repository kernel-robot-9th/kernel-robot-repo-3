<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from './ui/Icon.vue'
import { robotName } from './admin/presentation'
import { api, ApiError, label, requestId, timeText, usePolling, zoneName } from './api'
import type { Product, Snapshot } from './types'

const token = ref(sessionStorage.getItem('shopping.customer.token') || '')
const name = ref('')
const products = ref<Product[]>([])
const acceptingSessions = ref(false)
const state = ref<Snapshot | null>(null)
const quantities = ref<Record<string, number>>({})
const route = useRoute(), router = useRouter()
const tab = computed<'products' | 'shopping'>({
  get: () => route.query.view === 'orders' ? 'shopping' : 'products',
  set: value => { void router.push({ path: '/shop', query: value === 'shopping' ? { view: 'orders' } : {} }) },
})
const catalogLoading = ref(true)
const busy = ref(false)
const error = ref('')
const note = ref('')
const expired = ref(false)
const session = computed(() => Object.values(state.value?.sessions || {})[0])
const task = computed(() => session.value?.current_task ? state.value?.tasks[session.value.current_task] : undefined)
const orders = computed(() => Object.values(state.value?.orders || {}))
const ordered = computed(() => orders.value.filter(o => o.status !== 'CANCELLED').reduce((n, order) => n + Object.values(order.items).reduce((a, b) => a + b, 0), 0))
const selected = computed(() => Object.values(quantities.value).reduce((a, b) => a + Number(b || 0), 0))
const canOrder = computed(() => session.value && !session.value.checkout_requested && !session.value.error && !state.value?.test_only && !state.value?.test_hold && !connectionError.value && !expired.value)
const trip = computed(() => session.value?.active_trip ? state.value?.trips[session.value.active_trip] : undefined)
const selectionAvailable = computed(() => products.value.every(p => (quantities.value[p.sku] || 0) <= (p.available ?? 0)))
function canAdd(p: Product) {
  return canOrder.value && !busy.value && !pendingOrder.value && selected.value < 6 &&
    (quantities.value[p.sku] || 0) < (p.available ?? 0)
}
function add(p: Product) { if (canAdd(p)) quantities.value[p.sku] = (quantities.value[p.sku] || 0) + 1 }
function remove(p: Product) { quantities.value[p.sku] = Math.max(0, (quantities.value[p.sku] || 0) - 1) }
// A retry after a lost response MUST reuse the same key and payload.
type PendingOrder = { request_id: string; items: { sku: string; quantity: number }[] }
function savedOrder(): PendingOrder | null {
  try { return JSON.parse(sessionStorage.getItem('shopping.pending.order') || 'null') } catch { return null }
}
const pendingOrder = ref<PendingOrder | null>(savedOrder())
const { refresh, connectionError, lastUpdate } = usePolling(async () => {
  try {
    const catalog = await api<{ items: Product[]; accepting_sessions: boolean }>('/products')
    products.value = catalog.items
    acceptingSessions.value = catalog.accepting_sessions
  } finally { catalogLoading.value = false }
  if (!token.value || expired.value) return
  try {
    state.value = await api<Snapshot>('/customer/state', token.value)
    products.value = state.value.products
  }
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
    const result = await api<{ token: string }>('/sessions', '', { label: name.value.trim() })
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
      quantities.value = {}; note.value = '주문 접수'; tab.value = 'shopping'
    } catch (e) {
      if (e instanceof ApiError && [400, 401, 404, 409, 422].includes(e.status)) {
        pendingOrder.value = null; sessionStorage.removeItem('shopping.pending.order')
      }
      throw e
    }
  })
}
async function checkout() {
  if (!window.confirm('주문을 마감하고 인계할까요? 3개씩 운반하며 남은 상품은 자동으로 다시 가져옵니다.')) return
  await action(async () => { await api('/customer/checkout', token.value, {}); tab.value = 'shopping' })
}
async function cancel(orderId: string) {
  await action(async () => { await api('/customer/orders/' + orderId + '/cancel', token.value, {}); note.value = '주문 취소' })
}
function newSession() {
  token.value = ''; state.value = null; expired.value = false; quantities.value = {}; pendingOrder.value = null
  sessionStorage.removeItem('shopping.customer.token'); sessionStorage.removeItem('shopping.pending.order')
  tab.value = 'products'
}
const productName = (sku: string) => products.value.find(p => p.sku === sku)?.name || sku
const delivered = computed(() => session.value?.inventory.filter(i => i.delivered).length || 0)
const stage = computed(() => session.value?.state === 'COMPLETED' ? 3 : session.value?.checkout_requested ? 2 : ordered.value ? 1 : 0)
const statusTitle = computed(() => {
  if (session.value?.error) return '작업 중단'
  if (session.value?.state === 'COMPLETED') return '시연 흐름 완료'
  if (task.value?.state === 'WAIT_BASKET') return '장바구니 대기'
  if (task.value?.state === 'WAIT_ZONE') return '작업 대기'
  if (task.value?.kind === 'HANDOFF' && task.value.state === 'MOVING') return '인계 장소 이동'
  if (task.value?.kind === 'HANDOFF') return '인계 중'
  if (ordered.value) return '상품 준비 중'
  return '상품 선택'
})
const selectedProducts = computed(() => products.value.filter(p => quantities.value[p.sku] > 0))
const productIcon = (p: Product) => p.detector_class.includes('milk') ? 'milk' : p.detector_class.includes('ramen') ? 'bowl' : 'snack'
onMounted(refresh)
</script>

<template>
  <main id="main-content" class="customer-page" tabindex="-1">
    <header class="customer-heading"><h1>{{ !token ? '로봇 쇼핑' : tab === 'products' ? '상품 고르기' : '내 주문' }}</h1></header>
    <div v-if="connectionError" class="alert danger" role="alert"><strong>연결 끊김 · 마지막 조회 상태</strong><p>{{ connectionError }}</p><button @click="refresh">다시 불러오기</button></div>
    <div v-if="error" class="alert danger" role="alert">{{ error }}</div>
    <div v-if="note" class="alert success" role="status"><Icon name="check" :size="18" />{{ note }}</div>
    <section v-if="expired" class="panel empty-state"><h2>쇼핑 정보 만료</h2><button class="primary" @click="newSession">새 쇼핑 시작</button></section>
    <section v-else-if="catalogLoading" class="panel empty-state" role="status">불러오는 중…</section>
    <template v-else-if="!token">
      <section v-if="!acceptingSessions && !connectionError" class="panel empty-state"><span class="empty-icon"><Icon name="clock" :size="32" /></span><h2>주문 준비 중</h2></section>
      <section v-else class="panel start-panel"><span class="welcome-icon"><Icon name="robot" :size="34" /></span><h2>쇼핑 시작</h2><form @submit.prevent="start"><label for="customer-name">고객 이름</label><input id="customer-name" v-model="name" maxlength="40" required autocomplete="name" placeholder="예: 김쇼핑" /><button class="primary" :disabled="busy || !name.trim() || !acceptingSessions || !!connectionError">{{ busy ? '시작하는 중…' : '쇼핑 시작하기' }}<Icon name="arrow" :size="18" /></button></form></section>
    </template>
    <template v-else-if="session">
      <section class="assignment"><span class="assignment-icon"><Icon name="robot" :size="27" /></span><div><small>{{ session.label }}</small><strong>{{ robotName(session.robot_id) }}</strong></div><span class="pill">{{ session.basket_side === 'left' ? '왼쪽 장바구니' : session.basket_side === 'right' ? '오른쪽 장바구니' : '장바구니 대기' }}</span></section>
      <nav class="customer-tabs" aria-label="고객 메뉴"><button :class="{ active: tab === 'products' }" :aria-current="tab === 'products' ? 'page' : undefined" @click="tab = 'products'"><Icon name="cart" :size="18" />상품 고르기</button><button :class="{ active: tab === 'shopping' }" :aria-current="tab === 'shopping' ? 'page' : undefined" @click="tab = 'shopping'"><Icon name="orders" :size="18" />내 주문<span v-if="ordered" class="count-badge">{{ ordered }}</span></button></nav>
      <section v-if="tab === 'products'" class="catalog-section">
        <div class="catalog-toolbar"><span>{{ products.length }}종</span><span class="pill">최대 6개</span></div>

        <div v-if="!canOrder" class="inline-note" role="status">{{ state?.test_only || state?.test_hold ? '장비 검사 중' : connectionError ? '연결 대기' : session.error ? '작업 중단' : '주문 마감' }}</div>
        <div class="product-list"><article v-for="(product, index) in products" :key="product.sku" class="product-card" :class="{ 'is-selected': quantities[product.sku], 'is-sold-out': product.available === 0 }">
          <button class="product-select" :disabled="!canAdd(product)" :aria-label="product.name + (quantities[product.sku] ? ' 추가로 담기' : ' 담기')" @click="add(product)">
            <span class="product-illustration" :class="'product-tone-' + index % 4" aria-hidden="true"><Icon :name="productIcon(product)" :size="38" /></span>
            <span class="product-info"><strong>{{ product.name }}</strong><span class="availability" :class="{ unavailable: product.available === 0 }">{{ product.available === null ? '재고 미확인' : product.available === 0 ? (product.stock?.reserved ? '예약 중' : '품절') : quantities[product.sku] ? '선택됨' : !canOrder ? '선택 불가' : '' }}</span></span>
            <span class="product-pick" :class="{ picked: quantities[product.sku] }"><span v-if="(quantities[product.sku] || 0) > 1" aria-live="polite">×{{ quantities[product.sku] }}</span><Icon v-else :name="quantities[product.sku] ? 'check' : 'cart'" :size="20" /></span>
          </button>
        </article></div>
        <p v-if="selected === 6" class="inline-note" role="status">최대 6개 선택됨</p>
        <section class="order-summary panel"><details v-if="selectedProducts.length"><summary>선택한 상품 보기 <span>{{ selected }}개</span></summary><div v-for="p in selectedProducts" :key="p.sku" class="selected-line"><span>{{ p.name }}</span><span class="selection-actions"><strong v-if="quantities[p.sku] > 1">×{{ quantities[p.sku] }}</strong><button class="remove-selection" :aria-label="p.name + ' 선택에서 1개 빼기'" :disabled="busy || !!pendingOrder" @click="remove(p)">빼기</button></span></div></details><p v-if="!selectionAvailable && !pendingOrder" class="alert danger" role="status">주문 가능 수량 초과</p><p v-if="pendingOrder" class="inline-note" role="status">주문 응답 미확인</p><div class="order-bar"><div aria-live="polite" aria-atomic="true"><small>{{ pendingOrder ? '접수 확인 중' : '선택한 상품' }}</small><strong>{{ pendingOrder ? pendingOrder.items.reduce((n, i) => n + i.quantity, 0) : selected }}<span>개</span></strong></div><button class="primary" :disabled="busy || !canOrder || (!pendingOrder && (selected === 0 || selected > 6 || !selectionAvailable))" @click="order">{{ busy ? '처리 중…' : pendingOrder ? '주문 접수 다시 확인' : '주문하기' }}<Icon name="arrow" :size="18" /></button></div></section>
      </section>
      <section v-else class="shopping-status">
        <section class="panel customer-progress"><h2>{{ statusTitle }}</h2><p v-if="trip" class="muted">{{ trip.number }}차 운반 · 현재 카트 {{ session.inventory.length - delivered }}/3개</p><ol class="order-steps" aria-label="주문 진행 단계"><li v-for="(step, i) in ['상품 선택', '상품 준비', '인계 요청', '시연 흐름 완료']" :key="step" :class="{ done: i < stage, current: i === stage }" :aria-current="i === stage ? 'step' : undefined"><span><Icon v-if="i < stage" name="check" :size="15" /><template v-else>{{ i + 1 }}</template></span>{{ step }}</li></ol></section>
        <div v-if="session.error" class="alert danger" role="alert"><strong>작업 중단</strong><p>{{ session.error }}</p></div>
        <div class="metrics"><article><span>주문한 상품</span><strong>{{ ordered }}<small>개</small></strong></article><article><span>적재 실행</span><strong>{{ session.inventory.length }}<small>개</small></strong></article><article><span>인계 실행</span><strong>{{ delivered }}<small>개</small></strong></article></div>
        <section v-if="ordered && !session.checkout_requested" class="panel checkout-panel"><button class="primary" :disabled="busy || !!session.error || !!pendingOrder || !!connectionError" @click="checkout">주문 마감 · 상품 받기<Icon name="arrow" :size="18" /></button><button class="text-link" :disabled="!canOrder" @click="tab = 'products'">상품 더 고르기</button></section>
        <section v-else-if="session.checkout_requested && session.state !== 'COMPLETED'" class="inline-note"><Icon name="clock" /><span>인계 요청 접수</span></section>
        <div v-if="session.state === 'COMPLETED'" class="completion-actions"><button class="primary" :disabled="!!session.current_task" @click="newSession">{{ session.current_task ? '구역 이탈 대기' : '새 쇼핑 시작' }}</button></div>
        <section class="panel"><div class="section-title"><h2>주문 내역</h2><span class="pill">{{ orders.length }}건</span></div><div v-if="!orders.length" class="empty-state"><Icon name="cart" :size="30" /><h3>주문 없음</h3><button class="primary" @click="tab = 'products'">상품 고르기</button></div><article v-for="orderItem in orders" :key="orderItem.id" class="customer-order-record"><div class="section-title"><small>{{ timeText(orderItem.created_at) }}</small><span class="pill" :class="{ bad: orderItem.status === 'CANCELLED' }">{{ orderItem.status === 'CANCELLED' ? '취소됨' : '접수됨' }}</span></div><div v-for="(qty, sku) in orderItem.items" :key="sku" class="selected-line"><span>{{ productName(String(sku)) }}</span><strong>{{ qty }}개</strong></div><button v-if="orderItem.status !== 'CANCELLED' && orderItem.cancellable" class="secondary" :disabled="busy || !!connectionError" @click="cancel(orderItem.id)">이 주문 취소</button></article></section>
        <details class="panel detail-panel"><summary>작업 상세 보기</summary><p v-if="state?.mode === 'hardware'">실물 확인은 실행 결과와 별도입니다. 적재 {{ session.inventory.filter(i => i.physical_loading_confirmed).length }}개 · 하역 {{ session.inventory.filter(i => i.physical_delivery_confirmed).length }}개 확인</p><p>{{ task ? label(task.state) : label(session.state) }}</p><p v-if="task">{{ zoneName(task.zone_id) }} · {{ label(task.kind) }}</p><p v-if="task?.state === 'WAIT_ZONE'">다른 로봇의 구역 사용 또는 장비 연결을 기다립니다.</p><p v-if="task?.state === 'WAIT_BASKET'">관리자의 해당 고객 장바구니 준비 확인을 기다립니다.</p><small>갱신 {{ lastUpdate?.toLocaleTimeString('ko-KR') || '—' }}<template v-if="session.completed_at"> · 시연 흐름 완료 {{ timeText(session.completed_at) }}</template></small></details>

      </section>
    </template>
    <section v-else-if="!connectionError" class="panel empty-state" role="status">불러오는 중…</section>
  </main>
</template>
