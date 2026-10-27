<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import type { Session, Snapshot } from '../types'
import { label, shortId, timeText, zoneName } from '../api'
import SessionCard from './SessionCard.vue'
import { robotName } from './presentation'
const props = defineProps<{ state: Snapshot; busy: boolean }>()
defineEmits<{ ready: [session: Session, basketId: string] }>()
const route = useRoute(), router = useRouter()
const selected = computed(() => typeof route.query.customer === 'string' ? route.query.customer : '')
const sessions = computed(() => Object.values(props.state.sessions))
const visible = computed(() => sessions.value.filter(s => !selected.value || selected.value === s.id))
const orders = computed(() => Object.values(props.state.orders).filter(o => !selected.value || o.session_id === selected.value).reverse())
const tasks = computed(() => Object.values(props.state.tasks).filter(t => !selected.value || t.session_id === selected.value))
const commands = computed(() => Object.values(props.state.commands).filter(c => !selected.value || c.session_id === selected.value).reverse())
const productName = (sku: string) => props.state.products.find(p => p.sku === sku)?.name || sku
const customerName = (id: string) => props.state.sessions[id]?.label || shortId(id)
</script>

<template>
  <div class="filter-bar"><label for="order-customer">고객 선택</label><select id="order-customer" :value="selected" @change="router.replace({ query: { customer: ($event.target as HTMLSelectElement).value || undefined } })"><option value="">전체 고객</option><option v-for="s in sessions" :key="s.id" :value="s.id">{{ s.label }} · {{ robotName(s.robot_id) }}</option></select><small>{{ orders.length }}건의 주문</small></div>
  <section v-if="!visible.length" class="panel empty-state"><h3>{{ selected ? '고객 정보 없음' : '고객 없음' }}</h3><RouterLink class="button secondary" :to="selected ? '/admin/orders' : '/shop'">{{ selected ? '전체 고객 보기' : '고객 화면 보기' }}</RouterLink></section>
  <section class="session-grid"><SessionCard v-for="session in visible" :key="session.id" :session="session" :state="state" :busy="busy" @ready="(s, id) => $emit('ready', s, id)" /></section>
  <section v-if="visible.length" class="panel"><div class="section-title"><h2>주문 내역</h2><span class="pill">{{ orders.length }}건</span></div><p v-if="!orders.length" class="muted">주문 없음</p><article v-for="order in orders" :key="order.id" class="order-record"><div><strong>{{ customerName(order.session_id) }}</strong><small>{{ timeText(order.created_at) }} · {{ order.status === 'CANCELLED' ? '취소됨' : '접수됨' }}</small></div><div class="item-chips"><span v-for="(qty, sku) in order.items" :key="sku">{{ productName(String(sku)) }} <b>× {{ qty }}</b></span></div></article></section>
  <details v-if="visible.length" class="panel detail-panel"><summary>작업·명령 상세</summary>
    <h3>작업 순서와 실행 조건</h3><div class="table-scroll"><table><thead><tr><th>고객 / 작업</th><th>종류·구역</th><th>상태</th><th>정차 확인</th><th>팔 이탈</th><th>상품</th></tr></thead><tbody><tr v-for="t in tasks" :key="t.id"><td>{{ customerName(t.session_id) }}<small>{{ shortId(t.id) }}</small></td><td>{{ label(t.kind) }} / {{ zoneName(t.zone_id) }}</td><td>{{ label(t.state) }}</td><td>{{ timeText(t.stopped_at) }}</td><td>{{ t.arm_clear ? '확인' : '미확인' }}</td><td>{{ t.items.map(i => `${productName(i.sku)} [${i.slot + 1}]`).join(', ') || '—' }}</td></tr><tr v-if="!tasks.length"><td colspan="6">작업 없음</td></tr></tbody></table></div>
    <h3>명령 · 수락 · 결과</h3><div class="table-scroll"><table><thead><tr><th>명령</th><th>장비</th><th>상태</th><th>전송</th><th>수락</th><th>결과</th></tr></thead><tbody><tr v-for="c in commands" :key="c.id"><td>{{ label(c.kind) }}<small>{{ shortId(c.id) }}</small></td><td>{{ robotName(c.device_id) }}</td><td>{{ label(c.status) }}</td><td>{{ timeText(c.sent_at) }}</td><td>{{ timeText(c.accepted_at) }}</td><td>{{ c.result ? label(c.result.kind) : '확인되지 않음' }}</td></tr><tr v-if="!commands.length"><td colspan="6">명령 없음</td></tr></tbody></table></div>
  </details>
</template>
