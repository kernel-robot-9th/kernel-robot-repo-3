"""Command adapter for one independent reference-path trial; no motors or ROS."""
import threading
import time
import uuid

from .catalog import BACKEND, FRAME, VERSION, route


class ReferenceMobile:
    def __init__(self, publish, clock=time.monotonic, wall=time.time):
        self.publish, self.clock, self.wall = publish, clock, wall

    def execute(self, command, cancelled):
        if command['mode'] != 'mock' or command['kind'] != 'NAVIGATE' or command.get('backend') != BACKEND:
            raise ValueError('도로 모의 시험 명령만 실행할 수 있습니다')
        from . import compact, catalog
        provider = compact if command.get('route_version') == 4 else catalog
        selected = provider.route(command['parameters']['route_id'])
        if command.get('source_hash') != selected.source_hash:
            raise ValueError('관제와 실행부의 도로 기준이 다릅니다')
        selected.check()
        epoch, sequence, elapsed = str(uuid.uuid4()), 0, 0.
        rate = command['parameters']['rate']
        if rate not in (1, 2, 4):
            raise ValueError('지원하지 않는 재생 배속')
        last = self.clock()
        last_publish = -1.
        def observe(halted=False):
            nonlocal sequence
            sequence += 1
            pose, speed = selected.sample(elapsed)
            value = dict(run_id=command['run_id'], command_id=command['id'], task_id=command.get('task_id', command['id']),
                         session_id=command.get('session_id'), robot_id=command['robot_id'], backend=BACKEND,
                         observation_source=BACKEND, route_version=provider.VERSION, source_hash=selected.source_hash,
                         frame_id=provider.FRAME, sim_epoch=epoch, sequence=sequence, sim_time=elapsed,
                         observed_at=self.wall(), pose=pose, speed=0. if halted else speed,
                         halted=halted, arrived=elapsed >= selected.duration,
                         progress=min(1., elapsed / selected.duration))
            return value
        self.publish(observe())
        while True:
            if cancelled.is_set():
                return {'outcome': 'CANCELLED', 'reason': '중지 요청 또는 관제 연결 만료', 'sample': observe(True)}
            if command.get('simulate_failure') and elapsed >= selected.duration * .3:
                return {'outcome': 'FAILED', 'reason': '모의 이동 실패 주입', 'sample': observe(True)}
            if elapsed >= selected.duration:
                return {'outcome': 'SUCCEEDED', 'sample': observe(True)}
            cancelled.wait(.05)
            now = self.clock()
            # Long scheduling pauses do not teleport the reference to completion.
            elapsed = min(selected.duration, elapsed + min(max(0., now - last), .1) * rate)
            last = now
            if now - last_publish >= .2:
                self.publish(observe())
                last_publish = now


class ReferenceTrials:
    def __init__(self):
        self.lock = threading.Lock()
        self.latest = None

    def offer(self, sample):
        with self.lock:
            self.latest = sample

    def take(self):
        with self.lock:
            value, self.latest = self.latest, None
            return value

    def execute(self, job, cancelled):
        self.take()
        return ReferenceMobile(self.offer).execute(job, cancelled)
