"""Opt-in order integration for the mathematical route world, never hardware.

V4: one moving robot, direct A -> B -> handoff, home only after handoff.
Source and destination reservations survive all uncertain outcomes.
"""
from copy import deepcopy
from functools import lru_cache
import math

from robot_gateway.mock import make_event
from robots.pinky import compact
from robots.pinky.compact import BACKEND, FRAME, VERSION, bundle, route
from robots.pinky.reference.route_validation import pair_step_clear
from robots.pinky.reference.route_paths import angle_delta
from .distributed import DistributedEngine
from .domain import Engine, atomic, require, uid, digest
from .motion_tests import validate_sample

ZONES = {'load-a': 'A', 'load-b': 'B', 'handoff': 'handoff'}
FINAL = {'SUCCEEDED', 'FAILED', 'CANCELLED'}


@lru_cache(maxsize=128)
def clears_stationary(route_id, pose):
    r = route(route_id)
    r.check()
    return all(pair_step_clear(r.config, a, b, pose, pose) for a, b in zip(r.poses, r.poses[1:]))


class ReferenceEngine(DistributedEngine):
    motion_policy = 'reference_v4'
    def __init__(self, *args, **kwargs):
        require(kwargs.get('mode', 'mock') == 'mock', '도로 기준 실행은 MOCK 전용입니다')
        super().__init__(*args, **kwargs)

    def _fresh(self):
        state = super()._fresh()
        state['road'] = dict(backend=BACKEND, frame_id=FRAME, source_hash=bundle()[3], route_version=VERSION,
            physical_hardware_verified=False, physics_tracking=False, active=None, blocked=None,
            jobs={}, waiting={}, rate=4, fail_next=False, robots={
                'pinky-1': dict(location='front', pose=route('home_to_A').poses[0], sample=None, staging=False),
                'pinky-2': dict(location='back', pose=route('queue_advance').poses[0], sample=None, staging=False)})
        return state

    def _recover(self):
        require('road' in self.state, '도로 통합은 별도 DB로 시작하세요. 기존 DB를 자동 변환하지 않습니다')
        require(self.state['road']['source_hash'] == bundle()[3], '기존 실행과 도로 기준 해시가 다릅니다')
        super()._recover()
        road = self.state['road']
        road['blocked'] = '서버 재시작: 위치와 점유 보존, 새 모의 실행 필요'
        if road['active']:
            job = road['jobs'][road['active']]
            job.update(status='UNCERTAIN', stop_requested_at=self.clock())

    def _plan_trip(self, session):
        # Freeze the manifest on first dispatch. New orders go in the next trip.
        trip = self.state['trips'].get(session.get('active_trip'))
        if trip and trip.get('dispatched'):
            return
        super()._plan_trip(session)

    def _next_task(self, session):
        queued = [t for t in self.state['tasks'].values() if t['session_id'] == session['id'] and t['state'] == 'QUEUED']
        if queued:
            return min(queued, key=lambda t: (list(ZONES).index(t['zone_id']), t['created_at']))
        outstanding = [i for i in session['inventory'] if not i['delivered']]
        if session['checkout_requested'] and outstanding:
            task = self._task(session, 'HANDOFF', 'handoff',
                [{k:i[k] for k in ('sku','slot','item_id')} for i in outstanding])
            task['trip_id'] = session['active_trip']
            self.state['trips'][session['active_trip']]['state'] = 'HANDOFF'
            session['state'] = 'DELIVERING'
            return task

    def _pump(self):
        road = self.state['road']
        if road['blocked'] or self.state['device_tests']['hold'] or self.test_only:
            return
        if any(s['error'] for s in self.state['sessions'].values()):
            self._block_road('작업 오류: 이동과 작업장 점유를 보존합니다')
            return
        for session in self.state['sessions'].values():
            if not session['current_task'] and session['state'] != 'COMPLETED':
                self._plan_trip(session)
                task = self._next_task(session)
                if task:
                    session['current_task'] = task['id']
                    task['state'] = 'WAIT_ZONE'
                    self.state['zones'][task['zone_id']]['queue'].append(task['id'])
                elif self._complete_shopping(session):
                    self.state['robots'][session['robot_id']]['session_id'] = None
            if session['current_task']:
                task = self.state['tasks'][session['current_task']]
                if task['state'] in {'WAIT_STOP','WAIT_BASKET'} and self._observed(task['stopped_at']):
                    if task['kind'] == 'HANDOFF' and not self._ready(task):
                        task['state'] = 'WAIT_BASKET'
                    elif self.state['devices'][task['device_id']]['connected']:
                        task['state'] = 'ARM_WORK'
                        self._command(task, 'PICK' if task['kind'] == 'LOAD' else 'HANDOFF', task['device_id'])
        self._plan_road()

    def _plan_road(self):
        road = self.state['road']
        if road['active'] or road['blocked'] or self.state['device_tests']['hold'] or self.test_only:
            return
        road['waiting'] = {}
        robots = road['robots']
        front = next((rid for rid, r in robots.items() if r['location'] == 'front'), None)
        back = next((rid for rid, r in robots.items() if r['location'] == 'back'), None)
        if not front and back:
            self._new_route(back, 'queue_advance', 'front', 'QUEUE_ADVANCE')
            return
        # Empty leader rotation uses only the two verified handoff/home routes.
        # It never runs a handoff policy or records any merchandise.
        for rid, r in robots.items():
            if r['staging'] and not back:
                target = 'back' if front else 'front'
                self._new_route(rid, 'handoff_to_home_' + target, target, 'QUEUE_REJOIN')
                return
        tasks = sorted((self.state['tasks'][s['current_task']] for s in self.state['sessions'].values() if s['current_task']),
                       key=lambda t: -list(ZONES).index(t['zone_id']))
        for task in tasks:
            rid = task['robot_id']; session = self._session(task['session_id'])
            if not self.state['devices'][rid]['connected']:
                continue
            if task['state'] == 'LEAVING' and task['kind'] == 'HANDOFF':
                if back:
                    road['waiting'][rid] = '대기 후열이 비워지기를 기다립니다'
                    continue
                target = 'back' if front else 'front'
                cmd = self._leave(task)
                self._new_route(rid, 'handoff_to_home_' + target, target, 'ORDER', cmd)
                return
            if task['state'] not in {'WAIT_ZONE','LEAVING'}:
                continue
            origin = task if task['state'] == 'LEAVING' else None
            target_task = self._next_task(session) if origin else task
            if target_task is None:
                road['waiting'][rid] = '쇼핑 종료 요청 대기 · 현재 적재장 점유 유지'
                continue
            zone = self.state['zones'][target_task['zone_id']]
            if target_task['id'] not in zone['queue']:
                zone['queue'].append(target_task['id'])
            if zone['owner'] and (not origin or zone['owner'] != origin['id']):
                road['waiting'][rid] = target_task['zone_id'] + ' 사용 순서 대기'
                continue
            if not self.state['devices'][target_task['device_id']]['connected']:
                continue
            if not origin and rid != front:
                road['waiting'][rid] = '대기 선두 진입 대기'
                continue
            if origin and origin['zone_id'] == target_task['zone_id']:
                # Multiple orders in one frozen trip may share the same station.
                # Carry the original parking evidence, never refresh its timestamp.
                if not self._observed(origin['stopped_at']):
                    self._fault(origin, '같은 적재장 후속 작업의 정차 관측 만료')
                    return
                self._finish_origin(origin, moved=False)
                zone['owner'] = target_task['id']; zone['queue'].remove(target_task['id'])
                session['current_task'] = target_task['id']
                target_task.update(state='WAIT_STOP', stopped_at=origin['stopped_at'])
                self._log('station_work_continued', {'parking_source_task':origin['id']}, task=target_task)
                return
            route_id = ('home' if not origin else ZONES[origin['zone_id']]) + '_to_' + ZONES[target_task['zone_id']]
            other = next(v for k,v in robots.items() if k != rid)
            if not clears_stationary(route_id, tuple(other['pose'])):
                road['waiting'][rid] = '정차 로봇·바구니와 경로 간격 대기'
                continue
            zone['owner'] = target_task['id']; zone['queue'].remove(target_task['id'])
            session['current_task'] = target_task['id']; target_task['state'] = 'MOVING'
            self.state['trips'][target_task['trip_id']]['dispatched'] = True
            cmd = self._command(target_task, 'NAVIGATE', rid)
            if origin: origin['state'] = 'TRANSFERRING'
            self._new_route(rid, route_id, ZONES[target_task['zone_id']], 'ORDER', cmd, origin)
            return
        if front and back:
            waiting = any(t['robot_id'] == back and t['state'] == 'WAIT_ZONE' for t in tasks)
            leader_busy = any(t['robot_id'] == front for t in tasks)
            if waiting and not leader_busy and not self.state['zones']['handoff']['owner']:
                if all(self.state['devices'][r]['connected'] for r in (front, back)):
                    self.state['zones']['handoff']['owner'] = 'queue:' + front
                    self._new_route(front, 'home_to_handoff', 'handoff', 'QUEUE_YIELD')

    def _leave(self, task):
        return next(c for c in self.state['commands'].values() if c['task_id'] == task['id'] and c['kind'] == 'LEAVE')

    def _finish_origin(self, task, moved=True):
        cmd = self._leave(task)
        cmd.update(status='SUCCEEDED' if moved else 'CANCELLED', result={'kind':'SUCCEEDED' if moved else 'CANCELLED',
            'data':{'source':BACKEND, 'outside':moved, 'reason':'target_arrival' if moved else 'same_station_no_departure'}})
        self.state['zones'][task['zone_id']]['owner'] = None
        task['state'] = 'DONE'
        self._log('zone_released' if moved else 'same_station_task_completed', {'physical':False}, task=task)

    def _new_route(self, rid, route_id, target, purpose, command=None, origin=None):
        road = self.state['road']; r = route(route_id)
        pose = road['robots'][rid]['pose']
        require(math.dist(pose[:2], r.poses[0][:2]) < 1e-6 and abs(angle_delta(pose[2], r.poses[0][2])) < 1e-6,
                '경로 시작 위치 불일치')
        other = next(v for k, v in road['robots'].items() if k != rid)
        require(clears_stationary(route_id, tuple(other['pose'])), '정차 로봇·바구니와 이동 경로 충돌')
        jid = uid()
        job = dict(id=jid, run_id=self.state['run_id'], task_id=command['task_id'] if command else jid,
            session_id=command['session_id'] if command else None, robot_id=rid, mode='mock', kind='NAVIGATE',
            node_id='gateway-a', backend=BACKEND, source_hash=bundle()[3], frame_id=FRAME, route_version=VERSION,
            parameters=dict(robot_id=rid, route_id=route_id, rate=road['rate']), purpose=purpose, target=target,
            order_command_id=command['id'] if command else None, status='CREATED', instance_id=None,
            origin_task_id=origin['id'] if origin else None,
            command_ids=([command['id']] if command else []) + ([self._leave(origin)['id']] if origin else []),
            created_at=self.clock(), sent_at=None, accepted_at=None, started_at=None, ended_at=None,
            created_monotonic=self.receiver_clock(), receiver_epoch=self.receiver_epoch,
            stop_requested_at=None, stop_ack_at=None, stopped=None, telemetry=None, telemetry_signature=None,
            simulate_failure=road['fail_next'], events={}, timeline=[], timeout_seconds=r.duration / road['rate'] + 30)
        road['fail_next'] = False
        road['jobs'][jid] = job; road['active'] = jid
        self._road_log(job, 'RESERVED', {'route': route_id, 'purpose': purpose, 'lease': 'whole-aisle'})

    def _road_log(self, job, kind, data=None):
        row = dict(at=self.clock(), kind=kind, data=data or {})
        job['timeline'].append(row)
        self._log('road_' + kind.lower(), dict(road_job_id=job['id'], robot_id=job['robot_id'], **row),
                  session_id=job['session_id'])

    @atomic
    def node_heartbeat(self, node_id, instance_id, role='control'):
        out = DistributedEngine.node_heartbeat.__wrapped__(self, node_id, instance_id, role)
        return {**out, 'motion_backend': BACKEND, 'route_version': VERSION}

    @atomic
    def cancel_order(self, sid, order_id):
        road = self.state['road']; job = road['jobs'].get(road['active'])
        if job and job['session_id'] == sid:
            require(job['status'] == 'CREATED' and not job['origin_task_id'], '이동 전송 또는 작업장 간 이동 준비 후 자동 취소 불가')
            # Engine validates the order and restores reservations in the same transaction.
            if self.state['tasks'][job['task_id']].get('order_id') == order_id:
                job.update(status='CANCELLED', ended_at=self.clock())
                road['active'] = None
        result = Engine.cancel_order.__wrapped__(self, sid, order_id)
        session = self._session(sid)
        trip = self.state['trips'].get(session['active_trip'])
        if trip and all(self.state['units'][i]['state'] == 'CANCELLED' for i in trip['unit_ids']):
            trip['state'] = 'DONE'; session['active_trip'] = None
        return result

    @atomic
    def reset_mock(self, acknowledge_unresolved=False):
        require(not (self.state['road']['active'] or self.state['road']['blocked']) or acknowledge_unresolved,
                '이동 점유가 남아 있습니다. 가상 실행 폐기를 확인하세요')
        return Engine.reset_mock.__wrapped__(self, acknowledge_unresolved)

    def node_work(self, node_id, instance_id):
        out = super().node_work(node_id, instance_id)
        out['commands'] = {k:c for k,c in out['commands'].items() if not c['device_id'].startswith('pinky-')}
        return out

    @atomic
    def node_claim(self, node_id, instance_id):
        node = self._node(node_id, instance_id)
        require(node.get('role', 'control') == 'control' and not self.test_only, '운영용 중계만 주문을 실행합니다')
        cmd = Engine.claim.__wrapped__(self, node_id, [d for d in node['devices'] if not d.startswith('pinky-')])
        if cmd:
            self.state['commands'][cmd['id']].update(gateway_id=node_id, instance_id=instance_id)
            return deepcopy(self.state['commands'][cmd['id']])

    @atomic
    def node_event(self, node_id, instance_id, event):
        cmd = self._owned_command(node_id, instance_id, event['command_id'])
        require(not cmd['device_id'].startswith('pinky-'), 'Pinky 결과는 도로 관측 계약으로 수신합니다')
        return Engine.event.__wrapped__(self, event)

    @atomic
    def mock_action(self, node_id, instance_id, command_id, action):
        cmd = self._owned_command(node_id, instance_id, command_id)
        require(not cmd['device_id'].startswith('pinky-'), 'Pinky는 기준 경로 실행부의 관측만 사용합니다')
        return DistributedEngine.mock_action.__wrapped__(self, node_id, instance_id, command_id, action)

    @atomic
    def motion_poll(self, node, instance, profile, available):
        gateway = self._node(node, instance)
        require(node == 'gateway-a' and gateway.get('role', 'control') == 'control', 'Pinky 담당 운영 중계가 아닙니다', 403)
        require(profile.get('motion_backend') == BACKEND and profile.get('source_hash') == bundle()[3], '도로 출처 불일치')
        road = self.state['road']; job = road['jobs'].get(road['active'])
        if job and job['status'] == 'CREATED' and available and profile.get('allow_motion'):
            job.update(status='SENT', sent_at=self.clock(), instance_id=instance)
            for cid in job['command_ids']:
                cmd = self.state['commands'][cid]
                require(cmd['status'] == 'CREATED', '주문 명령 상태가 바뀌었습니다')
                cmd.update(status='SENT', sent_at=self.clock(), gateway_id=node, instance_id=instance)
                self._log('command_sent', {'gateway_id':node, 'road_job_id':job['id']}, command=cmd)
            self._road_log(job, 'SENT')
        return dict(run_id=self.state['run_id'], job=deepcopy(job) if job and job['instance_id'] == instance and job['status'] not in FINAL else None,
                    closed_ids=[j['id'] for j in road['jobs'].values() if j['status'] in FINAL])

    def _order_event(self, job, kind, data=None):
        cmd = self.state['commands'][job['order_command_id']]
        return Engine.event.__wrapped__(self, make_event(cmd, kind, data, self.clock()))

    @atomic
    def motion_event(self, node, instance, jid, event_id, kind, data):
        self._node(node, instance)
        road = self.state['road']; require(jid in road['jobs'], '도로 명령 없음', 404)
        job = road['jobs'][jid]
        require(node == 'gateway-a' and job['instance_id'] == instance, '이전/다른 중계의 도로 명령', 403)
        signature = digest([kind, data])
        if kind != 'PROGRESS' and event_id in job['events']:
            require(job['events'][event_id] == signature, '같은 결과 ID의 내용 불일치')
            return {'received': True}
        if kind in {'FINISHED','ERROR'} and job.get('result'):
            require(job['result'] == data and job.get('result_kind') == kind, '이미 보고된 이동 결과와 충돌합니다')
            job['events'][event_id] = signature
            return {'received':True, 'duplicate':True}
        require(road['active'] == jid and job['status'] not in FINAL, '현재 도로 명령이 아닙니다')
        if kind == 'ACCEPTED':
            require(job['status'] == 'SENT', '전송 후 수락 필요')
            job.update(status='ACCEPTED', accepted_at=self.clock())
            for cid in job['command_ids']:
                cmd = self.state['commands'][cid]
                require(cmd['status'] == 'SENT', '명령 전송 상태 불일치')
                cmd.update(status='ACCEPTED', accepted_at=self.clock())
                self._log('command_accepted', {'road_job_id':jid}, command=cmd)
        elif kind == 'STARTED':
            require(job['status'] == 'ACCEPTED' and not job['stop_requested_at'], '실행 전 중지/상태 확인 필요')
            job.update(status='RUNNING', started_at=self.clock(), started_monotonic=self.receiver_clock())
        elif kind == 'PROGRESS':
            # After a stop request, drain fresh telemetry so STOP_ACK / ERROR can
            # follow it in the durable outbox. Uncertainty never releases a lease.
            require(job['status'] in {'RUNNING','UNCERTAIN'}, '실행 중 관측만 허용합니다')
            changed = validate_sample(self, job, data.get('sample'), compact)
            if changed:
                road['robots'][job['robot_id']].update(pose=job['telemetry']['pose'], sample=deepcopy(job['telemetry']))
                if self.clock() - job.get('progress_log_at', -100) >= 2:
                    job['progress_log_at'] = self.clock()
                    self._road_log(job, kind, {'progress':job['telemetry']['progress']})
            return {'received':True, 'duplicate':not changed}
        elif kind == 'STOP_ACK':
            require(job['stop_requested_at'] is not None, '중지 요청 없음')
            job['stop_ack_at'] = self.clock()
        elif kind in {'FINISHED', 'ERROR'}:
            require(job['status'] in {'SENT','ACCEPTED','RUNNING','UNCERTAIN'}, '실행 상태 오류')
            if data.get('sample'):
                validate_sample(self, job, data['sample'], compact)
                require(data['sample']['halted'] is True, '실행부 정지 관측 필요')
                job['stopped'] = dict(source=BACKEND, physical=False, at=self.clock())
                road['robots'][job['robot_id']].update(pose=data['sample']['pose'], sample=deepcopy(job['telemetry']))
            elif data.get('not_executed') and job['started_at'] is None:
                job['stopped'] = dict(source='not_executed', physical=False, at=self.clock())
            if kind == 'FINISHED':
                require(job['status'] == 'RUNNING' and not job['stop_requested_at'] and not road['blocked']
                        and data.get('outcome') == 'SUCCEEDED' and data.get('sample', {}).get('arrived') and job['stopped'], '도착·정지 확인 전 성공 불가')
                robot = road['robots'][job['robot_id']]
                robot.update(location=job['target'], staging=job['purpose'] == 'QUEUE_YIELD')
                if job['origin_task_id']:
                    self._finish_origin(self.state['tasks'][job['origin_task_id']])
                if job['purpose'] == 'QUEUE_REJOIN':
                    require(self.state['zones']['handoff']['owner'] == 'queue:' + job['robot_id'], '대기열 조정 점유 불일치')
                    self.state['zones']['handoff']['owner'] = None
                if job['order_command_id']:
                    cmd = self.state['commands'][job['order_command_id']]
                    self._order_event(job, 'SUCCEEDED', {'source':BACKEND, 'road_job_id':jid})
                    if cmd['kind'] == 'NAVIGATE':
                        self.state['mock_world']['positions'][job['robot_id']] = cmd['zone_id']
                        self._order_event(job, 'STOPPED', {'stopped':True, 'zone_id':cmd['zone_id']})
                    else:
                        self.state['mock_world']['positions'][job['robot_id']] = 'outside'
                        self._order_event(job, 'EXITED', {'outside':True, 'zone_id':cmd['zone_id']})
                job['status'] = 'SUCCEEDED'; road['active'] = None
            else:
                job['status'] = ('CANCELLED' if job['stop_requested_at'] else 'FAILED') if job['stopped'] else 'UNCERTAIN'
                self._block_road(str(data.get('reason', data.get('error', '이동 실패')))[:200])
            job.update(ended_at=self.clock(), result=deepcopy(data), result_kind=kind)
        else:
            require(False, '도로 이벤트 오류', 422)
        job['events'][event_id] = signature
        self._road_log(job, kind, data)
        return {'received':True}

    def _block_road(self, reason):
        road = self.state['road']; road['blocked'] = reason
        job = road['jobs'].get(road['active'])
        if job:
            job['stop_requested_at'] = job['stop_requested_at'] or self.clock()
            if job['status'] not in FINAL: job['status'] = 'UNCERTAIN'
            self._road_log(job, 'HELD', {'reason':reason, 'lease_released':False})
        for session in self.state['sessions'].values():
            if session['current_task']:
                Engine._fault(self, self.state['tasks'][session['current_task']], reason)
        road['stop_requests'] = {rid: {'requested_at':self.clock(), 'physical_stop_confirmed':False}
                                 for rid in road['robots']}

    @atomic
    def motion_stop(self):
        require(self.state['road']['active'], '실행 중 이동이 없습니다')
        self._block_road('관제에서 이동 중지를 요청했습니다')
        return self.motion_snapshot()

    @atomic
    def motion_failure(self):
        self.state['road']['fail_next'] = True
        return {'next_route_failure':True}

    @atomic
    def watchdog(self):
        for session in self.state['sessions'].values():
            task = self.state['tasks'].get(session['current_task'])
            if (task and task['state'] in {'WAIT_STOP','WAIT_BASKET'} and task['stopped_at'] is not None
                    and not self._observed(task['stopped_at'])):
                self._fault(task, '모의 정차 관측 유효기간 만료: 위치를 다시 확인해야 합니다')
        road = self.state['road']; job = road['jobs'].get(road['active'])
        if not job or job['status'] in FINAL or road['blocked']: return
        gateway = self.state['gateways']['gateway-a']
        expired = job['receiver_epoch'] != self.receiver_epoch or self.receiver_clock()-job['created_monotonic'] > job['timeout_seconds']
        stale = job['status'] == 'RUNNING' and self.receiver_clock() - (job.get('telemetry') or {}).get('received_monotonic', job['started_monotonic']) > 3
        lost = job['sent_at'] is not None and (not self._fresh_observation_node(gateway) or gateway['instance_id'] != job['instance_id'])
        fault = job['order_command_id'] and self.state['sessions'][job['session_id']]['error']
        if expired or stale or lost or fault: self._block_road('이동 관측 만료·연결 또는 작업 오류: 통행 점유 유지')

    def motion_snapshot(self):
        with self.lock:
            out = deepcopy(self.state['road'])
            for job in out['jobs'].values():
                job.pop('events', None)
            for rid, r in out['robots'].items():
                s = r['sample']
                r['age_seconds'] = (max(0, self.receiver_clock()-s['received_monotonic'])
                                    if s and s['receiver_epoch'] == self.receiver_epoch else None)
                r['session_id'] = self.state['robots'][rid]['session_id']
            return out

    def snapshot(self, sid=None):
        out = super().snapshot(sid)
        out.pop('road', None)
        out['motion_backend'] = BACKEND
        out['route_version'] = VERSION
        return out

    def _invariants(self):
        super()._invariants()
        road = self.state['road']
        active = road['jobs'].get(road['active'])
        assert sum(j['status'] in {'SENT','ACCEPTED','RUNNING'} for j in road['jobs'].values()) <= 1
        if active and active['origin_task_id']:
            origin = self.state['tasks'][active['origin_task_id']]
            assert self.state['zones'][origin['zone_id']]['owner'] == origin['id']
        if active and active['order_command_id']:
            cmd = self.state['commands'][active['order_command_id']]
            assert self.state['zones'][cmd['zone_id']]['owner'] == cmd['task_id']
