import type { Session, Snapshot } from '../types'

export const robotName = (id: string) => ({ 'pinky-1': 'Pinky 1', 'pinky-2': 'Pinky 2', 'omx-a': 'OMX · 적재 A', 'omx-b': 'OMX · 적재 B', 'omx-handoff': 'OMX · 하역' }[id] || id)
export const orderedCount = (state: Snapshot, sid: string) => Object.values(state.orders).filter(o => o.session_id === sid && o.status !== 'CANCELLED')
  .reduce((total, order) => total + Object.values(order.items).reduce((a, b) => a + b, 0), 0)
export const currentTask = (state: Snapshot, session: Session) => session.current_task ? state.tasks[session.current_task] : undefined
export const needsBasket = (state: Snapshot, session: Session) => {
  const task = currentTask(state, session)
  return task?.kind === 'HANDOFF' && ['MOVING', 'WAIT_STOP', 'WAIT_BASKET'].includes(task.state) && !session.error
}
export const nodeOnline = (state: Snapshot, id: string) => {
  const node = state.gateways?.[id]
  return !!node?.connected && node.heartbeat_at !== null && state.server_time - node.heartbeat_at < 10
}
