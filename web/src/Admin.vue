<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, label, shortId, timeText, usePolling, zoneName } from './api'
import type { Audit, Session, Snapshot, Task } from './types'

const token = ref(sessionStorage.getItem('shopping.admin.token') || '')
const tokenInput = ref('')
const state = ref<Snapshot | null>(null)
const logs = ref<Audit[]>([])
const tab = ref('overview')
const error = ref('')
const message = ref('')
const busy = ref(false)
const device = ref('omx-a')
const basketInputs = ref<Record<string, string>>({})
const selectedSession = ref('')
const sessions = computed(() => Object.values(state.value?.sessions || {}))
const tasks = computed(() => Object.values(state.value?.tasks || {}).filter(t => !selectedSession.value || t.session_id === selectedSession.value))
const commands = computed(() => Object.values(state.value?.commands || {}).filter(c => !selectedSession.value || c.session_id === selectedSession.value).reverse())
const connectedNodes = computed(() => Object.values(state.value?.gateways || {}).filter(n => n.connected && n.heartbeat_at !== null && (state.value!.server_time - n.heartbeat_at) < 10).length)
const visibleLogs = computed(() => logs.value.filter(l => !selectedSession.value || l.session_id === selectedSession.value))
const currentTask = (s: Session): Task | undefined => s.current_task ? state.value?.tasks[s.current_task] : undefined
const customerName = (sid: string | null) => sid ? state.value?.sessions[sid]?.label || shortId(sid) : '—'
const ordered = (sid: string) => Object.values(state.value?.orders || {}).filter(o => o.session_id === sid)
  .reduce((total, order) => total + Object.values(order.items).reduce((a, b) => a + b, 0), 0)
const { refresh, connectionError, lastUpdate } = usePolling(async () => {
  if (!token.value) return
  state.value = await api<Snapshot>('/admin/state', token.value)
  if (tab.value === 'history') logs.value = (await api<{ items: Audit[] }>('/admin/logs', token.value)).items
})
async function login() {
  error.value = ''
  try {
    state.value = await api<Snapshot>('/admin/state', tokenInput.value)
    token.value = tokenInput.value; tokenInput.value = ''
    sessionStorage.setItem('shopping.admin.token', token.value)
    await refresh()
  } catch (e) { error.value = e instanceof Error ? e.message : '인증 실패' }
}
function logout() { token.value = ''; state.value = null; sessionStorage.removeItem('shopping.admin.token') }
async function act(path: string, body: unknown, success: string) {
  if (busy.value) return
  busy.value = true; error.value = ''; message.value = ''
  try { await api(path, token.value, body); message.value = success; await refresh() }
  catch (e) { error.value = e instanceof Error ? e.message : '처리 실패' }
  finally { busy.value = false }
}
function ready(s: Session) {
  const basketId = basketInputs.value[s.id]?.trim()
  if (!basketId || !s.current_task) return
  if (!window.confirm(`${s.label} · ${s.robot_id}의 고객 장바구니 ${basketId}가 인계 위치에 준비됐습니까?`)) return
  void act('/admin/basket-ready', { session_id: s.id, task_id: s.current_task, basket_id: basketId }, '고객·작업에 연결된 장바구니 준비를 기록했습니다.')
}
function resetRun() {
  if (!window.confirm('새 모의 실행을 시작할까요? 현재 가상 상태·고객 세션은 종료되고 이전 기록은 DB에 보관됩니다. 실제 장비에는 사용할 수 없습니다.')) return
  selectedSession.value = ''; basketInputs.value = {}
  void act('/admin/mock/new-run', {}, '새 모의 실행을 만들었습니다. 고객도 새 세션을 시작해야 합니다.')
}
onMounted(refresh)
</script>

<template>
  <main class="admin-page">
    <div class="page-heading horizontal"><div><p class="eyebrow">OPERATIONS</p><h1>로봇 작업 관제</h1><p>고객·장비·공유 구역의 상태를 함께 확인합니다.</p></div><button v-if="token" class="secondary" @click="logout">관리자 로그아웃</button></div>
    <div v-if="error" class="alert danger" role="alert">{{ error }}</div>
    <div v-if="message" class="alert success" role="status">{{ message }}</div>
    <div v-if="connectionError" class="alert danger" role="alert">연결 상태 미확인 · {{ connectionError }}<p>아래 내용은 마지막 조회 상태입니다. 로봇 정지나 작업 완료를 의미하지 않습니다.</p></div>
    <form v-if="!token" class="panel login" @submit.prevent="login"><h2>관리자 인증</h2><label for="admin-token">개발용 관리자 토큰</label><input id="admin-token" v-model="tokenInput" type="password" autocomplete="off" required /><button class="primary">관제 열기</button><small>Ubuntu 설치 과정에서 생성한 SHOP_ADMIN_TOKEN을 사용합니다.</small></form>
    <template v-else-if="state">
      <div class="run-bar"><span v-if="state.gateway_mode === 'distributed'">분산 모의 실행 · 중개 {{ connectedNodes }}/3 연결</span><span v-else><span class="status-dot" :class="{ online: state.heartbeat_at !== null && state.server_time - state.heartbeat_at < 10 }"></span>모의 연결 프로그램 {{ state.heartbeat_at !== null && state.server_time - state.heartbeat_at < 10 ? '연결됨' : '대기·끊김' }}</span><span>실행 {{ shortId(state.run_id) }}</span><span>갱신 {{ lastUpdate?.toLocaleTimeString('ko-KR') || '—' }}</span></div>
      <section v-if="state.gateways" class="gateway-grid"><article v-for="(node, id) in state.gateways" :key="id" class="panel"><div class="section-title"><h2>{{ node.label }}</h2><span class="pill" :class="{bad: !node.connected || node.heartbeat_at === null || state.server_time - node.heartbeat_at >= 10}">{{ node.connected && node.heartbeat_at !== null && state.server_time - node.heartbeat_at < 10 ? '연결됨' : '연결 미확인' }}</span></div><p>{{ id }} · MOCK</p><p class="muted">{{ node.devices.join(' · ') }}</p><small>마지막 연결 {{ timeText(node.heartbeat_at) }}</small><p class="muted">{{ node.capabilities.includes('overview-observation') ? '전경 카메라·디지털 트윈 연결 예정' : node.capabilities.includes('handoff') ? '실제 모방학습 정책 연결 예정' : '실제 YOLO·이동 장비 연결 예정' }}</p></article></section>
      <nav class="tabs" aria-label="관리자 메뉴"><button v-for="item in [{id:'overview',name:'관제 현황'},{id:'tasks',name:'주문·작업'},{id:'devices',name:'장비·구역'},{id:'history',name:'작업 이력'}]" :key="item.id" :class="{active: tab === item.id}" @click="tab = item.id; refresh()">{{ item.name }}</button></nav>
      <section class="simulation-controls panel"><div><strong>모의 장비 단계 실행</strong><small>전송 → 수락 → 결과 → 별도 관측을 구분해 진행합니다.</small></div><div class="button-row"><button :disabled="busy" @click="act('/admin/mock/steps', {count:1}, '모의 단계 1회를 요청했습니다.')">1단계</button><button :disabled="busy" @click="act('/admin/mock/steps', {count:20}, '최대 20단계를 요청했습니다. 준비 조건이 없으면 대기합니다.')">20단계 진행</button><span class="muted">잔여 {{ state.permits || 0 }}</span></div></section>
      <template v-if="tab === 'overview'">
        <section class="zone-grid"><article v-for="(zone, id) in state.zones" :key="id" class="zone-card" :class="{occupied: zone.owner}"><small>공유 작업 구역</small><h2>{{ zoneName(String(id)) }}</h2><strong>{{ zone.owner ? customerName(state.tasks[zone.owner]?.session_id || null) : '비어 있음' }}</strong><p>{{ zone.owner ? state.tasks[zone.owner]?.robot_id : '진입 가능' }} · 대기 {{ zone.queue?.length || 0 }}건</p><span class="pill">{{ zone.owner ? '사용 허가·점유 유지' : '미점유' }}</span></article></section>
        <div class="section-title"><h2>고객별 진행 상황</h2><span class="muted">수량은 모의 장비의 확인된 결과만 반영</span></div>
        <p v-if="!sessions.length" class="panel muted">고객 화면에서 두 개의 쇼핑 세션을 시작하세요.</p>
        <section class="session-grid"><article v-for="s in sessions" :key="s.id" class="panel session-card"><div class="section-title"><h2>{{ s.label }}</h2><span class="pill" :class="{bad: s.error}">{{ label(s.state) }}</span></div><p class="robot-name">{{ s.robot_id }} <small>고객 {{ shortId(s.id) }}</small></p>
          <div class="metrics"><article><span>주문</span><strong>{{ ordered(s.id) }}</strong></article><article><span>적재 확인</span><strong>{{ s.inventory.length }}</strong></article><article><span>인계 확인</span><strong>{{ s.inventory.filter(i => i.delivered).length }}</strong></article></div>
          <p class="current-stage">{{ currentTask(s) ? label(currentTask(s)!.state) : label(s.state) }}</p><p v-if="currentTask(s)" class="muted">{{ zoneName(currentTask(s)!.zone_id) }} · 작업 {{ shortId(s.current_task) }}</p>
          <div v-if="s.error" class="alert danger">{{ s.error }}<p>중단 요청의 도달·실제 정지는 별도 확인 대상입니다.</p></div>
          <div v-if="currentTask(s)?.kind === 'HANDOFF' && ['MOVING','WAIT_STOP','WAIT_BASKET'].includes(currentTask(s)!.state) && !s.error" class="basket-confirm"><label :for="'basket-' + s.id">{{ s.label }} 고객 장바구니 식별값</label><small>배정값: {{ s.basket_id }}</small><input :id="'basket-' + s.id" v-model="basketInputs[s.id]" placeholder="해당 고객 장바구니 식별값 입력" maxlength="80" /><button :disabled="busy || !basketInputs[s.id]?.trim()" @click="ready(s)">이 고객 장바구니 준비 확인</button><small>실제 장바구니 표시와 대조한 후 확인하세요. 센서 인식 결과가 아닌 운영자 확인입니다.</small></div>
          <p v-if="s.state === 'COMPLETED'" class="muted">상품 인계 완료 {{ timeText(s.completed_at) }} · {{ s.current_task ? '로봇 구역 이탈 대기' : '로봇 배정 해제됨' }}</p>
        </article></section>
      </template>
      <template v-if="tab === 'tasks' || tab === 'history'"><label for="session-filter">고객 필터</label><select id="session-filter" v-model="selectedSession"><option value="">전체 고객</option><option v-for="s in sessions" :key="s.id" :value="s.id">{{ s.label }} · {{ shortId(s.id) }}</option></select></template>
      <template v-if="tab === 'tasks'">
        <section class="panel table-panel"><h2>작업 순서와 실행 조건</h2><div class="table-scroll"><table><thead><tr><th>고객 / 작업</th><th>종류·구역</th><th>상태</th><th>정차 확인</th><th>팔 이탈</th><th>대상</th></tr></thead><tbody><tr v-for="t in tasks" :key="t.id"><td>{{ customerName(t.session_id) }}<small>{{ shortId(t.id) }}</small></td><td>{{ label(t.kind) }} / {{ zoneName(t.zone_id) }}</td><td>{{ label(t.state) }}</td><td>{{ timeText(t.stopped_at) }}</td><td>{{ t.arm_clear ? '확인' : '미확인' }}</td><td>{{ t.items.map(i => `${i.sku} [${i.slot}]`).join(', ') }}</td></tr></tbody></table></div></section>
        <section class="panel table-panel"><h2>명령 · 수락 · 결과</h2><div class="table-scroll"><table><thead><tr><th>명령</th><th>장비</th><th>상태</th><th>전송</th><th>수락</th><th>결과</th></tr></thead><tbody><tr v-for="c in commands" :key="c.id"><td>{{ label(c.kind) }}<small>{{ shortId(c.id) }}</small></td><td>{{ c.device_id }}</td><td>{{ label(c.status) }}</td><td>{{ timeText(c.sent_at) }}</td><td>{{ timeText(c.accepted_at) }}</td><td>{{ c.result ? label(c.result.kind) : '확인되지 않음' }}</td></tr></tbody></table></div></section>
      </template>
      <template v-if="tab === 'devices'">
        <section class="device-grid"><article v-for="(value, id) in state.devices" :key="id" class="panel"><span class="pill">MOCK</span><h2>{{ id }}</h2><p><span class="status-dot" :class="{online:value.connected}"></span>{{ value.connected ? '연결됨' : '연결 미확인·끊김' }}</p></article></section>
        <section class="panel"><h2>모의 오류 주입</h2><p>연결이 복구돼도 오류 작업을 자동 재실행하지 않습니다.</p><label for="device">대상 장비</label><select id="device" v-model="device"><option v-for="(_, id) in state.devices" :key="id" :value="id">{{ id }}</option></select><div class="button-row"><button :disabled="busy || device.startsWith('pinky')" @click="act('/admin/mock/fault',{device_id:device,kind:'PICK_FAIL'},'선택한 팔의 다음 집기·인계 작업에 실패를 주입합니다.')">다음 집기·인계 실패</button><button class="danger-button" :disabled="busy" @click="act('/admin/mock/fault',{device_id:device,kind:'DISCONNECT'},'모의 통신 끊김을 기록했습니다.')">통신 끊김</button></div></section>
        <section class="panel"><h2>새 모의 실행</h2><p>오류·재시작 시험 후 가상 상태를 새로 만듭니다. 기존 실행 기록은 DB에 보관됩니다. 실제 장비 복구 기능은 아직 제공하지 않습니다.</p><button :disabled="busy" class="secondary" @click="resetRun">이전 실행 보관 후 새로 시작</button></section>
      </template>
      <section v-if="tab === 'history'" class="panel table-panel"><h2>작업 이력 <small>현재 실행 최근 200건</small></h2><div class="table-scroll"><table><thead><tr><th>시각</th><th>고객</th><th>이벤트</th><th>명령</th><th>상세</th></tr></thead><tbody><tr v-for="entry in visibleLogs" :key="entry.seq"><td>{{ timeText(entry.at) }}<small>{{ entry.mode }}</small></td><td>{{ customerName(entry.session_id) }}</td><td>{{ entry.kind }}</td><td>{{ shortId(entry.command_id) }}</td><td><code>{{ JSON.stringify(entry.detail) }}</code></td></tr></tbody></table></div></section>
    </template>
  </main>
</template>
