"""Persisted commissioning jobs. Never write the customer quantity ledger."""
from copy import deepcopy
from functools import wraps
import json

from .domain import atomic, require, uid, digest

MOTION = {'PICK', 'HANDOFF', 'NAVIGATE'}
FINAL = {'SUCCEEDED', 'FAILED', 'CANCELLED'}
DEVICES = {'gateway-a': ('omx-a', 'load-a'), 'gateway-b': ('omx-b', 'load-b'),
           'gateway-c': ('omx-handoff', 'handoff')}


def empty():
    return {'jobs': {}, 'nodes': {}, 'hold': None}


def mutation(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        return atomic(lambda engine: method(self, *args, **kwargs))(self.e)
    return wrapped


class Bench:
    def __init__(self, engine):
        self.e = engine

    @property
    def state(self):
        return self.e.state['device_tests']

    def log(self, job, kind, data=None):
        row = {'at': self.e.clock(), 'kind': kind, 'data': data or {}}
        job['timeline'].append(row)
        self.e._log('device_test_' + kind.lower(), {'test_id': job['id'], 'node_id': job['node_id'], **row})

    def job(self, jid):
        require(jid in self.state['jobs'], '시험 명령을 찾을 수 없습니다', 404)
        return self.state['jobs'][jid]

    def snapshot(self):
        with self.e.lock:
            out = deepcopy(self.state)
            out.update(mode=self.e.mode, test_only=self.e.test_only, server_time=self.e.clock(),
                       distributed=self.e.state.get('gateway_mode') == 'distributed')
            for job in out['jobs'].values():
                job.pop('events', None)
                sample = job.get('telemetry')
                if sample:
                    sample['age_seconds'] = (max(0., self.e.receiver_clock() - sample['received_monotonic'])
                                             if sample['receiver_epoch'] == self.e.receiver_epoch else None)
            for node, value in out['nodes'].items():
                gateway = self.e.state.get('gateways', {}).get(node, {})
                value['online'] = bool(gateway.get('connected') and gateway.get('instance_id') == value['instance_id']
                                       and self.e.clock() - value['at'] < 5)
            return out

    @mutation
    def create(self, node, kind, parameters, request_id, prepared=False, simulate_failure=False):
        require(self.e.state.get('gateway_mode') == 'distributed', '장비 테스트는 분산 중계 모드에서 사용합니다')
        require(node in DEVICES and kind in {'PING', 'INSPECT', *MOTION}, '시험 대상/명령 오류', 422)
        require(not simulate_failure or (self.e.mode == 'mock' and kind in MOTION), '가상 실패는 모의 동작 시험에서만 사용합니다', 422)
        signature = digest([node, kind, parameters, prepared, simulate_failure])
        for job in self.state['jobs'].values():
            if job['request_id'] == request_id:
                require(job['signature'] == signature, '같은 요청 ID에 다른 시험 내용입니다')
                return deepcopy(job)
        require(len(self.state['jobs']) < 500, '현재 실행의 시험 기록 한도입니다. 기록을 보관하고 새 실행을 준비하세요')
        require(not any(j['node_id'] == node and (j['status'] not in FINAL or (j['kind'] in MOTION and j['released_at'] is None))
                        for j in self.state['jobs'].values()), '해당 중계의 이전 시험 종료·확인을 먼저 완료하세요')
        report = self.state['nodes'].get(node, {})
        gateway = self.e.state['gateways'][node]
        if kind in MOTION:
            road = self.e.state.get('road', {})
            require(not road.get('active') and not road.get('blocked'), '주문 이동 또는 이동 복구가 진행 중입니다')
            require(kind != 'NAVIGATE' or not road, 'v4 주문 통합에서는 독립 v3 이동 시험을 실행하지 않습니다. 별도 기본 미리보기를 사용하세요')
            require(prepared is True, '고정 바구니·작업 영역 준비를 확인하세요')
            require(not self.state['hold'], '이전 동작 시험의 정지·원위치 확인이 필요합니다')
            require(not any(t['state'] not in {'DONE', 'CANCELLED'} for t in self.e.state['tasks'].values())
                    and not any(u['state'] not in {'DELIVERED', 'CANCELLED'} for u in self.e.state['units'].values())
                    and not any(s['error'] for s in self.e.state['sessions'].values()), '주문 작업 또는 복구할 상태가 남아 있습니다')
            require(report.get('instance_id') == gateway.get('instance_id') and gateway.get('connected')
                    and self.e.clock() - report.get('at', 0) < 5, '시험 실행부의 최신 준비 상태가 필요합니다')
            require(report.get('allow_motion') is True, '동작 시험 실행부가 준비되지 않았습니다')
            require(kind in report.get('operations', []), '중계가 지원하지 않는 시험입니다')
            if kind == 'NAVIGATE':
                from .motion_tests import validate_request
                validate_request(self.e, node, parameters, report)
            elif kind == 'PICK':
                require(node != 'gateway-c' and set(parameters) == {'sku', 'slot', 'robot_id'}, '적재 시험 입력 오류', 422)
                require(parameters['sku'] in self.e.products and self.e.products[parameters['sku']]['station'] == DEVICES[node][1], '해당 적재장의 상품을 선택하세요', 422)
                require(type(parameters['slot']) is int and parameters['slot'] in (0, 1, 2)
                        and parameters['robot_id'] in ('pinky-1', 'pinky-2'), '슬롯 또는 바구니 배치 오류', 422)
                if self.e.mode == 'hardware':
                    require(parameters['slot'] in report.get('slots', {}).get(parameters['robot_id'], []), '선택한 적재 슬롯 자세가 등록되지 않았습니다')
            else:
                require(node == 'gateway-c' and set(parameters) == {'side', 'skus'}, '하역 시험 입력 오류', 422)
                require(parameters['side'] in report.get('sides', []), '해당 방향의 모델이 준비되지 않았습니다')
                require(isinstance(parameters['skus'], list) and 1 <= len(parameters['skus']) <= 3
                        and all(s in self.e.products for s in parameters['skus']), '하역 상품은 1~3개를 선택하세요', 422)
        else:
            require(not parameters, '통신·설정 검사는 추가 동작 인수를 받지 않습니다', 422)
        jid = uid()
        job = {'id': jid, 'run_id': self.e.state['run_id'], 'request_id': request_id, 'signature': signature, 'node_id': node,
               'device_id': DEVICES[node][0], 'zone_id': DEVICES[node][1], 'kind': kind,
               'mode': self.e.mode, 'parameters': deepcopy(parameters), 'status': 'CREATED',
               'simulate_failure': simulate_failure,
               'created_at': self.e.clock(), 'sent_at': None, 'accepted_at': None, 'started_at': None,
               'ended_at': None, 'instance_id': None, 'stop_requested_at': None, 'stop_ack_at': None,
               'stopped': None, 'review': None, 'released_at': None, 'observation': None,
               'result': None, 'timeline': [], 'events': {}}
        self.state['jobs'][jid] = job
        if kind == 'NAVIGATE':
            from robots.pinky.catalog import BACKEND, FRAME, VERSION, bundle, route
            job.update(device_id=parameters['robot_id'], robot_id=parameters['robot_id'],
                       task_id=jid, session_id=None, zone_id='reference-trial',
                       backend=BACKEND, frame_id=FRAME, route_version=VERSION, source_hash=bundle()[3],
                       receiver_epoch=self.e.receiver_epoch, created_monotonic=self.e.receiver_clock(),
                       telemetry=None, telemetry_signature=None,
                       timeout_seconds=route(parameters['route_id']).duration / parameters['rate'] + 30)
        if kind in MOTION:
            self.state['hold'] = jid
        self.log(job, 'CREATED', {'kind': kind, 'parameters': parameters, 'prepared_by_operator': prepared, 'simulate_failure': simulate_failure})
        return deepcopy(job)

    @mutation
    def poll(self, node, instance, profile, available):
        self.e._node(node, instance)
        require(len(json.dumps(profile)) <= 24000, '준비 상태 데이터가 너무 큽니다', 413)
        self.state['nodes'][node] = {**deepcopy(profile), 'instance_id': instance, 'at': self.e.clock()}
        jobs = [j for j in self.state['jobs'].values() if j['node_id'] == node]
        current = next((j for j in jobs if j['instance_id'] == instance
                        and j['status'] not in FINAL and j['released_at'] is None), None)
        if current is None and available:
            current = next((j for j in jobs if j['status'] == 'CREATED'), None)
            if current:
                current.update(status='SENT', instance_id=instance, sent_at=self.e.clock())
                self.log(current, 'SENT')
        return {'job': deepcopy(current), 'run_id': self.e.state['run_id'],
                'closed_ids': [j['id'] for j in jobs if j['released_at'] is not None or (j['kind'] not in MOTION and j['status'] in FINAL)]}

    @mutation
    def event(self, node, instance, jid, event_id, kind, data):
        self.e._node(node, instance)
        job = self.job(jid)
        require(job['node_id'] == node and job['instance_id'] == instance, '다른 중계 또는 이전 실행의 시험입니다', 403)
        require(len(json.dumps(data)) <= 24000, '시험 결과가 너무 큽니다', 413)
        if kind == 'PROGRESS':
            require(job['kind'] == 'NAVIGATE' and job['mode'] == 'mock'
                    and job['status'] == 'RUNNING', '현재 도로 모의 시험의 진행 보고가 아닙니다')
            from .motion_tests import validate_sample
            changed = validate_sample(self.e, job, data.get('sample'))
            if changed and (job.get('progress_log_at') is None or self.e.clock() - job['progress_log_at'] >= 2):
                job['progress_log_at'] = self.e.clock()
                self.log(job, 'PROGRESS', {'pose': job['telemetry']['pose'], 'progress': job['telemetry']['progress'],
                                         'source': job['backend'], 'sequence': job['telemetry']['sequence']})
            return {'received': True, 'duplicate': not changed}
        signature = digest([kind, data])
        if event_id in job['events']:
            require(job['events'][event_id] == signature, '중복 결과 내용이 다릅니다')
            return {'received': True}
        require(job['status'] not in FINAL, '종료한 시험에 새 결과를 적용할 수 없습니다')
        if kind == 'ACCEPTED':
            require(job['status'] == 'SENT', '전달된 명령만 수락할 수 있습니다')
            job.update(status='ACCEPTED', accepted_at=self.e.clock())
        elif kind == 'STARTED':
            require(job['status'] == 'ACCEPTED' and not job['stop_requested_at'], '수락·중지 상태를 확인하세요')
            job.update(status='RUNNING', started_at=self.e.clock())
            if job['kind'] == 'NAVIGATE':
                job['started_monotonic'] = self.e.receiver_clock()
        elif kind == 'STOP_ACK':
            require(job['stop_requested_at'] is not None, '중지 요청이 없습니다')
            job['stop_ack_at'] = self.e.clock()
        elif kind in {'FINISHED', 'ERROR'}:
            require(job['status'] in {'RUNNING', 'UNCERTAIN', 'ACCEPTED'}
                    or (job['status'] == 'SENT' and kind == 'ERROR' and data.get('not_executed') is True), '실행 상태가 아닙니다')
            require(kind == 'ERROR' or job['started_at'] is not None, '실행 시작 확인 전에는 결과를 받을 수 없습니다')
            if job['kind'] == 'NAVIGATE':
                from .motion_tests import validate_sample
                require(job['mode'] == 'mock', '실물 이동 결과로 사용할 수 없습니다')
                if data.get('sample'):
                    validate_sample(self.e, job, data['sample'])
                    require(data['sample']['halted'] is True, '모의 실행부 정지 확인이 필요합니다')
                    job['stopped'] = {'source': job['backend'], 'at': self.e.clock(), 'physical': False}
                elif data.get('not_executed') is True and job['started_at'] is None:
                    job['stopped'] = {'source': 'not_executed', 'at': self.e.clock(), 'physical': False}
                if kind == 'FINISHED':
                    require(job['status'] == 'RUNNING' and not job['stop_requested_at'] and data.get('outcome') == 'SUCCEEDED'
                            and data.get('sample', {}).get('arrived') is True and job['stopped'],
                            '시간 만료·중지·결과 불명은 이동 성공이 아닙니다')
                job.update(ended_at=self.e.clock(), result={'kind': kind, 'data': deepcopy(data)},
                           status=('SUCCEEDED' if kind == 'FINISHED' else
                                   ('CANCELLED' if job['stop_requested_at'] else 'FAILED') if job['stopped'] else 'UNCERTAIN'))
                job['events'][event_id] = signature
                self.log(job, kind, data)
                return {'received': True}
            job.update(ended_at=self.e.clock(), result={'kind': kind, 'data': deepcopy(data)},
                       status='WAIT_REVIEW' if job['kind'] in MOTION else ('SUCCEEDED' if kind == 'FINISHED' else 'FAILED'))
            stopped = data.get('stop_feedback', {})
            if all(stopped.get(k) is True for k in ('policy_stopped', 'motion_stopped', 'hold_confirmed', 'torque_enabled')):
                job['stopped'] = {'source': 'simulation' if self.e.mode == 'mock' else 'feedback', 'at': self.e.clock(), 'data': stopped}
        else:
            require(False, '지원하지 않는 시험 이벤트입니다', 422)
        job['events'][event_id] = signature
        self.log(job, kind, data)
        return {'received': True}

    @mutation
    def stop(self, jid):
        job = self.job(jid)
        if job['status'] in FINAL or job['stop_requested_at'] is not None:
            return deepcopy(job)
        job['stop_requested_at'] = self.e.clock()
        if job['status'] == 'CREATED':
            job.update(status='CANCELLED', ended_at=self.e.clock(), stopped={'source': 'not_dispatched', 'at': self.e.clock()})
        self.log(job, 'STOP_REQUESTED', {'actual_stop_confirmed': False})
        return deepcopy(job)

    @mutation
    def observe(self, jid, operator, facts):
        job = self.job(jid)
        require(job['kind'] == 'HANDOFF' and job['status'] == 'RUNNING' and not job['stop_requested_at'], '실행 중인 하역 시험에서만 관측할 수 있습니다')
        require(set(facts) == {'cart_visible', 'cart_empty', 'last_item_placed', 'standby_reached'}
                and all(v is True for v in facts.values()), '마지막 담기·카트 비움·대기 자세를 모두 확인하세요')
        job['observation'] = {'source': 'operator', 'operator': operator, 'at': self.e.clock(), 'facts': facts}
        self.log(job, 'OPERATOR_OBSERVATION', job['observation'])
        return deepcopy(job)

    @mutation
    def review(self, jid, operator, success, stopped, note, process_closed=False):
        job = self.job(jid)
        require(job['kind'] in MOTION and job['status'] in {'WAIT_REVIEW', 'UNCERTAIN'}, '결과 확인 대기 상태가 아닙니다')
        require(stopped is True, '로봇의 실제 정지를 확인하세요')
        if job['status'] == 'UNCERTAIN' and job['ended_at'] is None:
            node = self.e.state['gateways'][job['node_id']]
            require(process_closed and (node['instance_id'] != job['instance_id'] or not self.e._fresh_observation_node(node)),
                    '원래 실행부 종료·실제 정지 확인 후 복구할 수 있습니다')
            require(success is False, '결과 불명 시험을 성공으로 복구할 수 없습니다')
        require(not success or (job['result'] and job['result']['kind'] == 'FINISHED' and not job['stop_requested_at']),
                '중단·실행 오류를 성공으로 기록할 수 없습니다')
        if success and job['kind'] == 'HANDOFF':
            require(job['stopped'] is not None and job['observation'] is not None, '담기 관측과 실제 정책 정지 피드백이 필요합니다')
        source = 'simulation' if self.e.mode == 'mock' else 'operator'
        if not job['stopped']:
            job['stopped'] = {'source': source, 'operator': operator, 'at': self.e.clock()}
        job['review'] = {'operator': operator, 'source': source, 'success': success, 'note': note, 'at': self.e.clock()}
        job['status'] = 'SUCCEEDED' if success else ('CANCELLED' if job['stop_requested_at'] else 'FAILED')
        self.log(job, 'REVIEWED', job['review'])
        return deepcopy(job)

    @mutation
    def release(self, jid, operator, restored):
        job = self.job(jid)
        require(self.state['hold'] == jid and job['status'] in FINAL and job['stopped'], '시험 종료·실제 정지 확인이 필요합니다')
        require(restored is True, '상품 수량·원위치·작업 구역 복구를 확인하세요')
        self.state['hold'] = None
        job['released_at'] = self.e.clock()
        self.log(job, 'RELEASED', {'operator': operator, 'stock_and_workspace_restored': True})
        return deepcopy(job)

    @mutation
    def watchdog(self):
        now = self.e.clock()
        for job in self.state['jobs'].values():
            if job['status'] not in {'CREATED', 'SENT', 'ACCEPTED', 'RUNNING'}:
                continue
            node = self.e.state.get('gateways', {}).get(job['node_id'], {})
            expired = now - job['created_at'] > job.get('timeout_seconds', 210 if job['kind'] in MOTION else 15)
            lost = job['sent_at'] is not None and (node.get('instance_id') != job['instance_id']
                    or not node.get('connected') or now - node.get('heartbeat_at', 0) > 10)
            stale = False
            if job['kind'] == 'NAVIGATE':
                expired = (job['receiver_epoch'] != self.e.receiver_epoch or
                           self.e.receiver_clock() - job['created_monotonic'] > job['timeout_seconds'])
                stale = job['status'] == 'RUNNING' and self.e.receiver_clock() - (
                    job.get('telemetry') or {}).get('received_monotonic', job['started_monotonic']) > 3
            if expired or lost or stale:
                job['status'] = 'UNCERTAIN' if job['kind'] in MOTION else 'FAILED'
                job['stop_requested_at'] = job['stop_requested_at'] or now
                self.log(job, 'TIMEOUT_OR_DISCONNECT', {'actual_stop_confirmed': False})
