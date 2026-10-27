<script setup lang="ts">
import type { Snapshot } from '../types'
import { zoneName } from '../api'
defineProps<{ state: Snapshot }>()
const stockLabel = (available: number | null) => available === null ? '확인 필요' : available === 0 ? '주문 불가' : '주문 가능'
// The server remains the source of truth for all stock quantities.
</script>

<template>
  <section class="panel table-panel"><div class="table-toolbar"><span class="pill">{{ state.products.length }}종</span></div>

    <div class="table-scroll"><table><thead><tr><th>상품</th><th>적재 구역</th><th>선반 수량</th><th>예약 수량</th><th>주문 가능</th><th>상태</th></tr></thead><tbody><tr v-for="p in state.products" :key="p.sku"><td><strong>{{ p.name }}</strong><small>{{ p.sku }}</small></td><td>{{ zoneName(p.station) }}</td><td>{{ p.stock?.on_hand ?? '확인 필요' }}</td><td>{{ p.stock?.reserved ?? '—' }}</td><td><strong>{{ p.available ?? '—' }}</strong></td><td><span class="pill" :class="{ bad: p.available === 0 }">{{ stockLabel(p.available) }}</span></td></tr></tbody></table></div>

  </section>
</template>
