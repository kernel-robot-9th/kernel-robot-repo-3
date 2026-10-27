<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, requestId, shortId, timeText, usePolling } from './api'
type Pose = [number, number, number]
type Segment = { name: string; direction: number; poses: Pose[] }
type Route = { duration: number; start: Pose; end: Pose; segments: Segment[] }
type MapData = { route_version: number; frame_id: string; source_hash: string; routes: Record<string, Route>;
  edges: Pose[][]; layout: { width: number; depth: number; station_widths: number[]; station_depth: number };
  body_front: number; body_rear: number; body_width: number }
type Sample = { pose: Pose; progress: number; sim_time: number; observed_at: number; received_at: number;
  age_seconds: number | null; halted: boolean; sequence: number; observation_source: string }
type Trial = { id: string; request_id: string; robot_id: string; kind: string; status: string; parameters: {route_id: string; rate: number};
  telemetry: Sample | null; sent_at: number | null; accepted_at: number | null; started_at: number | null;
  stop_requested_at: number | null; stop_ack_at: number | null; stopped: unknown; released_at: number | null;
  timeline: {at: number; kind: string; data: Record<string, unknown>}[]; result: unknown }
type State = {mode: string; hold: string | null; distributed: boolean; jobs: Record<string, Trial>;
  nodes: Record<string, {online: boolean; allow_motion: boolean; motion_backend?: string; source_hash?: string}> }
type Request = { node_id: string; kind: string; parameters: {robot_id: string; route_id: string; rate: number};
  request_id: string; prepared: boolean; simulate_failure: boolean }
const props = defineProps<{token: string}>()
const map = ref<MapData | null>(null), state = ref<State | null>(null)
const routeId = ref('home_to_A'), robot = ref('pinky-1'), rate = ref(4), fail = ref(false)
const selected = ref(''), busy = ref(false), error = ref(''), operator = ref(''), closed = ref(false)
let initializedSelection = false
const pendingKey = 'shopping.motion.pending'
function saved(): Request | null { try { return JSON.parse(sessionStorage.getItem(pendingKey) || 'null') } catch { return null } }
const pending = ref<Request | null>(saved())
const rows = computed(() => Object.values(state.value?.jobs || {}).filter(j => j.kind === 'NAVIGATE').reverse())
const job = computed(() => rows.value.find(j => j.id === selected.value))
const shownRoute = computed(() => map.value?.routes[job.value?.parameters.route_id || routeId.value])
const sample = computed(() => job.value?.telemetry)
const pose = computed<Pose | undefined>(() => sample.value?.pose || shownRoute.value?.start)
const final = (s: string) => ['SUCCEEDED', 'FAILED', 'CANCELLED'].includes(s)
const stale = computed(() => !!sample.value && !final(job.value?.status || '') &&
  (sample.value.age_seconds === null || sample.value.age_seconds > 3 || !!connectionError.value))
const ready = computed(() => {
  const n = state.value?.nodes['gateway-a']
  return state.value?.mode === 'mock' && state.value.distributed && n?.online && n.allow_motion &&
    n.motion_backend === 'reference_path' && n.source_hash === map.value?.source_hash
})
const names: Record<string, string> = {
  CREATED:'전송 대기', SENT:'전송됨', ACCEPTED:'수락됨', RUNNING:'이동 중', SUCCEEDED:'모의 도착 확인',
  FAILED:'이동 실패', CANCELLED:'취소·중단', UNCERTAIN:'결과 불명 · 확인 필요', STARTED:'실행 시작',
  STOP_REQUESTED:'중지 요청', STOP_ACK:'중지 요청 수신', PROGRESS:'위치 수신', FINISHED:'도착·정지 보고',
  ERROR:'실패·중단 보고', RELEASED:'시험 해제', TIMEOUT_OR_DISCONNECT:'시간 초과·관측 만료·통신 끊김',
}
const routeName = (key: string) => key.replace('queue_advance', '대기 후열 → 선두').replace('home_to_', '대기 선두 → ')
  .replace('_to_home_back', ' → 대기 후열').replace('_to_home_front', ' → 대기 선두').replace('_to_', ' → ')
  .replaceAll('handoff', '인계').replace(/\bA\b/g, '적재 A').replace(/\bB\b/g, '적재 B')
const points = (poses: Pose[]) => poses.map(p => `${p[0] * 500},${-p[1] * 500}`).join(' ')
const transform = computed(() => pose.value ? `translate(${pose.value[0]*500} ${-pose.value[1]*500}) rotate(${-pose.value[2]*180/Math.PI})` : '')
const {refresh, connectionError} = usePolling(async () => {
  if (!map.value) map.value = await api<MapData>('/admin/motion-map', props.token)
  state.value = await api<State>('/admin/device-tests', props.token)
  if (pending.value) {
    const found = rows.value.find(j => j.request_id === pending.value!.request_id)
    if (found) { selected.value = found.id; pending.value = null; sessionStorage.removeItem(pendingKey) }
  }
  if (!initializedSelection) {
    if (!selected.value && rows.value.length) selected.value = rows.value[0]!.id
    initializedSelection = true
  }
})
void refresh()
async function send(retry = false) {
  if (busy.value || (pending.value && !retry)) return
  const body: Request = retry && pending.value ? pending.value : {
    node_id:'gateway-a', kind:'NAVIGATE', parameters:{robot_id:robot.value, route_id:routeId.value, rate:rate.value},
    request_id:requestId(), prepared:true, simulate_failure:fail.value,
  }
  pending.value = body; sessionStorage.setItem(pendingKey, JSON.stringify(body))
  busy.value = true; error.value = ''
  try {
    const created = await api<Trial>('/admin/device-tests', props.token, body)
    selected.value = created.id; pending.value = null; sessionStorage.removeItem(pendingKey)
  } catch (e) { error.value = e instanceof Error ? e.message : '요청 실패' }
  finally { busy.value = false; await refresh() }
}
async function action(actionName: string, body: unknown = {}) {
  if (!job.value || busy.value) return
  busy.value = true; error.value = ''
  try { await api('/admin/device-tests/' + job.value.id + '/' + actionName, props.token, body) }
  catch (e) { error.value = e instanceof Error ? e.message : '처리 실패' }
  finally { busy.value = false; await refresh() }
}
function exportLog() {
  if (!job.value) return
  const blob = new Blob([JSON.stringify({map: {route_version:map.value?.route_version, source_hash:map.value?.source_hash},
    physical_hardware_verified:false, trial:job.value}, null, 2)], {type:'application/json'})
  const url = URL.createObjectURL(blob), a = document.createElement('a')
  a.href = url; a.download = 'pinky-motion-' + shortId(job.value.id) + '.json'; a.click(); URL.revokeObjectURL(url)
}
function clearPending() {
  if (!window.confirm('먼저 시험 이력에 등록됐는지 확인하세요. 미확인 요청을 해제하고 새 요청을 준비할까요?')) return
  pending.value = null; sessionStorage.removeItem(pendingKey)
}
</script>

<template>
  <section class="pinky-motion">
    <div class="section-title"><h2>이동 시험</h2><span class="pill">모의 · v3</span></div>

    <div v-if="error || connectionError" class="alert danger" role="alert">{{ error || connectionError }}<p>마지막 위치 · 정지 미확인</p></div>
    <div class="motion-grid">
      <article class="panel motion-map">
        <div class="section-title"><strong>{{ shownRoute ? routeName(job?.parameters.route_id || routeId) : '도로 불러오는 중' }}</strong><span class="pill" :class="{bad: stale}">{{ stale ? '위치 갱신 없음' : sample ? (final(job?.status || '') ? '시험 마지막 위치' : '모의 위치 수신') : '시작 위치 미리보기' }}</span></div>
        <svg v-if="map" viewBox="-55 -55 1110 865" role="img" aria-label="도로 v3 지도와 Pinky 바구니 위치">
          <rect width="1000" height="750" rx="8" fill="#f3f6f2" stroke="#8b9d92" stroke-width="5"/>
          <rect x="0" y="0" width="300" height="375" fill="#e0ece7"/><rect x="300" y="0" width="300" height="375" fill="#e6efea"/><rect x="600" y="0" width="400" height="375" fill="#faf0db"/>
          <path d="M300 0V375 M600 0V375" stroke="#8d9693" stroke-width="5"/>
          <text x="150" y="45" text-anchor="middle">적재 A · 60cm</text><text x="450" y="45" text-anchor="middle">적재 B · 60cm</text><text x="800" y="45" text-anchor="middle">인계 · 80cm</text>
          <g v-for="(edge, i) in map.edges" :key="'road'+i"><polyline :points="points(edge)" fill="none" stroke="#c8d2cc" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/></g>
          <g v-if="shownRoute"><polyline v-for="(s,i) in shownRoute.segments" :key="i" :points="points(s.poses)" fill="none" :stroke="s.direction < 0 ? '#c96e3f' : '#368575'" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><circle :cx="shownRoute.end[0]*500" :cy="-shownRoute.end[1]*500" r="11" fill="#fff" stroke="#368575" stroke-width="4"/></g>
          <text x="60" y="690" font-size="19">대기줄</text><text x="610" y="718" font-size="18" fill="#66756c">200 × 150cm · layout 좌표</text>
          <g v-if="pose" :transform="transform" :opacity="stale ? .45 : 1">
            <rect :x="(map.body_rear-.155)*500" y="-31.75" width="77.5" height="63.5" rx="5" fill="#fff1cf" stroke="#9b7941" stroke-width="3"/>
            <path :d="`M${(map.body_rear-.13)*500} -22v44 m18 -44v44 m18 -44v44`" stroke="#d9c294" stroke-width="2"/>
            <rect :x="map.body_rear*500" :y="-map.body_width*250" :width="(map.body_front-map.body_rear)*500" :height="map.body_width*500" rx="10" fill="#ea9cb5" stroke="#885467" stroke-width="3"/>
            <path d="M-8 -10L8 0L-8 10" fill="none" stroke="#533a45" stroke-width="5"/>
          </g>
          <text v-if="pose" :x="pose[0]*500" :y="-pose[1]*500-45" text-anchor="middle" font-size="18">{{ job?.robot_id || robot }}</text>
        </svg>
        <div class="motion-legend"><span>초록: 전진</span><span>주황: 후진</span><span>분홍: Pinky / 노랑: 후면 바구니</span></div>

      </article>
      <article class="panel motion-inputs">
        <h3>이동 요청</h3><p :class="{ 'video-error': !ready }">{{ ready ? '시험 준비됨' : '시험 준비 대기' }}</p>
        <label for="motion-robot">시험 로봇</label><select id="motion-robot" v-model="robot" :disabled="!!state?.hold" @change="selected=''"><option>pinky-1</option><option>pinky-2</option></select>
        <label for="motion-route">경로</label><select id="motion-route" v-model="routeId" :disabled="!!state?.hold" @change="selected=''"><option v-for="(_,id) in map?.routes || {}" :key="id" :value="id">{{ routeName(String(id)) }}</option></select>
        <label for="motion-rate">재생 배속</label><select id="motion-rate" v-model="rate"><option :value="1">1배</option><option :value="2">2배</option><option :value="4">4배</option></select>
        <small v-if="shownRoute">모의 경로 {{ shownRoute.duration.toFixed(1) }}초</small>
        <label class="motion-check"><input type="checkbox" v-model="fail"/> 경로 30% 지점에서 모의 실패</label>
        <button class="primary" :disabled="busy || !ready || !!state?.hold || !!pending || !!connectionError" @click="send()">이동 요청</button>
        <p v-if="state?.hold" class="muted">시험 점유 중</p>
        <div v-if="pending" class="alert danger"><p>요청 응답 미확인</p><button :disabled="busy" @click="send(true)">같은 요청 재전송</button><button class="secondary" @click="clearPending">이력 확인 후 요청 해제</button></div>
      </article>
    </div>
    <article v-if="job" class="panel">
      <div class="section-title"><h3>{{ names[job.status] || job.status }} · {{ job.robot_id }}</h3><button class="secondary" @click="exportLog">로그 JSON 저장</button></div>
      <div class="motion-milestones"><span>전송 {{ timeText(job.sent_at) }}</span><span>수락 {{ timeText(job.accepted_at) }}</span><span>중지 요청 {{ timeText(job.stop_requested_at) }}</span><span>중지 수신 {{ timeText(job.stop_ack_at) }}</span><span>모의 정지 {{ job.stopped ? '확인' : '미확인' }}</span></div>
      <progress :value="sample?.progress || 0" max="1" aria-label="이동 진행률"></progress>
      <p v-if="sample">진행 {{ (sample.progress*100).toFixed(0) }}% · X {{ sample.pose[0].toFixed(3) }}m / Y {{ sample.pose[1].toFixed(3) }}m / 방향 {{ (sample.pose[2]*180/Math.PI).toFixed(1) }}° · 시뮬 {{ sample.sim_time.toFixed(1) }}초</p>
      <div class="button-row"><button class="danger-button" :disabled="busy || final(job.status) || !!job.stop_requested_at" @click="action('stop')">중지 요청</button><button :disabled="busy || !final(job.status) || !job.stopped || state?.hold !== job.id" @click="action('release',{operator:'reference-ui',restored:true})">종료된 모의 시험 해제</button></div>
      <div v-if="job.status === 'UNCERTAIN'" class="alert danger"><p>결과 미확인 · 기존 실행부 종료 필요</p><label>확인자<input v-model="operator"/></label><label class="motion-check"><input type="checkbox" v-model="closed"/> 기존 실행부 종료 확인</label><button :disabled="busy || !closed || !operator.trim()" @click="action('review',{operator,success:false,stopped:true,process_closed:true,note:'원래 모의 실행부 종료 후 실패로 복구'})">실패로 정리</button></div>
      <div class="table-scroll"><table><thead><tr><th>시각</th><th>이벤트</th><th>내용</th></tr></thead><tbody><tr v-for="(entry,i) in [...job.timeline].reverse()" :key="i"><td>{{ timeText(entry.at) }}</td><td>{{ names[entry.kind] || entry.kind }}</td><td><code>{{ JSON.stringify(entry.data) }}</code></td></tr></tbody></table></div>
    </article>
    <article class="panel"><h3>이동 시험 이력</h3><p v-if="!rows.length" class="muted">이동 이력 없음</p><div class="motion-history"><button v-for="r in rows" :key="r.id" :class="{active:selected===r.id}" @click="selected=r.id">{{ r.robot_id }} · {{ routeName(r.parameters.route_id) }} · {{ names[r.status] || r.status }} · {{ shortId(r.id) }}</button></div></article>
  </section>
</template>

<style scoped>
.motion-description{max-width:850px;color:#66756c;line-height:1.8}.motion-grid{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:18px;align-items:start}.motion-map{padding:20px}.motion-map svg{width:100%;display:block}.motion-map text{font-family:inherit;font-size:22px;fill:#3d5047}.motion-inputs select{width:100%;margin-bottom:14px}.motion-inputs .primary{width:100%;margin-top:12px}.motion-inputs small{display:block}.motion-check{display:flex;align-items:center;gap:9px;margin-top:18px}.motion-check input{width:auto;margin:0}.motion-legend,.motion-milestones{display:flex;gap:15px;flex-wrap:wrap;font-size:12px;color:#65746b}.motion-milestones{padding:12px 0}progress{width:100%;height:10px;accent-color:#368575}.motion-history{display:flex;flex-direction:column;gap:8px}.motion-history button{text-align:left}.motion-history .active{background:#e0ece7;border-color:#368575}.table-scroll{max-height:360px;margin-top:20px}.pinky-motion h3{font-size:18px;margin:0 0 16px}.motion-grid .panel{min-width:0}@media(max-width:900px){.motion-grid{grid-template-columns:1fr}.motion-map{padding:12px}}
</style>
