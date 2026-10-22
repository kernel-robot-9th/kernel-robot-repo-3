"""Test protocol client, usable from Python 3.10 without robot SDK imports."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import platform
import threading
import time
import uuid
import subprocess
import urllib.error
from functools import lru_cache

from .runtime import save_state


class StartRejected(Exception):
    """The server definitively refused permission; no actuator was called."""


@lru_cache(maxsize=1)
def revision():
    try:
        root = Path(__file__).resolve().parents[1]
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        sha = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=root, stderr=subprocess.DEVNULL, timeout=3, creationflags=flags).decode().strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=root, stderr=subprocess.DEVNULL, timeout=3, creationflags=flags).strip())
        return {'commit': sha, 'modified': dirty, 'protocol': 1}
    except (OSError, subprocess.SubprocessError):
        return {'commit': '미확인', 'modified': None, 'protocol': 1}


class HardwareTrials:
    def __init__(self, config, frames, execute=False):
        self.config, self.frames, self.enabled = config, frames, execute
        self.arm, self.observation, self.command = None, None, None
        self.report = self.inspect()

    def inspect(self):
        from .hardware.config import validate
        try:
            issues = validate(self.config, require_mobile=False, check_slots=False)
        except Exception as exc:
            issues = [f'설정 검사 실패: {type(exc).__name__}']
        node = self.config.get('node_id')
        arm = self.config.get('act') if node == 'gateway-c' else self.config.get('yolo')
        arm = arm or {}
        checks = []
        for name in ('serial_by_id', 'camera_by_id', 'front_by_id', 'wrist_by_id', 'calibration_file', 'poses_file', 'calibration_dir'):
            if name in arm:
                value = arm[name]
                checks.append({'name': name, 'state': '경로 있음 · 실제 열기 미확인' if value and Path(value).expanduser().exists() else '경로 미설정·없음'})
        models = arm.get('models', {})
        slots = {robot: [int(slot) for slot, value in arm.get('drop_slots', {}).get(robot, {}).items()
                         if slot in ('0', '1', '2') and isinstance(value, dict) and value.get('approach') and value.get('release')]
                 for robot in ('pinky-1', 'pinky-2')}
        if node != 'gateway-c' and not any(slots.values()):
            issues.append('시험할 바구니·슬롯의 접근/놓기 자세를 한 곳 이상 등록하세요')
        self.report = {'allow_motion': self.enabled and not issues, 'operations': ['HANDOFF'] if node == 'gateway-c' else ['PICK'],
                       'sides': [s for s, m in models.items() if m], 'issues': issues,
                       'checks': checks, 'execution_enabled': self.enabled, 'camera_frames': '미확인',
                       'slots': slots,
                       'robot_connection': '미확인', 'model_inference': '미확인', 'python': platform.python_version(),
                       'inspection': '파일·설정 검사만 수행. 카메라·모터·CUDA를 열지 않음'}
        return self.report

    def read(self, command, kind):
        observation = self.observation
        if kind != 'handoff' or not observation or time.time() - observation['at'] > 2 or observation['at'] > time.time() + 1:
            return None
        return {**observation['facts'], 'confirmed_items': command['items'], 'basket_id': command['basket_id']}

    def execute(self, job, cancelled):
        if not self.inspect()['allow_motion'] or job['mode'] != 'hardware':
            raise RuntimeError('실물 시험 실행 설정이 준비되지 않았습니다')
        params = job['parameters']
        if job['kind'] == 'PICK' and params['slot'] not in self.report['slots'].get(params['robot_id'], []):
            raise RuntimeError('선택한 슬롯의 자세가 등록되지 않았습니다')
        if self.arm is None:
            if job['kind'] == 'HANDOFF':
                from .hardware.act import ActArm
                self.arm = ActArm(self.config['act'], self, self.frames)
            else:
                from .hardware.yolo import YoloArm
                from server.catalog import load_products
                self.arm = YoloArm(self.config['yolo'], self, self.frames, load_products())
        items = ([{'sku': params['sku'], 'slot': params['slot'], 'item_id': job['id'] + '-0'}] if job['kind'] == 'PICK'
                 else [{'sku': sku, 'slot': i, 'item_id': job['id'] + '-' + str(i)} for i, sku in enumerate(params['skus'])])
        command = {**job, 'scope': 'device_test', 'items': items, 'robot_id': params.get('robot_id', 'pinky-1'),
                   'task_id': job['id'], 'session_id': job['id'], 'basket_id': 'test-' + job['id']}
        if job['kind'] == 'HANDOFF':
            side = params['side']
            model = self.config['act']['models'].get(side)
            if not model:
                raise RuntimeError('해당 방향 모델 없음')
            command.update(basket_side=side, model_id=model['id'])
        self.command = command
        result = self.arm.execute(command, cancelled)
        if job['kind'] == 'HANDOFF':
            result['stop_feedback'] = self.arm.stopped(command, cancelled)
        return result


class TestAgent:
    def __init__(self, client, identity, path, hardware=None, allow_mock_motion=True, endpoint='/api/nodes/device-tests'):
        self.client, self.identity, self.path = client, identity, Path(path)
        self.endpoint = endpoint
        self.hardware, self.allow_mock_motion = hardware, allow_mock_motion
        self.reference = None
        if identity.get('mode', 'mock') == 'mock' and identity['node_id'] == 'gateway-a' and hardware is None:
            from robots.pinky.simulator import ReferenceTrials
            self.reference = ReferenceTrials()
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {'job': None, 'pending': []}
        self.recovering = bool(self.state['job'] or self.state['pending'])
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future, self.cancelled = None, threading.Event()
        self.last_contact = time.monotonic()
        self.ending = threading.Event()
        self.guard = threading.Thread(target=self.watchdog, daemon=True)
        self.guard.start()

    def watchdog(self):
        while not self.ending.wait(.1):
            if time.monotonic() - self.last_contact > 3:
                self.cancelled.set()

    def persist(self):
        save_state(self.path, self.state)

    def emit(self, kind, data=None):
        event = {**self.identity, 'job_id': self.state['job']['id'], 'event_id': str(uuid.uuid4()), 'kind': kind, 'data': data or {}}
        self.state['pending'].append(event)
        self.persist()

    def flush(self):
        while self.state['pending']:
            head = self.state['pending'][0]
            try:
                self.client.call(self.endpoint + '/events', head)
            except urllib.error.HTTPError as exc:
                if exc.code == 409 and head['kind'] in {'ACCEPTED', 'STARTED'} and not self.state['job'].get('launched'):
                    self.state['pending'] = [p for p in self.state['pending'] if p['kind'] not in {'ACCEPTED', 'STARTED'}]
                    self.emit('ERROR', {'not_executed': True, 'error': '실행 전 중지 또는 명령 상태 변경으로 실행 거부'})
                    raise StartRejected from exc
                raise
            self.state['pending'].pop(0)
            self.persist()

    def profile(self):
        mode = self.identity.get('mode', 'mock')
        node = self.identity['node_id']
        report = dict(self.hardware.report) if self.hardware else {
            'allow_motion': mode == 'mock' and self.allow_mock_motion,
            'operations': ['HANDOFF'] if node == 'gateway-c' else ['PICK'], 'sides': ['left', 'right'],
            'issues': [], 'checks': [], 'inspection': 'MOCK · 실제 장비·모델 미사용', 'python': platform.python_version()}
        if self.recovering:
            report.update(allow_motion=False, issues=[*report.get('issues', []), '이전 시험 결과 보존: 관제 복구 확인 필요'])
        if self.reference:
            from robots.pinky import compact, catalog
            source = compact if self.endpoint == '/api/nodes/motion' else catalog
            report.update(operations=[*report['operations'], 'NAVIGATE'], motion_backend=source.BACKEND,
                          route_version=source.VERSION, source_hash=source.bundle()[3])
        return {**report, 'revision': revision()}

    def run(self, job):
        try:
            if self.cancelled.is_set():
                raise RuntimeError('실행 전 중지 요청')
            if job['kind'] == 'PING':
                return 'FINISHED', {'reply': 'PONG', 'node_id': self.identity['node_id'], 'python': platform.python_version(), 'revision': revision()}
            if job['kind'] == 'INSPECT':
                return 'FINISHED', self.hardware.inspect() if self.hardware else self.profile()
            if job['kind'] == 'NAVIGATE':
                if not self.reference or job['mode'] != 'mock':
                    raise RuntimeError('도로 모의 이동 실행부가 없습니다')
                result = self.reference.execute(job, self.cancelled)
                return ('FINISHED' if result['outcome'] == 'SUCCEEDED' else 'ERROR'), result
            if job['mode'] == 'hardware':
                if not self.hardware:
                    raise RuntimeError('실물 실행부가 없습니다')
                return 'FINISHED', self.hardware.execute(job, self.cancelled)
            # Delays and all outcomes here are explicitly virtual.
            for _ in range(10):
                if self.cancelled.wait(.1):
                    raise RuntimeError('모의 시험 중단')
            if job.get('simulate_failure'):
                raise RuntimeError('모의 동작 실패 주입 · 실제 장비 미사용')
            if job['kind'] == 'HANDOFF':
                while not self.observation:
                    if self.cancelled.wait(.1):
                        raise RuntimeError('모의 하역 중단')
            return 'FINISHED', {'simulation': True, 'attempted_parameters': job['parameters'],
                                'stop_feedback': dict.fromkeys(['policy_stopped', 'motion_stopped', 'hold_confirmed', 'torque_enabled'], True)}
        except Exception as exc:
            data = {'error': str(exc)[:500], 'error_type': type(exc).__name__, 'actual_stop_confirmed': False}
            if self.hardware and self.hardware.arm and job['kind'] == 'HANDOFF':
                try:
                    data['stop_feedback'] = self.hardware.arm.stopped(self.hardware.command, self.cancelled)
                except Exception:
                    pass
            return 'ERROR', data

    def tick(self):
        value = self.client.call(self.endpoint + '/poll', {**self.identity, 'profile': self.profile(),
                                'available': not self.recovering and self.future is None and self.state['job'] is None and not self.state['pending']})
        self.last_contact = time.monotonic()
        local = self.state['job']
        if local and local.get('run_id') != value['run_id'] and self.identity.get('mode', 'mock') == 'mock':
            self.cancelled.set()
            if self.future is not None and not self.future.done():
                return
            self.state = {'job': None, 'pending': []}
            self.recovering, self.future = False, None
            self.persist()
            return
        if local and local['id'] in value['closed_ids']:
            if self.future is not None and not self.future.done():
                self.cancelled.set()
                return
            self.state = {'job': None, 'pending': []}
            self.recovering, self.future = False, None
            self.persist()
        if not self.recovering:
            try:
                self.flush()
            except StartRejected:
                return
        job = value['job']
        if self.recovering or job is None:
            return
        if self.state['job'] is None and job['status'] == 'SENT':
            self.state['job'] = job
            self.cancelled = threading.Event()
            self.observation = None
            if self.hardware:
                self.hardware.observation = None
            self.persist()  # Never actuate a job not durably recorded first.
            try:
                self.emit('ACCEPTED'); self.flush()
                if job['stop_requested_at']:
                    self.cancelled.set()
                    self.state['job']['stop_reported'] = True
                    self.emit('STOP_ACK')
                    self.emit('ERROR', {'not_executed': True, 'error': '실행 전 중지 요청'})
                    self.flush()
                    return
                self.emit('STARTED'); self.flush()
            except StartRejected:
                return
            except Exception:
                # An ambiguous ACK never authorizes motion or automatic retry.
                self.emit('ERROR', {'not_executed': True, 'error': '명령 수락/시작 응답 미확인: 동작하지 않음'})
                raise
            self.state['job']['launched'] = True
            self.persist()
            self.future = self.pool.submit(self.run, job)
        if self.state['job'] and self.state['job']['id'] == job['id']:
            self.observation = job.get('observation')
            if self.hardware:
                self.hardware.observation = self.observation
            if job['stop_requested_at'] and not self.cancelled.is_set():
                self.cancelled.set()
            if job['stop_requested_at'] and not self.state['job'].get('stop_reported'):
                self.state['job']['stop_reported'] = True
                self.emit('STOP_ACK')
            if self.reference and job['kind'] == 'NAVIGATE':
                sample = self.reference.take()
                if sample and job['status'] == 'RUNNING':
                    self.emit('PROGRESS', {'sample': sample})
            if self.future is not None and self.future.done():
                kind, data = self.future.result()
                self.emit(kind, data)
                self.future = None
            self.flush()

    def close(self):
        self.cancelled.set()
        self.ending.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
