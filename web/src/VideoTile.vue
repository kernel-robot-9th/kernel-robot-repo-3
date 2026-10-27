<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from './api'
import Icon from './ui/Icon.vue'
const props = defineProps<{ token: string; showTools?: boolean; feed: { id: string; label: string; owner: string; transport: string; whep_url?: string; read_user?: string; read_password?: string } }>()
const image = ref(''), error = ref(''), age = ref<number | null>(null), video = ref<HTMLVideoElement | null>(null)
const connecting = ref(false)
const received = ref(false)
let alive = true, timer: ReturnType<typeof setTimeout> | undefined, pc: RTCPeerConnection | undefined, resource: string | undefined
let decoded = 0, lastFrame = 0
const auth = () => ({ Authorization: 'Bearer ' + props.token })
const mediaAuth = (): Record<string, string> => props.feed.read_user ? { Authorization: 'Basic ' + btoa(props.feed.read_user + ':' + props.feed.read_password) } : {}
async function frame() {
  try {
    const response = await fetch('/api/admin/video/' + props.feed.id + '/frame', { headers: auth(), signal: AbortSignal.timeout(3000) })
    if (!response.ok) throw new Error(response.status === 401 ? '인증 필요' : props.feed.transport === 'mock' ? '모의 영상 수신 끊김' : response.status === 503 && !received.value ? '영상 대기' : '영상 수신 끊김')
    const blob = await response.blob()
    if (!alive) return
    const previous = image.value; image.value = URL.createObjectURL(blob)
    if (previous) URL.revokeObjectURL(previous)
    age.value = Number(response.headers.get('X-Frame-Age'))
    received.value = true
    error.value = age.value >= 3 ? '영상 지연 · 마지막 화면' : ''
  } catch (e) { if (alive) error.value = e instanceof Error ? e.message : '영상 확인 필요' }
  finally { if (alive) timer = setTimeout(frame, 500) }
}
async function closeRtc() {
  pc?.close(); pc = undefined
  if (resource) {
    const url = resource; resource = undefined
    try { await fetch(url, { method: 'DELETE', headers: mediaAuth(), signal: AbortSignal.timeout(2000) }) } catch { /* Server also expires disconnected peers. */ }
  }
}
async function connect() {
  if (connecting.value) return
  connecting.value = true
  received.value = false; age.value = null
  error.value = ''; await closeRtc()
  if (!alive || !props.feed.whep_url) { connecting.value = false; return }
  try {
    const peer = new RTCPeerConnection(); pc = peer
    peer.addTransceiver('video', { direction: 'recvonly' })
    peer.ontrack = event => { if (video.value) video.value.srcObject = new MediaStream([event.track]) }
    peer.onconnectionstatechange = () => { if (alive && ['failed', 'disconnected'].includes(peer.connectionState)) error.value = '영상 연결 끊김' }
    await peer.setLocalDescription(await peer.createOffer())
    await new Promise<void>((resolve, reject) => {
      if (peer.iceGatheringState === 'complete') { resolve(); return }
      const timeout = setTimeout(() => { peer.removeEventListener('icegatheringstatechange', changed); reject(new Error('영상 연결 준비 시간 초과')) }, 5000)
      function changed() { if (peer.iceGatheringState === 'complete') { clearTimeout(timeout); peer.removeEventListener('icegatheringstatechange', changed); resolve() } }
      peer.addEventListener('icegatheringstatechange', changed)
    })
    const response = await fetch(props.feed.whep_url, { method: 'POST', headers: { ...mediaAuth(), 'Content-Type': 'application/sdp' }, body: peer.localDescription?.sdp, signal: AbortSignal.timeout(5000) })
    if (!response.ok) throw new Error('영상 서버 응답 오류 ' + response.status)
    const location = response.headers.get('Location')
    if (location) {
      const url = new URL(location, props.feed.whep_url)
      if (url.origin !== new URL(props.feed.whep_url).origin) throw new Error('영상 세션 주소 불일치')
      resource = url.href
    }
    if (!alive) { await closeRtc(); return }
    await peer.setRemoteDescription({ type: 'answer', sdp: await response.text() })
    lastFrame = Date.now(); decoded = 0
  } catch (e) { if (alive) error.value = e instanceof Error ? e.message : '영상 연결 실패'; await closeRtc() }
  finally { connecting.value = false }
}
async function statistics() {
  if (pc) {
    try {
      for (const report of (await pc.getStats()).values()) {
        if (report.type === 'inbound-rtp' && report.kind === 'video' && report.framesDecoded > decoded) {
          decoded = report.framesDecoded; lastFrame = Date.now(); error.value = ''
          received.value = true
        }
      }
      if (lastFrame) { age.value = (Date.now() - lastFrame) / 1000; if (age.value >= 3) error.value = '영상 지연 · 마지막 화면' }
    } catch { error.value = '영상 상태 조회 실패' }
  }
  if (alive) timer = setTimeout(statistics, 1000)
}
async function fault(kind: string) {
  try { await api('/admin/video/' + props.feed.id + '/mock-fault', props.token, { kind }) }
  catch (e) { error.value = String(e) }
}
onMounted(() => { if (props.feed.transport === 'webrtc') { void connect(); void statistics() } else void frame() })
onUnmounted(() => { alive = false; if (timer) clearTimeout(timer); if (image.value) URL.revokeObjectURL(image.value); void closeRtc() })
</script>
<template>
  <article class="panel video-tile">
    <div class="section-title"><h2>{{ feed.label }}</h2><span class="pill" :class="{bad: received && error}">{{ feed.transport === 'mock' ? '모의' : received && error ? '수신 지연' : received ? '수신 중' : '수신 대기' }}</span></div>
    <video v-if="feed.transport === 'webrtc'" ref="video" autoplay muted playsinline></video>
    <img v-else-if="image" :src="image" :alt="feed.label + ' 영상'" />
    <div v-else class="video-placeholder"><Icon name="camera" :size="36" /><strong>영상 대기</strong></div>
    <p v-if="error" class="video-error" role="status">{{ error }}</p>
    <details v-if="showTools" class="video-details"><summary>수신 정보</summary><small>{{ feed.owner }} · {{ age === null ? '대기' : age.toFixed(1) + '초 전' }}</small></details>
    <div v-if="showTools && feed.transport === 'mock'" class="button-row"><button @click="fault('freeze')">정지 화면 시험</button><button @click="fault('offline')">끊김 시험</button><button @click="fault('none')">복구</button></div>
    <button v-else-if="feed.transport === 'webrtc'" :disabled="connecting" @click="connect">영상 다시 연결</button>
  </article>
</template>
