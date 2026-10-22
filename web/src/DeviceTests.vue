<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, requestId, shortId, timeText, usePolling } from './api'
import type { Product } from './types'

type Trial = {
  id: string; request_id: string; node_id: string; device_id: string; kind: string; mode: string;
  parameters: Record<string, unknown>; status: string; created_at: number; sent_at: number | null;
  accepted_at: number | null; started_at: number | null; ended_at: number | null;
  stop_requested_at: number | null; stop_ack_at: number | null; released_at: number | null;
  stopped: { source: string } | null; observation: unknown; result: { kind: string; data: Record<string, unknown> } | null;
  review: unknown; timeline: { at: number; kind: string; data: Record<string, unknown> }[];
}
type Report = { online: boolean; allow_motion: boolean; operations: string[]; sides: string[]; issues: string[];
  checks: { name: string; state: string }[]; inspection: string; python?: string; slots?: Record<string, number[]>; revision?: {commit: string; modified: boolean | null} }
type State = { mode: string; test_only: boolean; distributed: boolean; hold: string | null;
  jobs: Record<string, Trial>; nodes: Record<string, Report>; server_time: number }
type Request = { node_id: string; kind: string; parameters: Record<string, unknown>; request_id: string; prepared: boolean; simulate_failure?: boolean }
const props = defineProps<{ token: string; products: Product[] }>()
const state = ref<State | null>(null)
const node = ref('gateway-a'), kind = ref('PING'), sku = ref(''), robot = ref('pinky-1'), slot = ref(0), side = ref('left')
const handoffSkus = ref<string[]>([]), prepared = ref(false), selected = ref('')
const simulateFailure = ref(false)
const operator = ref(sessionStorage.getItem('shopping.test.operator') || '')
const note = ref(''), stopped = ref(false), placed = ref(false), restored = ref(false), processClosed = ref(false)
const facts = ref({ cart_visible: false, cart_empty: false, last_item_placed: false, standby_reached: false })
const error = ref(''), message = ref(''), busy = ref(false), stopping = ref(false)
const pendingKey = 'shopping.test.pending'
function savedPending(): Request | null { try { return JSON.parse(sessionStorage.getItem(pendingKey) || 'null') } catch { return null } }
const pending = ref<Request | null>(savedPending())
const report = computed(() => state.value?.nodes[node.value])
const rows = computed(() => Object.values(state.value?.jobs || {}).filter(j => j.node_id === node.value).reverse())
const job = computed(() => state.value?.jobs[selected.value])
const stock = computed(() => props.products.filter(p => p.station === (node.value === 'gateway-b' ? 'load-b' : 'load-a')))
const motion = computed(() => kind.value === 'PICK' || kind.value === 'HANDOFF')
const final = (status: string) => ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(status)
const names: Record<string, string> = { PING: '통신 응답 확인', INSPECT: '설정 검사', PICK: '상품 1개 적재', HANDOFF: '바구니 하역',
  CREATED: '전송 대기', SENT: '중계에 전달 · 수락 대기', ACCEPTED: '중계 수락', RUNNING: '실행 중',
  WAIT_REVIEW: '실행 종료 · 결과 확인 대기', SUCCEEDED: '확인 완료', FAILED: '실패', CANCELLED: '취소·중단', UNCERTAIN: '결과 불명 · 정지 확인 필요',
  STARTED: '실행 시작', FINISHED: '실행 종료 보고', ERROR: '실행 오류', STOP_REQUESTED: '중지 요청', STOP_ACK: '중지 요청 수신',
  OPERATOR_OBSERVATION: '운영자 하역 관측', REVIEWED: '시험 결과 확인', RELEASED: '원위치 확인·시험 해제', TIMEOUT_OR_DISCONNECT: '시간 초과·통신 끊김' }
const name = (s: string) => names[s] || s
const { refresh, connectionError } = usePolling(async () => {
  state.value = await api<State>('/admin/device-tests', props.token)
  if (pending.value) {
    const existing = Object.values(state.value.jobs).find(j => j.request_id === pending.value!.request_id)
    if (existing) { selected.value = existing.id; pending.value = null; sessionStorage.removeItem(pendingKey) }
  }
})
void refresh()
function choose(id: string) {
  selected.value = id; stopped.value = placed.value = restored.value = processClosed.value = false; note.value = ''
  facts.value = { cart_visible: false, cart_empty: false, last_item_placed: false, standby_reached: false }
}
function changeNode() { kind.value = 'PING'; sku.value = ''; prepared.value = false; selected.value = ''; handoffSkus.value = [] }
async function send(retry = false) {
  if (busy.value) return
  error.value = ''; message.value = ''
  if (!retry && pending.value) { error.value = '응답이 확인되지 않은 이전 요청을 먼저 조회·재전송하세요.'; return }
  const body: Request = retry && pending.value ? pending.value : {
    node_id: node.value, kind: kind.value, request_id: requestId(), prepared: motion.value && prepared.value,
    simulate_failure: state.value?.mode === 'mock' && motion.value && simulateFailure.value,
    parameters: kind.value === 'PICK' ? { sku: sku.value, robot_id: robot.value, slot: slot.value }
      : kind.value === 'HANDOFF' ? { side: side.value, skus: handoffSkus.value } : {},
  }
  pending.value = body; sessionStorage.setItem(pendingKey, JSON.stringify(body)); busy.value = true
  try {
    const result = await api<Trial>('/admin/device-tests', props.token, body)
    choose(result.id); pending.value = null; sessionStorage.removeItem(pendingKey)
    message.value = '시험 요청을 등록했습니다. 중계 수락과 실행 결과를 확인하세요.'
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    // A definitive rejection can be corrected; a network timeout keeps the same request key.
    if (e && typeof e === 'object' && 'status' in e && Number(e.status) < 500) {
      pending.value = null; sessionStorage.removeItem(pendingKey)
    }
  } finally { busy.value = false; await refresh() }
}
async function action(path: string, body: unknown) {
  busy.value = true; error.value = ''; message.value = ''
  sessionStorage.setItem('shopping.test.operator', operator.value)
  try { await api(`/admin/device-tests/${selected.value}/${path}`, props.token, body); message.value = '기록했습니다.' }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false; await refresh() }
}
async function stop() {
  stopping.value = true; error.value = ''
  try { await api(`/admin/device-tests/${selected.value}/stop`, props.token, {}); message.value = '중지를 요청했습니다. 요청 수신과 실제 정지 확인은 별도입니다.' }
  catch (e) { error.value = String(e) }
  finally { stopping.value = false; await refresh() }
}
function review(success: boolean) {
  void action('review', { operator: operator.value, success, stopped: stopped.value, process_closed: processClosed.value, note: note.value })
}
function download() {
  if (!job.value) return
  const url = URL.createObjectURL(new Blob([JSON.stringify({ exported_at: new Date().toISOString(), trial: job.value }, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a'); a.href = url; a.download = `device-test-${job.value.id}.json`; a.click(); URL.revokeObjectURL(url)
}
function addSku(value: string) { if (value && handoffSkus.value.length < 3) handoffSkus.value.push(value) }
</script>

<template>
  <section class="test-bench">
    <div v-if="connectionError" class="alert danger" role="alert">{{ connectionError }} · 마지막 조회 상태입니다. 실제 정지로 해석하지 마세요.</div>
    <div v-if="error" class="alert danger" role="alert">{{ error }}</div>
    <div v-if="message" class="alert success" role="status">{{ message }}</div>
    <p v-if="state && !state.distributed" class="alert danger">분산 중계 모드로 서버를 실행해야 합니다. FIELD_SETUP.md의 실행 방법을 확인하세요.</p>
    <div class="panel">
      <div class="section-title"><h2>장비 테스트</h2><span class="pill">{{ state?.mode === 'hardware' ? '실물 장비 시험' : 'MOCK · 가상 시험' }}</span></div>
      <p>주문·재고와 별도로 기록합니다. 동작 시험은 실제 정지와 상품·작업 구역 복구를 확인할 때까지 주문 실행을 보류합니다.</p>
      <p v-if="state?.test_only" class="muted">시험 전용 서버 · 일반 주문 실행 비활성</p>
      <p v-if="state?.hold" class="alert danger">동작 시험 {{ shortId(state.hold) }} 점유 유지 <button class="secondary" @click="choose(state.hold)">해당 시험 보기</button></p>
      <div class="test-fields">
        <label>대상 중계<select v-model="node" @change="changeNode"><option value="gateway-a">A · YOLO 적재</option><option value="gateway-b">B · YOLO 적재</option><option value="gateway-c">C · ACT 하역</option></select></label>
        <label>시험 명령<select v-model="kind"><option value="PING">통신 응답 확인</option><option value="INSPECT">설정 검사</option><option v-if="node !== 'gateway-c'" value="PICK">상품 1개 적재</option><option v-else value="HANDOFF">바구니 하역</option></select></label>
      </div>
      <p><span class="status-dot" :class="{ online: report?.online }"></span>{{ report?.online ? '시험 실행부 응답 중' : '시험 실행부 응답 미확인' }} · 장치·카메라의 정상 동작 확인과 별도입니다.</p>
      <template v-if="report">
        <p class="muted">{{ report.inspection }} · Python {{ report.python || '미확인' }}</p>
        <p class="muted">코드 {{ report.revision?.commit || '미확인' }}{{ report.revision?.modified ? ' · 로컬 수정 있음' : '' }}</p>
        <ul v-if="report.issues?.length"><li v-for="issue in report.issues" :key="issue">{{ issue }}</li></ul>
        <p v-if="state?.mode === 'hardware' && !report.allow_motion">실물 동작 비활성 · 현장 설정 및 시험 실행부의 <code>--execute</code> 확인 필요</p>
        <table v-if="report.checks?.length"><thead><tr><th>검사 항목</th><th>확인 수준</th></tr></thead><tbody><tr v-for="check in report.checks" :key="check.name"><td>{{ check.name }}</td><td>{{ check.state }}</td></tr></tbody></table>
      </template>
      <div v-if="kind === 'PICK'" class="test-fields">
        <label>상품<select v-model="sku"><option value="" disabled>선택</option><option v-for="p in stock" :key="p.sku" :value="p.sku">{{ p.name }}</option></select></label>
        <label>바구니 배치<select v-model="robot"><option value="pinky-1">Pinky 1 기준</option><option value="pinky-2">Pinky 2 기준</option></select></label>
        <label>적재 위치<select v-model.number="slot"><option v-for="index in [0,1,2]" :key="index" :value="index" :disabled="state?.mode === 'hardware' && !report?.slots?.[robot]?.includes(index)">슬롯 {{ index + 1 }}{{ state?.mode === 'hardware' && !report?.slots?.[robot]?.includes(index) ? ' · 자세 미등록' : '' }}</option></select></label>
      </div>
      <template v-if="kind === 'HANDOFF'">
        <label>고객 장바구니 방향<select v-model="side"><option value="left">왼쪽 · ACT v2 5만</option><option value="right" :disabled="!report?.sides?.includes('right')">오른쪽 · {{ report?.sides?.includes('right') ? '실행부 등록 방향' : '모델 미등록' }}</option></select></label>
        <label>현재 카트 상품 (1~3개)<select :value="''" @change="addSku(($event.target as HTMLSelectElement).value)"><option value="">상품 추가</option><option v-for="p in products" :key="p.sku" :value="p.sku">{{ p.name }}</option></select></label>
        <div class="button-row"><button v-for="(item, i) in handoffSkus" :key="i" class="secondary" @click="handoffSkus.splice(i, 1)">{{ products.find(p => p.sku === item)?.name }} × 제거</button></div>
      </template>
      <label v-if="motion" class="check-line"><input v-model="prepared" type="checkbox" /> 바구니를 지정 위치에 고정하고 상품·작업 영역을 확인했습니다. Pinky 이동 명령은 보내지 않습니다.</label>
      <label v-if="motion && state?.mode === 'mock'" class="check-line"><input v-model="simulateFailure" type="checkbox" /> 이번 모의 동작에서 실패 응답 시험</label>
      <button class="primary" :disabled="busy || !!pending || !!connectionError || !state?.distributed || (motion && (!prepared || !report?.online || !report?.allow_motion || !!state?.hold))" @click="send()">{{ motion ? '선택한 동작 시험 요청' : '확인 요청' }}</button>
      <div v-if="pending" class="alert danger">이전 요청의 응답을 확인 중입니다. 같은 요청 ID로 재전송하면 중복 실행하지 않습니다. <button :disabled="busy" @click="send(true)">동일 요청 재전송</button></div>
    </div>

    <section class="panel table-scroll"><h2>시험 명령 목록</h2><table><thead><tr><th>명령 ID</th><th>시험</th><th>상태</th><th>요청 시각</th></tr></thead><tbody><tr v-for="item in rows" :key="item.id"><td><button class="secondary" @click="choose(item.id)">{{ shortId(item.id) }}</button></td><td>{{ name(item.kind) }}</td><td>{{ name(item.status) }}</td><td>{{ timeText(item.created_at) }}</td></tr></tbody></table><p v-if="!rows.length">이 중계의 시험 기록이 없습니다.</p></section>
    <section v-if="job" class="panel">
      <div class="section-title"><h2>{{ job.node_id }} · {{ name(job.kind) }}</h2><span class="pill">{{ name(job.status) }}</span></div>
      <p><code>{{ job.id }}</code> · {{ job.mode.toUpperCase() }}</p>
      <div class="test-stages"><div v-for="entry in [{title:'요청',at:job.created_at},{title:'전달',at:job.sent_at},{title:'수락',at:job.accepted_at},{title:'실행 시작',at:job.started_at},{title:'실행 종료',at:job.ended_at}]" :key="entry.title"><strong>{{ entry.title }}</strong><span>{{ timeText(entry.at) }}</span></div></div>
      <p>중지 요청 {{ timeText(job.stop_requested_at) }} → 요청 수신 {{ timeText(job.stop_ack_at) }} → 실제 정지 {{ job.stopped ? `확인 (${job.stopped.source})` : '미확인' }}</p>
      <div class="button-row"><button class="danger-button" :disabled="stopping || final(job.status)" @click="stop">{{ stopping ? '중지 요청 중' : '이 시험 중지 요청' }}</button><button class="secondary" @click="download">시험 로그 JSON 저장</button></div>
      <p class="muted">화면의 중지 버튼은 소프트웨어 요청입니다. 수락 응답만으로 실제 정지를 표시하지 않습니다.</p>
      <template v-if="['PICK','HANDOFF'].includes(job.kind)">
        <label>확인자<input v-model="operator" maxlength="80" placeholder="이름 또는 팀 내 식별값" /></label>
        <fieldset v-if="job.kind === 'HANDOFF' && job.status === 'RUNNING' && !job.stop_requested_at"><legend>하역 완료 조건 관측</legend>
          <label class="check-line"><input v-model="facts.cart_visible" type="checkbox" /> 카트 내부가 보입니다</label>
          <label class="check-line"><input v-model="facts.cart_empty" type="checkbox" /> 카트가 비었습니다</label>
          <label class="check-line"><input v-model="facts.last_item_placed" type="checkbox" /> 마지막 물건이 지정한 좌우 장바구니 안에 놓였습니다</label>
          <label class="check-line"><input v-model="facts.standby_reached" type="checkbox" /> 팔이 대기 자세로 돌아왔습니다</label>
          <button :disabled="busy || !operator.trim() || !Object.values(facts).every(Boolean)" @click="action('observe', {operator, facts})">운영자 관측 전달</button>
          <p class="muted">실행부가 관측을 받은 뒤 ACT 대기 자세·정지 피드백을 확인합니다. 관측은 2초 이내 사용하며, 놓쳤다면 현재 상태를 다시 확인해 전달하세요.</p>
        </fieldset>
        <fieldset v-if="['WAIT_REVIEW','UNCERTAIN'].includes(job.status)"><legend>시험 결과 확인 · 자동 성공 판정 아님</legend>
          <label class="check-line"><input v-model="stopped" type="checkbox" /> 로봇의 실제 정지를 확인했습니다</label>
          <label class="check-line"><input v-model="placed" type="checkbox" /> 지정 상품이 선택한 슬롯 또는 좌우 장바구니에 놓인 것을 확인했습니다</label>
          <label v-if="job.status === 'UNCERTAIN'" class="check-line"><input v-model="processClosed" type="checkbox" /> 원래 시험 실행부를 종료했고 재실행되지 않음을 확인했습니다</label>
          <label>결과 메모<textarea v-model="note" maxlength="500" placeholder="실제로 확인한 결과나 실패 원인" /></label>
          <div class="button-row"><button :disabled="busy || !operator.trim() || !note.trim() || !stopped || !placed || job.status === 'UNCERTAIN' || job.result?.kind !== 'FINISHED' || !!job.stop_requested_at" @click="review(true)">작업 성공 확인 기록</button><button class="secondary" :disabled="busy || !operator.trim() || !note.trim() || !stopped" @click="review(false)">실패·중단 확인 기록</button></div>
        </fieldset>
        <fieldset v-if="state?.hold === job.id && final(job.status)"><legend>시험 종료 후 원위치 확인</legend><label class="check-line"><input v-model="restored" type="checkbox" /> 실제 상품 수량·원위치와 작업 구역을 복구했습니다</label><button :disabled="busy || !restored || !operator.trim()" @click="action('release', {operator, restored})">시험 점유 해제</button></fieldset>
      </template>
      <h3>명령·응답 타임라인</h3>
      <ol class="test-timeline"><li v-for="(entry, i) in job.timeline" :key="i"><strong>{{ timeText(entry.at) }} · {{ name(entry.kind) }}</strong><details><summary>상세 데이터</summary><pre>{{ JSON.stringify(entry.data, null, 2) }}</pre></details></li></ol>
      <details><summary>요청·결과 전체 보기</summary><pre>{{ JSON.stringify(job, null, 2) }}</pre></details>
    </section>
  </section>
</template>

<style scoped>
.test-bench { display: grid; gap: 18px; }
.test-fields { display: flex; flex-wrap: wrap; gap: 16px; margin: 12px 0; }
.test-fields label { flex: 1; min-width: 180px; }
.check-line { display: flex; align-items: flex-start; gap: 10px; margin: 14px 0; }
.check-line input { width: 18px; height: 18px; flex: 0 0 auto; margin: 2px 0; }
.test-stages { display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0; }
.test-stages div { display: grid; gap: 6px; padding: 12px 18px; background: #edf4f8; border-radius: 8px; }
fieldset { border: 1px solid #cbd5e1; border-radius: 8px; margin: 18px 0; padding: 16px; }
textarea { width: 100%; min-height: 76px; }
.test-timeline { padding-left: 22px; }
.test-timeline li { margin: 12px 0; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f1f5f9; padding: 12px; max-height: 380px; overflow: auto; }
</style>
