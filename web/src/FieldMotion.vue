<script setup lang="ts">
import { ref } from 'vue'
import type { Snapshot, FieldMotionStatus } from './types'
import { api, label, timeText, zoneName } from './api'
import Icon from './ui/Icon.vue'
import VideoWall from './VideoWall.vue'
import CameraPosition from './CameraPosition.vue'
import RouteSelector from './RouteSelector.vue'
import { robotName } from './admin/presentation'
const props = defineProps<{ state: Snapshot; token: string }>()
defineEmits<{ tests: [] }>()
const busy = ref(false), message = ref(''), error = ref('')
const status = (id: string): FieldMotionStatus => props.state.hardware_motion?.[id] || {}
const task = (id: string) => Object.values(props.state.tasks).find(t => t.robot_id === id &&
  props.state.sessions[t.session_id]?.current_task === t.id)
const lastCommand = (id: string, kind: string) => Object.values(props.state.commands)
  .filter(c => c.robot_id === id && c.kind === kind).slice(-1)[0]
const loading = (id: string) => lastCommand(id, 'PICK')
const unloading = (id: string) => lastCommand(id, 'HANDOFF')
const stageLabel = (id: string) => {
  const value = status(id)
  if (!value.reporting) return '상태 수신 대기'
  return ({ executing: '명령 실행 중', parking: '마커 정밀주차 중',
    completed: task(id) ? label(task(id)!.state) : '명령 실행 종료', cancelled: '취소됨', error: '실행 오류' }[value.stage || ''] || '위치 수신 중')
}
const distance = (id: string) => {
  const e = status(id).parking_error
  return !e ? '—' : e.distance_mm !== undefined ? `${e.distance_mm.toFixed(1)} mm` : `${e.distance_marker_widths.toFixed(3)} 마커 폭`
}
async function act(path: string, body: unknown, done: string) {
  busy.value = true; error.value = ''; message.value = ''
  try { await api(path, props.token, body); message.value = done }
  catch (e) { error.value = e instanceof Error ? e.message : '요청 실패' }
  finally { busy.value = false }
}
function record(commandId: string, observation: string) {
  void act(`/admin/field/commands/${commandId}/observe`, { observation }, '실물 확인을 기록했습니다.')
}
</script>

<template>
  <section class="panel">
    <div class="section-title"><h2>이동·주차·적재 현황</h2><span class="pill">실물 연동</span></div>
    <p v-if="message" role="status">{{ message }}</p><p v-if="error" class="error" role="alert">{{ error }}</p>
    <CameraPosition :token="token" />
    <RouteSelector :token="token" />
    <div class="device-grid field-robots">
      <article v-for="id in ['pinky-1', 'pinky-2']" :key="id" class="panel field-card">
        <div class="section-title"><h3><Icon name="robot" :size="24" /> {{ robotName(id) }}</h3><span class="pill" :class="{bad: !status(id).reporting}">{{ stageLabel(id) }}</span></div>
        <p class="muted">{{ id === 'pinky-1' ? '흰색 · eed0 · 192.168.0.16' : '빨간색 · 62b2 · 192.168.0.17' }}</p>
        <dl>
          <dt>담당 중계</dt><dd>{{ state.devices?.[id]?.connected ? '연결' : '연결 대기' }}</dd>
          <dt>Nav2</dt><dd>{{ status(id).inspection_reporting && status(id).inspection?.connected ? '연결' : '미확인' }}</dd>
          <dt>목적지 / 작업</dt><dd>{{ task(id) ? zoneName(task(id)!.zone_id) + ' · ' + label(task(id)!.state) : '작업 없음' }}</dd>
          <dt>지도 위치</dt><dd v-if="status(id).inspection?.observation">x {{ status(id).inspection!.observation!.pose.x.toFixed(3) }}, y {{ status(id).inspection!.observation!.pose.y.toFixed(3) }} m<br>방향 {{ (status(id).inspection!.observation!.pose.yaw * 180 / Math.PI).toFixed(1) }}°</dd><dd v-else>미수신</dd>
          <dt>위치 관측 시각</dt><dd>{{ timeText(status(id).inspection?.observation?.observed_at || null) }}</dd>
          <dt>마커</dt><dd>{{ status(id).marker_visible === undefined ? '미수신' : status(id).marker_visible ? '검출 · ID ' + status(id).marker_id : '검출 대기' }}</dd>
          <dt>주차 오차</dt><dd>{{ distance(id) }} / {{ status(id).parking_error ? (status(id).parking_error!.yaw_error * 180 / Math.PI).toFixed(2) + '°' : '—' }}</dd>
          <dt>마지막 보고</dt><dd>{{ timeText(status(id).received_at || null) }}</dd>
        </dl>
        <p v-if="status(id).error" class="error">{{ status(id).error }}</p>
        <p v-if="status(id).inspection?.error" class="muted">{{ status(id).inspection?.error }}</p>
        <details v-if="loading(id) || unloading(id)"><summary>실물 결과 기록 · 실행과 별도</summary>
          <template v-if="loading(id)">
            <button v-for="item in state.tasks[loading(id)!.task_id]?.items" :key="item.item_id" :disabled="busy" @click="record(loading(id)!.id, 'pick-' + item.slot)">슬롯 {{ item.slot + 1 }} 실제 적재 확인</button>
            <button :disabled="busy" @click="record(loading(id)!.id, 'arm_clear')">팔 이탈 기록</button>
          </template>
          <button v-if="unloading(id)" :disabled="busy" @click="record(unloading(id)!.id, 'delivered')">실제 하역 확인</button>
        </details>
        <button v-if="unloading(id)?.status === 'ACCEPTED'" :disabled="busy" @click="record(unloading(id)!.id, 'finish')">하역 정책 실행 종료</button>
        <button v-if="task(id) && !state.sessions[task(id)!.session_id]?.error" class="secondary" :disabled="busy" @click="act('/admin/field/robots/' + id + '/stop', {}, '중단을 요청했습니다. 실제 정지는 별도 확인합니다.')">현재 작업 중단</button>
        <details v-if="status(id).result_file"><summary>주차 기록</summary><p class="record-path">{{ status(id).result_file }}</p><small>담당 노트북에 저장된 실행 기록입니다.</small></details>
      </article>
    </div>
    <p class="muted">주행·주차·적재·출발은 실행 결과로 이어집니다. 실물 확인은 별도 기록입니다. 수신된 위치의 관측 시각을 함께 확인하세요.</p>
    <VideoWall :token="token" :feed-ids="['load-a', 'load-b', 'handoff-front']" />
    <button class="secondary" @click="$emit('tests')">장비 테스트</button>
  </section>
</template>

<style scoped>
.field-card h3 { display: flex; gap: .5rem; align-items: center; }
.field-card dl { display: grid; grid-template-columns: 7rem 1fr; gap: .6rem; }
.field-card dt { color: var(--muted, #667085); }
.field-card dd { margin: 0; font-variant-numeric: tabular-nums; }
.field-card button { margin: .3rem .3rem .3rem 0; }
.record-path { overflow-wrap: anywhere; font-size: .8rem; }
</style>
