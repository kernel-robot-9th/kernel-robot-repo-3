<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, timeText, usePolling } from './api'
type Pose = { x: number; y: number; yaw: number }
type Robot = { visible: boolean; marker_id: number; layout_pose?: Pose }
type Dimensions = { body_front_m: number; body_rear_m: number; body_width_m: number; basket_width_m: number; basket_length_m: number; basket_mount_x_m: number; source: string }
type Target = { layout_pose: Pose; map_pose: Pose }
type View = { running: boolean; observed_at?: number; robots: Record<string, Robot>; dimensions?: Dimensions; basket_scale?: number;
  planning_footprint?: number[][]; waiting_targets?: Record<string, Target>;
  applied?: Record<string, {waiting: boolean; basket_scale?: number}>;
  waiting_status?: Record<string, {slot: string; phase: string; distance_m?: number; yaw_error?: number; at: number}> }
const props = defineProps<{ token: string }>()
const view = ref<View>({ running: false, robots: {} })
const robots = computed(() => Object.entries(view.value.robots).filter(([, r]) => r.visible && r.layout_pose))
const showPlanning = ref(false)
const dims = computed(() => view.value.dimensions)
const planningPoints = computed(() => (view.value.planning_footprint || []).map(p => `${p[0]*500},${-p[1]*500}`).join(' '))
const targetRows = computed(() => Object.entries(view.value.waiting_targets || {}))
const errorText = (id: string, pose: Pose) => {
  const robot = id === 'pinky-1' ? 'P1' : 'P2'
  const slot = view.value.waiting_status?.[robot]?.slot || 'front'
  const target = view.value.waiting_targets?.[`${slot}/${robot}`]?.layout_pose
  if (!target) return ''
  const delta = target.yaw-pose.yaw
  return `${slot === 'front' ? '선두' : '후열'} 목표까지 ${(Math.hypot(target.x-pose.x,target.y-pose.y)*100).toFixed(1)}cm · ${Math.abs(Math.atan2(Math.sin(delta),Math.cos(delta))*180/Math.PI).toFixed(1)}°`
}
const { refresh, connectionError } = usePolling(async () => {
  view.value = await api<View>('/admin/field/camera-position', props.token)
})
onMounted(refresh)
const transform = (p: Pose) => `translate(${p.x*500} ${-p.y*500}) rotate(${-p.yaw*180/Math.PI})`
</script>

<template>
  <section class="panel camera-position">
    <div class="section-title"><h3>전체 카메라 위치</h3><span class="pill">{{ connectionError ? '수신 오류' : view.running ? '관측 중' : '카메라 실행 대기' }}</span></div>
    <label><input v-model="showPlanning" type="checkbox" /> 주행 계산용 바구니 70% 외곽 비교</label>
    <svg viewBox="-50 -45 1100 850" role="img" aria-label="2m × 1.5m 맵의 카메라 관측 위치와 앞방향">
      <rect width="1000" height="750" fill="#f1f5f4" stroke="#64748b" stroke-width="4" />
      <path d="M300 0V375 M600 0V375" stroke="#64748b" stroke-width="5" />
      <g fill="#64748b" font-size="26" text-anchor="middle"><text x="150" y="45">적재 A</text><text x="450" y="45">적재 B</text><text x="800" y="45">하역 C</text><text x="500" y="720">대기 구간</text></g>
      <g v-for="([key, target]) in targetRows" :key="key" :transform="transform(target.layout_pose)" fill="none" stroke="#64748b" stroke-width="2" stroke-dasharray="5 4" opacity=".6">
        <rect v-if="dims" :x="dims.body_rear_m*500" :y="-dims.body_width_m*250" :width="(dims.body_front_m-dims.body_rear_m)*500" :height="dims.body_width_m*500" />
        <rect v-if="dims" :x="(dims.basket_mount_x_m-dims.basket_length_m)*500" :y="-dims.basket_width_m*250" :width="dims.basket_length_m*500" :height="dims.basket_width_m*500" />
        <path d="M0 0L30 0M22 -6L30 0L22 6" />
        <title>{{ key }} 저장 대기 목표</title>
      </g>
      <g v-if="!connectionError && view.running">
        <g v-for="([id, r]) in robots" :key="id">
          <g :transform="transform(r.layout_pose!)" :fill="id === 'pinky-1' ? '#0891b2' : '#e34b4b'">
            <template v-if="dims">
              <rect :x="dims.body_rear_m*500" :y="-dims.body_width_m*250" :width="(dims.body_front_m-dims.body_rear_m)*500" :height="dims.body_width_m*500" rx="9" stroke="white" stroke-width="2" />
              <rect :x="(dims.basket_mount_x_m-dims.basket_length_m)*500" :y="-dims.basket_width_m*250" :width="dims.basket_length_m*500" :height="dims.basket_width_m*500" fill="#eeb64d" stroke="#9b6d15" stroke-width="2" />
              <polygon v-if="showPlanning" :points="planningPoints" fill="none" stroke="#7c3aed" stroke-width="3" stroke-dasharray="5 3" />
            </template>
            <circle v-else r="24" stroke="white" stroke-width="3" /><path d="M14 -8L44 0L14 8Z" />
          </g>
          <text :x="r.layout_pose!.x*500" :y="-r.layout_pose!.y*500-35" text-anchor="middle" font-size="24">{{ id === 'pinky-1' ? 'P1 흰색' : 'P2 빨간색' }}</text>
        </g>
      </g>
    </svg>
    <p class="muted">화살표는 로봇 앞방향 · 마지막 관측 {{ timeText(view.observed_at || null) }}</p>
    <p class="muted">노란 바구니: 실측 127×155mm · 점선: 저장 대기 목표 · 정렬 완료: 3cm·7°</p>
    <p v-for="(applied, robot) in view.applied" :key="robot" class="muted">{{ robot }} 대기 경로 {{ applied.waiting ? '적용' : '준비' }} · 바구니 충돌 설정 {{ applied.basket_scale ? Math.round(applied.basket_scale*100)+'% 적용' : '미적용' }}</p>
    <p v-for="([id, r]) in robots" :key="id" class="muted">{{ id === 'pinky-1' ? 'P1' : 'P2' }} {{ errorText(id, r.layout_pose!) }}</p>
    <details v-if="dims"><summary>외곽 표시 기준</summary><p>{{ dims.source }}</p></details>
    <p v-if="view.running && !connectionError" class="muted">P1 {{ view.robots['pinky-1']?.visible ? '검출' : '미검출' }} · P2 {{ view.robots['pinky-2']?.visible ? '검출' : '미검출' }}</p>
    <p v-if="connectionError" class="error">{{ connectionError }}</p>
  </section>
</template>

<style scoped>
.camera-position svg { display: block; width: 100%; max-height: 480px; }
</style>
