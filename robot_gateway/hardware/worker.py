"""Opt-in field worker. Heartbeats/outbox run separately from blocking robot work."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import uuid

from server.catalog import load_products
from robot_gateway.frames import JpegSender, LatestFramePublisher, RtspSender
from robot_gateway.mock import Client, make_event
from robot_gateway.runtime import save_state
from .config import validate
from .evidence import EvidenceFiles


class Executor:
    def __init__(self, config, evidence, frames):
        self.config, self.evidence = config, evidence
        if config['node_id'] == 'gateway-c':
            from .act import ActArm
            self.arm = ActArm(config['act'], evidence, frames)
        else:
            from .yolo import YoloArm
            self.arm = YoloArm(config['yolo'], evidence, frames, load_products())
        self.mobile = None
        if config.get('mobile_factory'):
            module, name = config['mobile_factory'].split(':', 1)
            self.mobile = getattr(importlib.import_module(module), name)(config, evidence)

    def execute(self, command, cancelled):
        if command['mode'] != 'hardware':
            raise RuntimeError('모의 명령으로 실제 장비를 실행할 수 없습니다')
        kind = command['kind']
        if command['device_id'].startswith('pinky-'):
            if self.mobile is None:
                raise RuntimeError('검증한 Pinky 어댑터가 필요합니다')
            # Project-internal Python contract, NOT an assumed ROS interface.
            data = self.mobile.execute(command, cancelled)
            return make_event(command, 'SUCCEEDED', data)
        if kind == 'STOP':
            return make_event(command, 'SUCCEEDED', self.arm.stop(command, cancelled))
        if kind == 'STOP_POLICY':
            return make_event(command, 'SUCCEEDED', self.arm.stopped(command, cancelled))
        data = self.arm.execute(command, cancelled)
        return make_event(command, 'TRANSFER_READY' if kind == 'HANDOFF' else 'SUCCEEDED', data)

    def observe(self, command, kind):
        data = self.evidence.read(command, kind.lower())
        return make_event(command, kind, data) if data else None


def main():
    parser = argparse.ArgumentParser(description='현장 실물 중계. --execute와 검증한 로컬 설정이 모두 필요합니다.')
    parser.add_argument('--config', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--server', default=os.getenv('SHOP_SERVER_URL', 'http://127.0.0.1:8000'))
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    issues = validate(config)
    if not args.execute or issues:
        print(json.dumps({'hardware_executed': False, 'issues': issues or ['--execute 미지정']}, ensure_ascii=False))
        return 2
    token = os.getenv('SHOP_NODE_TOKEN', '')
    if len(token) < 16:
        parser.error('해당 중계 SHOP_NODE_TOKEN 필요')
    if os.name != 'posix':
        parser.error('실물 실행은 현장 Ubuntu에서만 지원')
    import fcntl
    path = Path('runtime/hardware') / config['node_id'] / 'outbox.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    lockfile = open(path.with_suffix('.lock'), 'a+')
    fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    previous = json.loads(path.read_text()) if path.exists() else {}
    if previous.get('inflight') or previous.get('pending'):
        raise RuntimeError('이전 실물 작업·미전달 결과가 남아 있습니다. 자동 재실행하지 않습니다')
    instance = str(uuid.uuid4())
    identity = {'node_id': config['node_id'], 'instance_id': instance, 'mode': 'hardware'}
    client = Client(args.server, token)
    hello = client.call('/api/nodes/heartbeat', identity)
    if hello['mode'] != 'hardware':
        raise RuntimeError('중앙 서버가 실물 모드가 아닙니다')
    sender = (RtspSender(config['video']['rtsp_urls'], config['video'].get('fps', 15))
              if config['video']['transport'] == 'rtsp' else JpegSender(args.server, token, instance))
    frames = LatestFramePublisher(sender, config['video'].get('fps', 5))
    executor = Executor(config, EvidenceFiles(config['evidence_directory']), frames)
    from robot_gateway.test_agent import TestAgent, HardwareTrials
    trial = TestAgent(client, identity, path.with_name('device-tests.json'), HardwareTrials(config, frames, execute=False))
    state = {'run_id': hello['run_id'], 'inflight': {}, 'pending': []}
    jobs, sent_observations = {}, {}
    pool = ThreadPoolExecutor(max_workers=4)
    last_contact = time.monotonic()
    ending = threading.Event()

    def lease_watchdog():
        while not ending.wait(.1):
            if time.monotonic() - last_contact > 3:
                for _, cancelled, _ in list(jobs.values()):
                    cancelled.set()

    lease = threading.Thread(target=lease_watchdog, daemon=True)
    lease.start()

    def persist():
        save_state(path, state)

    try:
        while True:
            try:
                hello = client.call('/api/nodes/heartbeat', identity)
                if hello['run_id'] != state['run_id']:
                    raise RuntimeError('실물 실행 ID 변경: 현장 상태 확인 필요')
                last_contact = time.monotonic()
                trial.tick()
                while state['pending']:
                    client.call('/api/nodes/events', {**identity, 'event': state['pending'][0]})
                    state['pending'].pop(0); persist()
                for cid, (future, cancelled, command) in list(jobs.items()):
                    if future.done():
                        try:
                            event = future.result()
                        except Exception as exc:
                            event = make_event(command, 'FAILED', {'confirmed_items': getattr(executor.arm, 'confirmed', []).copy()
                                if command['kind'] == 'PICK' else [], 'basket_id': command.get('basket_id'), 'reason': str(exc)[:200]})
                        state['pending'].append(event)
                        state['inflight'].pop(cid, None); jobs.pop(cid); persist()
                if state['pending']:
                    continue
                work = client.call('/api/nodes/work', identity)
                for command in work['commands'].values():
                    task = work['tasks'][command['task_id']]
                    observation = ('STOPPED' if command['kind'] == 'NAVIGATE' and task['state'] in {'WAIT_STOP', 'WAIT_BASKET'}
                                   else 'ARM_CLEAR' if command['kind'] in {'PICK', 'HANDOFF'} and task['state'] == 'WAIT_ARM_CLEAR'
                                   else 'EXITED' if command['kind'] == 'LEAVE' and task['state'] == 'WAIT_EXIT' else None)
                    key = (command['id'], observation)
                    refresh_parking = observation == 'STOPPED' and time.monotonic() - sent_observations.get(key, 0) >= 1
                    if observation and command['status'] == 'SUCCEEDED' and (key not in sent_observations or refresh_parking):
                        event = executor.observe(command, observation)
                        if event:
                            state['pending'].append(event); sent_observations[key] = time.monotonic(); persist()
                if state['pending']:
                    continue
                command = client.call('/api/nodes/commands/claim', identity)['command']
                if command:
                    if command['kind'] in {'STOP', 'STOP_POLICY'}:
                        for _, cancelled, running in jobs.values():
                            if running['device_id'] == command['device_id']:
                                cancelled.set()
                    state['inflight'][command['id']] = command
                    state['pending'].append(make_event(command, 'ACCEPTED')); persist()
                    try:
                        client.call('/api/nodes/events', {**identity, 'event': state['pending'][0]})
                    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                        # The server may have accepted it. Preserve outbox and stop,
                        # instead of executing an operation after an ambiguous ACK.
                        raise RuntimeError('명령 수락 응답 미확인: 실행하지 않고 outbox를 보존합니다') from exc
                    state['pending'].pop(0); persist()
                    cancelled = threading.Event()
                    jobs[command['id']] = (pool.submit(executor.execute, command, cancelled), cancelled, command)
            except urllib.error.HTTPError:
                # Rejected correlation/authentication is not a reason to replay a device operation.
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                # A stale central connection stops new outputs; no automatic resume of work.
                if time.monotonic() - last_contact > 3:
                    for _, cancelled, _ in jobs.values():
                        cancelled.set()
            time.sleep(.1)
    finally:
        ending.set()
        for _, cancelled, _ in jobs.values():
            cancelled.set()
        trial.close()
        if hasattr(sender, 'close'):
            sender.close()
        frames.close()
        pool.shutdown(wait=True, cancel_futures=True)
        lockfile.close()


if __name__ == '__main__':
    raise SystemExit(main())
