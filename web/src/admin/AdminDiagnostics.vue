<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Audit, Snapshot } from '../types'
import { shortId, timeText } from '../api'
import Icon from '../ui/Icon.vue'
import VideoWall from '../VideoWall.vue'
import { nodeOnline, robotName } from './presentation'
const props = defineProps<{ state: Snapshot; token: string; logs: Audit[]; busy: boolean }>()
defineEmits<{ action: [path: string, body: unknown, message: string]; reset: [] }>()
const selected = ref(''), device = ref('omx-a'), showVideoTools = ref(false)
const logs = computed(() => props.logs.filter(l => !selected.value || l.session_id === selected.value))
const customerName = (sid: string | null) => sid ? props.state.sessions[sid]?.label || shortId(sid) : '—'
</script>

<template>
  <nav class="anchor-tabs" aria-label="진단 영역"><a href="#audit-history">작업 이력</a><a href="#gateway-detail">중계·장비 상세</a><a v-if="state.mode === 'mock'" href="#mock-tools">모의 실행 도구</a></nav>
  <section id="audit-history" class="panel table-panel"><div class="section-title"><h2>작업 이력</h2><span class="pill">{{ logs.length }}건</span></div><label for="history-customer">고객 필터</label><select id="history-customer" v-model="selected"><option value="">전체 고객</option><option v-for="s in state.sessions" :key="s.id" :value="s.id">{{ s.label }} · {{ shortId(s.id) }}</option></select><div class="table-scroll"><table><thead><tr><th>시각</th><th>고객</th><th>이벤트</th><th>명령</th><th>상세</th></tr></thead><tbody><tr v-for="entry in logs" :key="entry.seq"><td>{{ timeText(entry.at) }}<small>{{ entry.mode }}</small></td><td>{{ customerName(entry.session_id) }}</td><td>{{ entry.kind }}</td><td>{{ shortId(entry.command_id) }}</td><td><details><summary>데이터 보기</summary><code>{{ JSON.stringify(entry.detail, null, 2) }}</code></details></td></tr><tr v-if="!logs.length"><td colspan="5">이력 없음</td></tr></tbody></table></div></section>
  <section id="gateway-detail"><div class="section-title"><h2>중계·장비 상세</h2></div><div v-if="state.gateways" class="gateway-grid"><article v-for="(node, id) in state.gateways" :key="id" class="panel"><div class="section-title"><h3>{{ node.label }}</h3><span class="pill" :class="{bad: !nodeOnline(state, String(id))}">{{ nodeOnline(state, String(id)) ? '통신 연결' : '연결 미확인' }}</span></div><p>{{ id }}</p><p class="muted">{{ node.devices.map(robotName).join(' · ') }}</p><small>마지막 연결 {{ timeText(node.heartbeat_at) }}</small><p class="muted">{{ node.role === 'test' ? '시험 전용' : '주문 중계' }}</p></article></div><div class="device-grid"><article v-for="(value, id) in state.devices" :key="id" class="panel"><Icon :name="String(id).startsWith('pinky') ? 'robot' : 'arm'" /><h3>{{ robotName(String(id)) }}</h3><p><span class="status-dot" :class="{online:value.connected}"></span>{{ value.connected ? '통신 연결' : '연결 대기' }}</p></article></div></section>
  <section v-if="state.mode === 'mock'" id="mock-tools" class="panel mock-tools"><div class="section-title"><h2>모의 실행 도구</h2><span class="pill">모의 전용</span></div>
    <div class="tool-block"><h3>단계 실행</h3><div class="button-row"><button :disabled="busy" @click="$emit('action','/admin/mock/steps',{count:1},'1단계 요청')">1단계 진행</button><button :disabled="busy" @click="$emit('action','/admin/mock/steps',{count:20},'20단계 요청')">20단계 진행</button><small>잔여 {{ state.permits || 0 }}</small></div></div>
    <div class="tool-block"><h3>오류 시험</h3><label for="fault-device">대상 장비</label><select id="fault-device" v-model="device"><option v-for="(_, id) in state.devices" :key="id" :value="id">{{ robotName(String(id)) }}</option></select><div class="button-row"><button :disabled="busy || device.startsWith('pinky')" @click="$emit('action','/admin/mock/fault',{device_id:device,kind:'PICK_FAIL'},'실패 시험 예약')">다음 집기·인계 실패</button><button class="danger-button" :disabled="busy" @click="$emit('action','/admin/mock/fault',{device_id:device,kind:'DISCONNECT'},'통신 끊김 시험')">통신 끊김</button></div></div>
    <div class="tool-block"><h3>새 모의 실행</h3><button class="danger-button" :disabled="busy" @click="$emit('reset')">이전 실행 보관 후 새로 시작</button></div>
    <details class="tool-block" @toggle="showVideoTools = ($event.target as HTMLDetailsElement).open"><summary>영상 정지·끊김 모의 시험</summary><VideoWall v-if="showVideoTools" :token="token" show-tools /></details>
  </section>
</template>
