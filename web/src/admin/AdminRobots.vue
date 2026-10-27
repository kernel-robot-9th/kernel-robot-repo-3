<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import type { Snapshot } from '../types'
import { label, timeText } from '../api'
import VideoWall from '../VideoWall.vue'
import RoadControl from '../RoadControl.vue'
import PinkyMotion from '../PinkyMotion.vue'
import FieldMotion from '../FieldMotion.vue'
import Icon from '../ui/Icon.vue'
import { omxStations } from './navigation'
import { nodeOnline, robotName } from './presentation'
const props = defineProps<{ state: Snapshot; token: string; kind: 'omx' | 'pinky' }>()
const emit = defineEmits<{ tests: []; overview: [] }>()
const route = useRoute()
const detail = computed(() => String(route.params.detail || ''))
const station = computed(() => omxStations.find(s => s.id === detail.value) || omxStations[0]!)
const tasks = computed(() => Object.values(props.state.tasks).filter(t => t.zone_id === station.value.id && props.state.sessions[t.session_id]?.current_task === t.id))
const robotSessions = computed(() => Object.values(props.state.sessions).filter(s => s.robot_id === detail.value))
const robotTask = computed(() => robotSessions.value.find(s => s.current_task))
const productName = (sku: string) => props.state.products.find(p => p.sku === sku)?.name || sku
</script>

<template>
  <template v-if="kind === 'omx'">
    <div class="robot-toolbar"><nav class="segment-tabs" aria-label="OMX 장비 선택"><RouterLink v-for="s in omxStations" :key="s.id" :to="'/admin/omx/' + s.id" :aria-current="detail === s.id ? 'page' : undefined"><Icon name="arm" :size="18" />{{ s.name }}</RouterLink></nav>
    <div class="robot-status"><span class="pill" :class="{bad: !state.devices?.[station.device]?.connected}">{{ state.devices?.[station.device]?.connected ? '통신 연결' : '연결 대기' }}</span></div></div>
    <div class="robot-workspace"><section aria-label="OMX 작업 영상"><VideoWall :key="station.id" :token="token" :feed-ids="station.feeds" /></section>
      <aside class="panel work-context"><div class="section-title"><h2>현재 작업</h2><Icon name="orders" /></div><template v-if="tasks.length"><article v-for="task in tasks" :key="task.id" class="work-item"><span class="pill">{{ label(task.state) }}</span><h3>{{ state.sessions[task.session_id]?.label || '고객 확인 필요' }}</h3><p>{{ robotName(task.robot_id) }} · {{ label(task.kind) }}</p><div class="item-chips"><span v-for="item in task.items" :key="item.item_id">{{ productName(item.sku) }} · 위치 {{ item.slot + 1 }}</span></div><RouterLink class="text-link" :to="{path:'/admin/orders', query:{customer:task.session_id}}">주문 상세 <Icon name="arrow" :size="16" /></RouterLink></article></template><div v-else class="context-empty"><Icon name="clock" :size="28" /><h3>작업 없음</h3></div>
      <div class="context-footer"><span>담당 중계</span><strong>중계 {{ station.node.slice(-1).toUpperCase() }}</strong><small>{{ nodeOnline(state, station.node) ? '통신 연결' : '연결 대기' }}</small><RouterLink class="button secondary" to="/admin/tests">장비 테스트 <Icon name="arrow" :size="16" /></RouterLink></div></aside>
    </div>
    <details class="panel detail-panel"><summary>장비·동작 상세</summary><p>통신 연결과 실제 동작 준비는 별도 상태입니다. 장치·보정·작업 영역은 장비 테스트에서 확인합니다.</p><p v-if="station.id === 'handoff'">왼쪽 ACT v2 5만 스텝 모델 기준입니다. 오른쪽은 현장 실행부에 등록된 방향만 시험할 수 있습니다. 정책 종료·실제 정지·팔 이탈을 구분합니다.</p><p v-else>YOLO는 상품 인식에 사용하며, 집기·놓기는 보정된 궤적으로 수행합니다. 실제 적재 결과는 별도 관측으로 확인합니다.</p></details>
  </template>
  <template v-else>
    <nav class="segment-tabs" aria-label="Pinky 화면 선택"><RouterLink to="/admin/pinky/movement"><Icon name="grid" :size="18" />이동 현황</RouterLink><RouterLink v-for="id in ['pinky-1','pinky-2']" :key="id" :to="'/admin/pinky/' + id"><Icon name="robot" :size="18" />{{ robotName(id) }}</RouterLink></nav>
    <template v-if="detail === 'movement'">
      <FieldMotion v-if="state.mode === 'hardware'" :state="state" :token="token" @tests="emit('tests')" />
      <RoadControl v-else-if="state.route_version === 4" :token="token" @overview="emit('overview')" />
      <PinkyMotion v-else :token="token" />
    </template>
    <template v-else>
      <div class="robot-status"><span class="pill" :class="{bad: !state.devices?.[detail]?.connected}">{{ state.devices?.[detail]?.connected ? '통신 연결' : '연결 대기' }}</span></div>
      <div class="robot-workspace"><section class="panel"><div class="section-title"><h2>관련 영상</h2></div><div class="empty-state pinky-video-empty"><span class="empty-icon"><Icon name="camera" :size="32" /></span><h3>영상 미등록</h3><RouterLink class="button secondary" to="/admin/video">전체 영상 <Icon name="arrow" :size="16" /></RouterLink></div></section>
      <aside class="panel work-context"><h2>현재 운반 작업</h2><template v-if="robotTask"><h3>{{ robotTask.label }}</h3><span class="pill">{{ label(state.tasks[robotTask.current_task!]?.state || robotTask.state) }}</span><div class="metrics"><article><span>현재 카트</span><strong>{{ robotTask.inventory.filter(i => !i.delivered).length }}</strong></article><article><span>인계 실행</span><strong>{{ robotTask.inventory.filter(i => i.delivered).length }}</strong></article></div><p v-if="robotTask.active_trip">{{ state.trips[robotTask.active_trip]?.number }}차 운반</p><RouterLink class="text-link" :to="{path:'/admin/orders',query:{customer:robotTask.id}}">주문 상세 <Icon name="arrow" :size="16" /></RouterLink></template><div v-else class="context-empty"><Icon name="robot" :size="30" /><h3>작업 없음</h3></div><div class="context-footer"><span>이동 지도·제어</span><RouterLink class="button secondary" to="/admin/pinky/movement">이동 현황 <Icon name="arrow" :size="16" /></RouterLink></div></aside></div>
      <section class="panel"><h2>고객 배정 이력</h2><p v-if="!robotSessions.length" class="muted">배정 이력 없음</p><div v-for="s in robotSessions" :key="s.id" class="order-record"><strong>{{ s.label }}</strong><span>{{ label(s.state) }}</span><small>{{ timeText(s.created_at) }}</small><RouterLink class="text-link" :to="{path:'/admin/orders',query:{customer:s.id}}">주문 보기</RouterLink></div></section>
    </template>
  </template>
</template>
