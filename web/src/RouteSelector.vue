<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, usePolling } from './api'
type Mode = { version: number; name: string; routes: Record<string, number[][]> }
type View = { selected: number; options: Mode[]; active: {robot_id: string; route_version: number}[]; deployed?: Record<string,boolean> }
const props = defineProps<{token: string}>()
const view = ref<View>({selected:4, options:[], active:[]})
const choice = ref(4), initialized = ref(false), busy = ref(false), message = ref(''), error = ref('')
const {refresh, connectionError} = usePolling(async () => {
  view.value = await api<View>('/admin/field/routes',props.token)
  if (!initialized.value) {choice.value=view.value.selected;initialized.value=true}
})
onMounted(refresh)
const mode = computed(() => view.value.options.find(m => m.version===choice.value))
const paths = computed(() => ['home_to_A','A_to_B','B_to_handoff','handoff_to_home_front']
  .map(name => ({name,points:(mode.value?.routes[name] || []).map(p => `${p[0]*500},${-p[1]*500}`).join(' ')})))
async function save() {
  busy.value=true;error.value=''
  try {await api('/admin/field/routes',props.token,{version:choice.value});message.value='다음 고객 시작부터 적용합니다.';await refresh()}
  catch(e) {error.value=e instanceof Error ? e.message : '선택 저장 실패'}
  finally {busy.value=false}
}
</script>

<template>
  <section class="panel route-selector">
    <div class="section-title"><h3>주행 경로 선택</h3><span class="pill">다음 고객: v{{ view.selected }}</span></div>
    <div class="route-controls"><select v-model="choice" aria-label="주행 경로 방식"><option v-for="m in view.options" :key="m.version" :value="m.version">v{{ m.version }} · {{ m.name }}</option></select><button :disabled="busy" @click="save">선택 적용</button></div>
    <p class="muted">P1·P2 공통 선택입니다. 진행 중인 고객은 시작할 때 선택한 경로를 유지합니다.</p>
    <p v-for="(ready, robot) in view.deployed" :key="robot" class="muted">{{ robot }} 두 경로 {{ ready ? '배포됨' : '배포 전' }}</p>
    <svg viewBox="-25 -45 1050 835" role="img" :aria-label="`${mode?.name || ''} 원본 계획 미리보기`">
      <rect width="1000" height="750" fill="#f1f5f4" stroke="#64748b" stroke-width="3" />
      <path d="M300 0V375 M600 0V375" stroke="#64748b" stroke-width="4" />
      <g fill="#475569" font-size="23" text-anchor="middle"><text x="150" y="35">A 적재</text><text x="450" y="35">B 적재</text><text x="800" y="35">C 하역</text></g>
      <polyline v-for="(p,i) in paths" :key="p.name" :points="p.points" fill="none" :stroke="['#287ca8','#319080','#8662b3','#d58b2d'][i]" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"><title>{{ p.name }}</title></polyline>
      <text x="250" y="735" font-size="23" fill="#475569">후열 → 선두 대기</text>
    </svg>
    <p class="muted">첨부 replay의 원본 계획 비교입니다. 실제 주행은 현장 목표·대기 정렬을 반영한 경로를 사용합니다.</p>
    <p v-for="s in view.active" :key="s.robot_id" class="muted">{{ s.robot_id }} 진행 고객: v{{ s.route_version }}</p>
    <p v-if="message" role="status">{{ message }}</p><p v-if="error || connectionError" class="error">{{ error || connectionError }}</p>
  </section>
</template>

<style scoped>
.route-controls {display:flex;gap:.75rem;flex-wrap:wrap;align-items:center}
.route-selector svg {display:block;width:100%;max-height:380px}
</style>
