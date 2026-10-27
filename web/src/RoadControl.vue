<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, label, shortId, timeText, usePolling } from './api'
import type { Snapshot } from './types'

type Pose = [number, number, number]
type Job = { id:string; robot_id:string; status:string; purpose:string; target:string; parameters:{route_id:string};
  session_id:string|null; origin_task_id:string|null; task_id:string; command_ids:string[];
  sent_at:number|null; accepted_at:number|null; started_at:number|null; stop_ack_at:number|null; stopped:unknown;
  telemetry:{progress:number; halted:boolean; sequence:number}|null; timeline:{at:number;kind:string}[] }
type Road = { active:string|null; blocked:string|null; source_hash:string; route_version:number; frame_id:string;
  jobs:Record<string,Job>; waiting:Record<string,string>; fail_next:boolean;
  robots:Record<string,{location:string;pose:Pose;age_seconds:number|null;session_id:string|null}> }
type Map = { routes:Record<string,{poses:Pose[]}>; body_front:number;body_rear:number;body_width:number;
  layout:{basket_length:number;basket_width:number} }
const props=defineProps<{token:string}>()
const emit=defineEmits<{overview:[]}>()
const road=ref<Road|null>(null), map=ref<Map|null>(null), state=ref<Snapshot|null>(null)
const error=ref(''),busy=ref(false), selected=ref('')
const jobs=computed(()=>Object.values(road.value?.jobs||{}).reverse())
const job=computed(()=>jobs.value.find(j=>j.id===(selected.value||road.value?.active))||jobs.value[0])
const active=computed(()=>road.value?.active ? road.value.jobs[road.value.active] : null)
const points=(poses:Pose[])=>poses.map(p=>`${p[0]*500},${-p[1]*500}`).join(' ')
const transform=(p:Pose)=>`translate(${p[0]*500} ${-p[1]*500}) rotate(${-p[2]*180/Math.PI})`
const location=(s:string)=>({front:'대기 선두',back:'대기 후열',A:'적재 A',B:'적재 B',handoff:'인계'}[s]||s)
const purpose=(s:string)=>({ORDER:'주문 운반',QUEUE_ADVANCE:'대기열 전진',QUEUE_YIELD:'빈 선두 로봇 양보',QUEUE_REJOIN:'빈 로봇 후열 복귀'}[s]||s)
const {refresh,connectionError}=usePolling(async()=>{
  if(!map.value) map.value=await api<Map>('/admin/road/map',props.token)
  const [r,s]=await Promise.all([api<Road>('/admin/road',props.token),api<Snapshot>('/admin/state',props.token)])
  road.value=r; state.value=s
})
async function act(path:string, body:unknown={}) {
  busy.value=true;error.value=''
  try {await api(path,props.token,body);await refresh()} catch(e) {error.value=e instanceof Error?e.message:'요청 실패'}
  finally {busy.value=false}
}
function download() {
  const url=URL.createObjectURL(new Blob([JSON.stringify({road:road.value,state:state.value,physical_hardware_verified:false},null,2)],{type:'application/json'}))
  const a=document.createElement('a');a.href=url;a.download='pinky-v4-mock-run.json';a.click();URL.revokeObjectURL(url)
}
void refresh()
</script>

<template>
  <section class="road-panel panel">
    <div class="road-heading"><span class="badge">모의 · v4</span>
      <button @click="download" :disabled="!road">실행 기록 저장</button></div>

    <div v-if="connectionError||error||road?.blocked" class="alert danger" role="alert">{{ connectionError||error||road?.blocked }}<p>정지 미확인 · 점유 유지</p></div>
    <div class="button-row"><a href="/shop" target="_blank" rel="noopener">고객 화면 ↗</a>
      <button @click="emit('overview')">장바구니 준비</button>
      <button :disabled="busy||!!road?.blocked" @click="act('/admin/mock/steps',{count:20})">모의 팔 작업 20단계</button>
      <button :disabled="busy||!road?.active||!!road?.blocked" @click="act('/admin/road/stop')">이동 중지 요청</button>
      <button :disabled="busy||!!road?.blocked||road?.fail_next" @click="act('/admin/road/failure')">다음 이동 실패 주입</button></div>
    <div v-if="road&&map&&state" class="road-grid">
      <div><svg viewBox="-25 -45 1050 825" role="img" aria-label="Pinky 두 대와 후면 바구니의 v4 기준 경로 지도">
        <rect x="0" y="0" width="1000" height="750" rx="8" fill="#f1f5f9" stroke="#94a3b8"/>
        <rect v-for="(x,i) in [0,300,600]" :key="x" :x="x+8" y="8" :width="i===2?384:284" height="367" :fill="i===2?'#ffedd5':'#dbeafe'"/>
        <path d="M300 0V375 M600 0V375" stroke="#64748b" stroke-width="7"/>
        <text v-for="(name,i) in ['적재 A','적재 B','고객 인계']" :key="name" :x="[150,450,800][i]" y="40" text-anchor="middle">{{name}}</text>
        <polyline v-for="(r,key) in map.routes" :key="key" :points="points(r.poses)" fill="none" stroke="#cbd5e1" stroke-width="2"/>
        <polyline v-if="active" :points="points(map.routes[active.parameters.route_id]!.poses)" fill="none" stroke="#0284c7" stroke-width="5"/>
        <g v-for="(r,rid) in road.robots" :key="rid">
          <g :transform="transform(r.pose)" :fill="rid==='pinky-1'?'#0891b2':'#d97706'" stroke="#0f172a" stroke-width="2">
            <rect :x="map.body_rear*500" :y="-map.body_width*250" :width="(map.body_front-map.body_rear)*500" :height="map.body_width*500" rx="5"/>
            <rect :x="(map.body_rear-map.layout.basket_length)*500" :y="-map.layout.basket_width*250" :width="map.layout.basket_length*500" :height="map.layout.basket_width*500" fill-opacity=".3"/>
            <path d="M0 -12L18 0L0 12" fill="none" stroke="white" stroke-width="4"/>
          </g>
          <text :x="r.pose[0]*500" :y="-r.pose[1]*500+53" text-anchor="middle">{{rid}}</text>
        </g>
        <text x="960" y="730" text-anchor="end">2.0 × 1.5 m · 후면 바구니 포함</text>
      </svg><details><summary>맵 정보</summary><small>{{road.frame_id}} · {{road.source_hash.slice(0,12)}} · 기준 경로 계산값</small></details></div>
      <div class="road-details"><article v-for="(r,rid) in road.robots" :key="rid" class="road-card">
        <strong>{{rid}} · {{r.session_id?state.sessions[r.session_id]?.label:'배정 없음'}}</strong>
        <p>{{active?.robot_id===rid?(active.status==='RUNNING'?'모의 이동 중':'이동 점유 유지 · '+label(active.status))+' · '+active.parameters.route_id:location(r.location)}}</p>
        <p>{{road.waiting[rid]||'대기'}}</p>
        <small>모의 위치 · {{r.age_seconds===null?'미수신':r.age_seconds.toFixed(1)+'초 전'}}</small>
      </article>
      <article class="road-card"><strong>점유 구역</strong><p v-for="(z,name) in state.zones" :key="name">{{name}} · {{z.owner?shortId(z.owner):'비어 있음'}}</p>
        </article></div>
    </div>
    <div v-if="job" class="road-card"><label>이동 기록 <select v-model="selected"><option value="">현재 / 최근 이동</option><option v-for="j in jobs" :key="j.id" :value="j.id">{{j.robot_id}} · {{j.parameters.route_id}} · {{label(j.status)}}</option></select></label>
      <p>{{purpose(job.purpose)}} · {{label(job.status)}} · {{Math.round((job.telemetry?.progress||0)*100)}}%</p>
      <p>전송 {{timeText(job.sent_at)}} → 수락 {{timeText(job.accepted_at)}} → 실행 {{timeText(job.started_at)}} · 중지 요청 수신 {{timeText(job.stop_ack_at)}} · 모의 정지 보고 {{job.stopped?'있음':'없음'}}</p>
      <small>작업 {{shortId(job.task_id)}} · 이동 {{shortId(job.id)}} · 원래 작업 {{shortId(job.origin_task_id)}}</small>
      <details><summary>이동 이벤트</summary><p v-for="(event,i) in job.timeline" :key="i">{{timeText(event.at)}} · {{label(event.kind)}}</p></details>
    </div>
  </section>
</template>

<style scoped>
.road-heading{display:flex;justify-content:space-between;align-items:center;gap:1rem}.road-heading h2{margin:.5rem 0}.road-grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(250px,1fr);gap:1rem;margin-top:1.25rem}.road-grid svg{width:100%;display:block}.road-grid text{font-size:20px;fill:#334155;font-family:inherit}.road-card{border:1px solid #dbe3ed;border-radius:12px;padding:1rem;margin-bottom:1rem;background:#fff}.road-card p{margin:.5rem 0}.road-card small{color:#64748b}.road-card select{max-width:100%;margin:.5rem}.button-row{flex-wrap:wrap}@media(max-width:900px){.road-grid{grid-template-columns:1fr}.road-heading{align-items:start;flex-direction:column}}
</style>
