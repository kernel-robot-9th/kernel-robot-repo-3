import { onUnmounted, ref } from 'vue'

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

// randomUUID requires HTTPS on remote phones; getRandomValues also works on
// the private LAN HTTP demo, without weakening request-key randomness.
export function requestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
}

export async function api<T>(path: string, token = '', body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(5000),
  })
  const data = await response.json()
  if (!response.ok) throw new ApiError(typeof data.detail === 'string' ? data.detail : '입력 오류', response.status)
  return data as T
}

// Sequential polling avoids stale overlapping responses. A failed read never
// clears the last known state or implies that an active robot stopped.
export function usePolling(load: () => Promise<void>) {
  const connectionError = ref('')
  const lastUpdate = ref<Date | null>(null)
  let alive = true
  let timer: ReturnType<typeof setTimeout> | undefined
  let running = false
  async function refresh() {
    if (running || !alive) return
    if (timer) clearTimeout(timer)
    running = true
    try { await load(); connectionError.value = ''; lastUpdate.value = new Date() }
    catch (error) { connectionError.value = error instanceof Error ? error.message : '서버 상태를 확인할 수 없습니다.' }
    finally {
      running = false
      if (alive) timer = setTimeout(refresh, 1000)
    }
  }
  onUnmounted(() => { alive = false; if (timer) clearTimeout(timer) })
  return { refresh, connectionError, lastUpdate }
}

export const labels: Record<string, string> = {
  TRANSFERRING: '다음 구역 이동', RUNNING: '실행 중',
  WAIT_POLICY_STOP: '정지 확인 대기', STOP_POLICY: '정책 중지', TRANSFERRED: '인계 확인 · 정지 대기',
  SHOPPING: '쇼핑 중', CHECKOUT_REQUESTED: '주문 마감', DELIVERING: '인계 준비',
  COMPLETED: '시연 흐름 완료', ERROR: '작업 중단', RECOVERY_REQUIRED: '복구 확인 필요',
  QUEUED: '작업 대기', WAIT_ZONE: '구역 사용 대기', MOVING: '이동 중',
  WAIT_LOADED: '적재 완료 · 구역 대기', WAIT_UNLOAD: 'C 도착 · 하역 대기', WAIT_STOP: '정차 확인 대기', WAIT_BASKET: '장바구니 대기', ARM_WORK: '로봇팔 작업',
  WAIT_ARM_CLEAR: '팔 이탈 확인 대기', LEAVING: '구역에서 이동', WAIT_EXIT: '구역 이탈 확인 대기', DONE: '작업 완료',
  NAVIGATE: '지점 이동', PICK: '집기·적재', HANDOFF: '고객 인계', LEAVE: '구역 출발', STOP: '중단 요청', LOAD: '적재',
  CREATED: '전송 대기', SENT: '전송됨', ACCEPTED: '수락됨', SUCCEEDED: '실행 완료', FAILED: '실패 보고',
  UNCERTAIN: '결과 불명', CANCELLED: '전송 취소',
}
export const label = (value: string) => labels[value] || value
export const zoneName = (value: string) => ({ 'load-a': '적재 A', 'load-b': '적재 B', handoff: '하역' }[value] || value)
export const shortId = (value: string | null) => value ? value.slice(0, 8) : '—'
export const timeText = (value: number | null) => value ? new Date(value * 1000).toLocaleTimeString('ko-KR') : '—'
