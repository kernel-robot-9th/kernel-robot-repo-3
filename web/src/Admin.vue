<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, usePolling } from './api'
import type { Audit, Session, Snapshot } from './types'
import Icon from './ui/Icon.vue'
import AdminLayout from './admin/AdminLayout.vue'
import AdminDashboard from './admin/AdminDashboard.vue'
import AdminOrders from './admin/AdminOrders.vue'
import AdminRobots from './admin/AdminRobots.vue'
import AdminStock from './admin/AdminStock.vue'
import AdminDiagnostics from './admin/AdminDiagnostics.vue'
import DeviceTests from './DeviceTests.vue'
import VideoWall from './VideoWall.vue'
import { adminPages } from './admin/navigation'

const route = useRoute(), router = useRouter()
const section = computed(() => String(route.meta.section || 'overview'))
const page = computed(() => adminPages.find(p => p.section === section.value) || adminPages[0]!)
const token = ref(sessionStorage.getItem('shopping.admin.token') || '')
const tokenInput = ref(''), error = ref(''), message = ref(''), busy = ref(false), expired = ref(false)
const state = ref<Snapshot | null>(null), logs = ref<Audit[]>([])
const { refresh, connectionError } = usePolling(async () => {
  if (!token.value || expired.value) return
  try {
    state.value = await api<Snapshot>('/admin/state', token.value)
    if (section.value === 'diagnostics') logs.value = (await api<{ items: Audit[] }>('/admin/logs', token.value)).items
  } catch (e) { if (e instanceof ApiError && e.status === 401) expired.value = true; throw e }
})
watch(section, () => { error.value = ''; message.value = ''; void refresh() })
async function login() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    state.value = await api<Snapshot>('/admin/state', tokenInput.value.trim())
    token.value = tokenInput.value.trim(); tokenInput.value = ''; expired.value = false
    sessionStorage.setItem('shopping.admin.token', token.value)
    await refresh()
  } catch (e) { error.value = e instanceof Error ? e.message : '인증 실패' }
  finally { busy.value = false }
}
function logout() { token.value = ''; tokenInput.value = ''; state.value = null; logs.value = []; expired.value = false; error.value = ''; message.value = ''; sessionStorage.removeItem('shopping.admin.token') }
async function act(path: string, body: unknown, success: string) {
  if (busy.value || connectionError.value || expired.value) return
  busy.value = true; error.value = ''; message.value = ''
  try { await api(path, token.value, body); message.value = success; await refresh() }
  catch (e) { error.value = e instanceof Error ? e.message : '처리 실패' }
  finally { busy.value = false }
}
function ready(s: Session, basketId: string) {
  if (!basketId || !s.current_task) return
  if (!window.confirm(`${s.label} · ${s.robot_id}의 고객 장바구니 ${basketId}가 인계 위치에 준비됐습니까?`)) return
  void act('/admin/basket-ready', { session_id: s.id, task_id: s.current_task, basket_id: basketId }, '장바구니 준비 확인 완료')
}
function resetRun() {
  if (!window.confirm('새 모의 실행을 시작할까요? 현재 가상 상태·고객 세션은 종료되고 이전 기록은 DB에 보관됩니다. 실제 장비에는 사용할 수 없습니다.')) return
  void act('/admin/mock/new-run', { acknowledge_unresolved: true }, '새 모의 실행 시작')
}
onMounted(refresh)
</script>

<template>
  <AdminLayout :section="section">
    <header class="page-heading horizontal"><h1>{{ page.label }}</h1><button v-if="token" class="secondary logout-button" @click="logout"><Icon name="logout" :size="17" />로그아웃</button></header>
    <div v-if="error" class="alert danger" role="alert">{{ error }}</div>
    <div v-if="message" class="alert success" role="status"><Icon name="check" :size="18" />{{ message }}</div>
    <form v-if="!token" class="panel login" @submit.prevent="login"><span class="login-icon"><Icon name="robot" :size="30" /></span><h2>관리자 인증</h2><label for="admin-token">관리자 토큰</label><input id="admin-token" v-model="tokenInput" type="password" autocomplete="off" placeholder="관리자 토큰 입력" required /><button class="primary" :disabled="busy || !tokenInput.trim()">{{ busy ? '인증 중…' : '로그인' }}<Icon name="arrow" :size="18" /></button><details><summary>토큰 정보</summary><p>설치 과정에서 생성한 SHOP_ADMIN_TOKEN을 사용합니다.</p></details></form>
    <section v-else-if="expired" class="panel empty-state"><h2>인증 만료</h2><button class="primary" @click="logout">다시 인증하기</button></section>
    <template v-else>
      <div v-if="connectionError" class="alert danger" role="alert"><strong>연결 끊김 · 마지막 조회 상태</strong><p>{{ connectionError }}</p><button @click="refresh">다시 불러오기</button></div>
      <template v-if="state">
        <AdminDashboard v-if="section === 'overview'" :state="state" :busy="busy || !!connectionError" />
        <AdminOrders v-else-if="section === 'orders'" :state="state" :busy="busy || !!connectionError" @ready="ready" />
        <AdminRobots v-else-if="section === 'omx' || section === 'pinky'" :kind="section" :state="state" :token="token" @tests="router.push('/admin/tests')" @overview="router.push('/admin/orders')" />
        <section v-else-if="section === 'video'"><VideoWall :token="token" :feed-ids="['overview']" /></section>
        <AdminStock v-else-if="section === 'stock'" :state="state" />
        <DeviceTests v-else-if="section === 'tests'" :token="token" :products="state.products" />
        <AdminDiagnostics v-else-if="section === 'diagnostics'" :state="state" :token="token" :logs="logs" :busy="busy || !!connectionError" @action="act" @reset="resetRun" />
      </template>
      <section v-else-if="!connectionError" class="panel empty-state" role="status">불러오는 중…</section>
    </template>
  </AdminLayout>
</template>
