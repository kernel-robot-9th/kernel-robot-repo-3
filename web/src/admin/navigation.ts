export const adminGroups = [
  { label: '운영', items: [
    { path: '/admin/overview', label: '운영 대시보드', icon: 'grid', section: 'overview' },
    { path: '/admin/orders', label: '주문·진행 관리', icon: 'orders', section: 'orders' },
  ] },
  { label: '로봇·현장', items: [
    { path: '/admin/omx/load-a', label: 'OMX 관리', icon: 'arm', section: 'omx' },
    { path: '/admin/pinky/movement', label: 'Pinky 관리', icon: 'robot', section: 'pinky' },
    { path: '/admin/video', label: '현장 전체 영상', icon: 'camera', section: 'video' },
  ] },
  { label: '관리·점검', items: [
    { path: '/admin/stock', label: '상품·재고', icon: 'package', section: 'stock' },
    { path: '/admin/tests', label: '장비 테스트', icon: 'tools', section: 'tests' },
    { path: '/admin/diagnostics', label: '이력·진단', icon: 'history', section: 'diagnostics' },
  ] },
]
export const adminPages = adminGroups.flatMap(group => group.items)
export const omxStations = [
  { id: 'load-a', name: '적재 A', device: 'omx-a', node: 'gateway-a', feeds: ['load-a'] },
  { id: 'load-b', name: '적재 B', device: 'omx-b', node: 'gateway-b', feeds: ['load-b'] },
  { id: 'handoff', name: '하역', device: 'omx-handoff', node: 'gateway-c', feeds: ['handoff-front', 'handoff-wrist'] },
]
