from copy import deepcopy
from pathlib import Path
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from conftest import Clock
from server.api import create_app
from server.domain import DomainError, Engine
from server.distributed import DistributedEngine
from server.video import VideoRegistry, VIDEO_PATH
from robot_gateway.frames import LatestFramePublisher
from robot_gateway.hardware.config import validate
from robot_gateway.hardware.evidence import EvidenceFiles
from robot_gateway.hardware.worker import Executor
from test_api import ADMIN, GATEWAY, bearer

ROOT = Path(__file__).resolve().parents[1]


def test_video_requires_admin_and_freeze_does_not_refresh_timestamp(rig):
    e, _, clock = rig
    video = VideoRegistry(clock=clock)
    before = deepcopy(e.state)
    with TestClient(create_app(e, ADMIN, GATEWAY, video=video)) as client:
        assert client.get('/api/admin/video').status_code == 401
        feeds = client.get('/api/admin/video', headers=bearer(ADMIN)).json()['items']
        assert len(feeds) == 5
        assert next(f for f in feeds if f['id'] == 'overview')['owner'] == 'central'
        url = '/api/admin/video/overview/frame'
        assert client.get(url, headers=bearer(ADMIN)).status_code == 200
        client.post('/api/admin/video/overview/mock-fault', headers=bearer(ADMIN), json={'kind': 'freeze'})
        clock.now += 4
        assert float(client.get(url, headers=bearer(ADMIN)).headers['x-frame-age']) == 4
        client.post('/api/admin/video/overview/mock-fault', headers=bearer(ADMIN), json={'kind': 'offline'})
        assert client.get(url, headers=bearer(ADMIN)).status_code == 503
    assert e.state == before


def test_video_publication_is_scoped_bounded_and_monotonic(tmp_path):
    config = json.loads(VIDEO_PATH.read_text(encoding='utf-8'))
    config['load-a']['transport'] = 'jpeg'
    file = tmp_path / 'video.json'; file.write_text(json.dumps(config), encoding='utf-8')
    video = VideoRegistry(file)
    jpeg = b'\xff\xd8test\xff\xd9'
    with pytest.raises(DomainError):
        video.publish('load-a', 'gateway-b', 'instance', 1, jpeg)
    video.publish('load-a', 'gateway-a', 'instance', 1, jpeg)
    with pytest.raises(DomainError):
        video.publish('load-a', 'gateway-a', 'instance', 1, jpeg)
    with pytest.raises(DomainError):
        video.publish('load-a', 'gateway-a', 'instance', 2, b'x' * (video.max_bytes + 1))
    assert video.frame('load-a')[0] == jpeg


def test_slow_video_sender_drops_waiting_frames_without_blocking_control():
    entered, release = threading.Event(), threading.Event()
    def slow(*_):
        entered.set(); release.wait(2)
    publisher = LatestFramePublisher(slow, fps=30)
    try:
        publisher.offer('front', [0])
        assert entered.wait(1)
        began = time.monotonic()
        for i in range(100):
            publisher.offer('front', [i])
        assert time.monotonic() - began < .5
        assert len(publisher.pending) == 1 and publisher.dropped >= 99
    finally:
        release.set(); publisher.close()


def test_default_hardware_configs_cannot_arm_devices():
    for name in ['hardware.example.json', 'hardware-yolo.example.json']:
        config = json.loads((ROOT / 'config' / name).read_text())
        issues = validate(config, check_files=False)
        assert any('armed' in item for item in issues)
        assert any('serial_by_id' in item for item in issues)
    with pytest.raises(DomainError):
        Engine(mode='hardware')


def test_hardware_rejects_mock_events_but_accepts_configured_demo_orders():
    engine = DistributedEngine(mode='hardware', readiness={'approved': True, 'supported_skus': ['SKU-RICE-CHIP'], 'handoff_sides': ['left']})
    tokens = {n: 'test-scoped-token-' + n for n in engine.profiles}
    try:
        with TestClient(create_app(engine, ADMIN, node_tokens=tokens)) as client:
            auth = bearer(tokens['gateway-a'])
            body = {'node_id': 'gateway-a', 'instance_id': 'instance-0001'}
            assert client.post('/api/nodes/heartbeat', headers=auth, json=body).status_code == 409
            assert client.post('/api/nodes/heartbeat', headers=auth, json={**body, 'mode': 'hardware'}).status_code == 200
            assert client.post('/api/admin/mock/new-run', headers=bearer(ADMIN), json={}).status_code == 409
        engine.create_session('left')
        right = engine.create_session('right')['session_id']
        engine.submit_order(right, [{'sku': 'SKU-RICE-CHIP', 'quantity': 1}], 'right-demo-order')
        assert engine.state['stock']['SKU-RICE-CHIP']['reserved'] == 1
    finally:
        engine.store.close()


def test_evidence_keeps_correlated_observation_without_expiry(tmp_path):
    clock = Clock()
    evidence = EvidenceFiles(tmp_path)
    command = {'id': 'abcdef-0123', 'run_id': 'run', 'task_id': 'task', 'session_id': 'session',
               'device_id': 'omx', 'created_at': clock() - 1}
    path = tmp_path / 'abcdef-0123.handoff.json'
    observation = {**command, 'observed_at': clock(), 'source': 'vision', 'data': {'cart_empty': True}}
    path.write_text(json.dumps(observation))
    assert evidence.read(command, 'handoff') == {'cart_empty': True}
    clock.now += 3
    assert evidence.read(command, 'handoff') == {'cart_empty': True}
    observation.update(observed_at=clock(), task_id='other')
    path.write_text(json.dumps(observation))
    assert evidence.read(command, 'handoff') is None


def test_hardware_executor_never_runs_mock_command():
    executor = object.__new__(Executor)
    with pytest.raises(RuntimeError, match='모의 명령'):
        executor.execute({'mode': 'mock'}, threading.Event())


def test_media_credentials_are_scoped_and_existing_config_is_preserved(tmp_path):
    from scripts.prepare_media import prepare
    directory = tmp_path / 'media'
    assert prepare(directory, '192.168.10.20') == 5
    config = json.loads((directory / 'mediamtx.yml').read_text())
    users = {u['user']: u for u in config['authInternalUsers']}
    assert len({u['pass'] for u in users.values()}) == 5
    assert all(p['action'] == 'read' for p in users['viewer']['permissions'])
    assert {p['path'] for p in users['gateway-c']['permissions']} == {'handoff-front', 'handoff-wrist'}
    assert users['central']['permissions'] == [{'action': 'publish', 'path': 'overview'}]
    before = (directory / 'mediamtx.yml').read_bytes()
    with pytest.raises(FileExistsError):
        prepare(directory, '192.168.10.20')
    assert (directory / 'mediamtx.yml').read_bytes() == before


def test_act_stop_requests_hold_without_claiming_physical_confirmation():
    from robot_gateway.hardware.act import ActArm
    from types import SimpleNamespace
    actions = []
    arm = ActArm({}, None, None)
    arm.policy = object()
    arm.robot = SimpleNamespace(bus=SimpleNamespace(sync_read=lambda _: {'joint': 10}),
                                send_action=actions.append)
    assert arm.stopped({}, threading.Event()) == {'policy_stopped': True, 'hold_requested': True}
    assert arm.policy is None
    assert actions == [{'joint.pos': 10}]


def test_act_missing_direction_does_not_connect_or_substitute_model():
    from robot_gateway.hardware.act import ActArm
    from unittest.mock import Mock
    arm = ActArm({'models': {'left': {'path': 'unused'}, 'right': None}}, None, None)
    arm.connect = Mock()
    with pytest.raises(RuntimeError, match='선택한 방향의 모델'):
        arm.execute({'basket_side': 'right'}, threading.Event())
    arm.connect.assert_not_called()


def test_mock_checkpoint_cannot_be_opened_as_hardware(tmp_path):
    path = tmp_path / 'shopping.db'
    engine = Engine(path)
    run_id = engine.state['run_id']
    engine.store.close()
    with pytest.raises(DomainError, match='DB를 분리'):
        Engine(path, mode='hardware', readiness={'approved': True})
    restored = Engine(path)
    try:
        assert restored.state['run_id'] == run_id and restored.state['mode'] == 'mock'
    finally:
        restored.store.close()


def test_hardware_observation_presence_does_not_expire_in_demo():
    clock = Clock()
    engine = Engine(clock=clock, mode='hardware', readiness={'approved': True})
    try:
        assert engine._observed(clock())
        assert engine._observed(clock() - 3)
        assert not engine._observed(None)
    finally:
        engine.store.close()
