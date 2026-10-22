"""Commissioning contracts and real feedback fakes; no physical actuation."""
from copy import deepcopy
import json
import time
import uuid
import urllib.error

import pytest
from fastapi.testclient import TestClient

from conftest import Clock
from server.api import create_app
from server.device_tests import Bench
from server.distributed import DistributedEngine
from server.domain import DomainError
from robot_gateway.test_agent import TestAgent as Agent, HardwareTrials
from robot_gateway.hardware.config import validate
from test_distributed import TOKENS, ADMIN
from test_api import bearer

NODE = 'gateway-a'
INSTANCE = 'test-instance-0001'
PROFILE = {'allow_motion': True, 'operations': ['PICK'], 'sides': [], 'issues': [], 'checks': []}
PARAMS = {'sku': 'SKU-JIN-RAMEN', 'slot': 0, 'robot_id': 'pinky-1'}
STOP = dict.fromkeys(['policy_stopped', 'motion_stopped', 'hold_confirmed', 'torque_enabled'], True)


@pytest.fixture
def bench():
    clock = Clock()
    e = DistributedEngine(clock=clock)
    e.node_heartbeat(NODE, INSTANCE)
    b = Bench(e)
    b.poll(NODE, INSTANCE, PROFILE, False)
    yield b, e, clock
    e.store.close()


def create(b, kind='PICK', params=None, node=NODE):
    return b.create(node, kind, PARAMS if params is None and kind == 'PICK' else params or {}, str(uuid.uuid4()), kind in {'PICK', 'HANDOFF'})


def event(b, job, kind, data=None, key=None):
    return b.event(job['node_id'], INSTANCE, job['id'], key or str(uuid.uuid4()), kind, data or {})


def start(b, job, profile=PROFILE):
    b.poll(job['node_id'], INSTANCE, profile, True)
    event(b, job, 'ACCEPTED')
    event(b, job, 'STARTED')


def test_motion_isolated_from_customer_inventory_and_release_required(bench):
    b, e, _ = bench
    before = deepcopy(e.state['stock'])
    job = create(b)
    customer = e.create_session('customer')['session_id']
    with pytest.raises(DomainError):
        e.submit_order(customer, [{'sku': 'SKU-SHIN-RAMEN', 'quantity': 1}], 'customer-order-01')
    start(b, job)
    event(b, job, 'FINISHED', {'attempted_items': [PARAMS]})
    assert b.job(job['id'])['status'] == 'WAIT_REVIEW'
    assert e.state['stock'] == before and not e.state['commands']
    with pytest.raises(DomainError):
        b.release(job['id'], 'tester', True)
    b.review(job['id'], 'tester', True, True, '실제 슬롯 확인')
    assert b.state['hold'] == job['id']
    b.release(job['id'], 'tester', True)
    e.submit_order(customer, [{'sku': 'SKU-SHIN-RAMEN', 'quantity': 1}], 'customer-order-01')
    assert e.state['stock']['SKU-JIN-RAMEN'] == before['SKU-JIN-RAMEN']


def test_existing_order_blocks_test_even_before_movement(bench):
    b, e, _ = bench
    sid = e.create_session('A')['session_id']
    e.submit_order(sid, [{'sku': 'SKU-JIN-RAMEN', 'quantity': 1}], 'existing-order-001')
    with pytest.raises(DomainError, match='주문 작업'):
        create(b)
    assert b.state['hold'] is None


def test_request_and_event_idempotence_cannot_change_payload(bench):
    b, _, _ = bench
    job = create(b)
    assert b.create(NODE, 'PICK', PARAMS, job['request_id'], True)['id'] == job['id']
    with pytest.raises(DomainError):
        b.create(NODE, 'PICK', {**PARAMS, 'slot': 1}, job['request_id'], True)
    start(b, job)
    event(b, job, 'FINISHED', {'motion_only': True}, key='repeat-event-001')
    count = len(b.job(job['id'])['timeline'])
    event(b, job, 'FINISHED', {'motion_only': True}, key='repeat-event-001')
    assert len(b.job(job['id'])['timeline']) == count
    with pytest.raises(DomainError):
        event(b, job, 'FINISHED', {'motion_only': False}, key='repeat-event-001')


def test_stop_ack_and_execution_end_do_not_confirm_physical_stop(bench):
    b, _, _ = bench
    job = create(b); start(b, job)
    b.stop(job['id']); event(b, job, 'STOP_ACK')
    assert b.job(job['id'])['stopped'] is None
    event(b, job, 'ERROR', {'error': 'cancelled'})
    assert b.job(job['id'])['stopped'] is None
    with pytest.raises(DomainError):
        b.review(job['id'], 'tester', True, True, 'cannot claim success')
    b.review(job['id'], 'tester', False, True, '실제 정지 확인')
    assert b.job(job['id'])['status'] == 'CANCELLED'


def test_wrong_node_and_premature_result_rejected(bench):
    b, e, _ = bench
    e.node_heartbeat('gateway-b', INSTANCE)
    job = create(b)
    b.poll(NODE, INSTANCE, PROFILE, True)
    with pytest.raises(DomainError):
        b.event('gateway-b', INSTANCE, job['id'], 'wrong-node-event', 'ACCEPTED', {})
    with pytest.raises(DomainError):
        event(b, job, 'FINISHED')
    assert b.job(job['id'])['status'] == 'SENT'


@pytest.mark.parametrize('params', [{**PARAMS, 'slot': True}, {**PARAMS, 'slot': 3}, {**PARAMS, 'sku': 'SKU-RICE-CHIP'}, {**PARAMS, 'robot_id': 'other'}])
def test_invalid_pick_selection_never_dispatches(bench, params):
    b, _, _ = bench
    with pytest.raises(DomainError):
        create(b, params=params)
    assert not b.state['jobs']


def test_missing_right_and_empty_cart_only_cannot_finish_handoff(bench):
    b, e, _ = bench
    node = 'gateway-c'; profile = {**PROFILE, 'operations': ['HANDOFF'], 'sides': ['left']}
    e.node_heartbeat(node, INSTANCE); b.poll(node, INSTANCE, profile, False)
    with pytest.raises(DomainError):
        create(b, 'HANDOFF', {'side': 'right', 'skus': ['SKU-JIN-RAMEN']}, node)
    job = create(b, 'HANDOFF', {'side': 'left', 'skus': ['SKU-JIN-RAMEN']}, node)
    start(b, job, profile)
    with pytest.raises(DomainError):
        b.observe(job['id'], 'tester', {'cart_empty': True})
    b.observe(job['id'], 'tester', dict.fromkeys(['cart_visible', 'cart_empty', 'last_item_placed', 'standby_reached'], True))
    event(b, job, 'FINISHED', {'stop_feedback': {**STOP, 'torque_enabled': False}})
    with pytest.raises(DomainError):
        b.review(job['id'], 'tester', True, True, '정지 피드백 없음')


def test_disconnect_keeps_hold_and_requires_offline_reconciliation(bench):
    b, e, clock = bench
    job = create(b); start(b, job)
    clock.now += 11; b.watchdog()
    assert b.job(job['id'])['status'] == 'UNCERTAIN' and b.state['hold'] == job['id']
    with pytest.raises(DomainError):
        b.review(job['id'], 'tester', True, True, 'cannot turn timeout into success', True)
    b.review(job['id'], 'tester', False, True, '원래 실행부 종료 및 장비 정지 확인', True)
    b.release(job['id'], 'tester', True)


def test_test_only_hardware_needs_no_pinky_but_never_runs_orders(tmp_path):
    e = DistributedEngine(str(tmp_path / 'tests.db'), mode='hardware', test_only=True)
    try:
        e.node_heartbeat(NODE, INSTANCE, 'test')
        assert not e.state['devices']['omx-a']['connected']
        sid = e.create_session('A')['session_id']
        with pytest.raises(DomainError):
            e.submit_order(sid, [{'sku': 'SKU-JIN-RAMEN', 'quantity': 1}], 'test-only-order')
        with pytest.raises(DomainError):
            e.node_claim(NODE, INSTANCE)
        job = Bench(e).create(NODE, 'PING', {}, 'diagnostic-req')
        assert job['mode'] == 'hardware'
    finally:
        e.store.close()


def test_restart_preserves_test_hold_without_replay(tmp_path):
    path = str(tmp_path / 'state.db')
    e = DistributedEngine(path); b = Bench(e)
    e.node_heartbeat(NODE, INSTANCE); b.poll(NODE, INSTANCE, PROFILE, False)
    job = create(b); start(b, job); e.store.close()
    e = DistributedEngine(path)
    try:
        assert Bench(e).job(job['id'])['status'] == 'UNCERTAIN'
        assert Bench(e).state['hold'] == job['id']
        sid = e.create_session('new')['session_id']
        assert 'device_tests' not in e.snapshot(sid)
    finally:
        e.store.close()


def test_http_authorization_and_mode_correlation(bench):
    b, e, _ = bench
    with TestClient(create_app(e, ADMIN, node_tokens=TOKENS)) as client:
        body = {'node_id': NODE, 'kind': 'PING', 'request_id': 'http-ping-request'}
        assert client.post('/api/admin/device-tests', json=body).status_code == 401
        job = client.post('/api/admin/device-tests', headers=bearer(ADMIN), json=body).json()
        identity = {'node_id': NODE, 'instance_id': INSTANCE, 'profile': PROFILE, 'available': True}
        assert client.post('/api/nodes/device-tests/poll', headers=bearer(TOKENS['gateway-b']), json=identity).status_code == 403
        assert client.post('/api/nodes/device-tests/poll', headers=bearer(TOKENS[NODE]), json={**identity, 'mode': 'hardware'}).status_code == 409
        poll = client.post('/api/nodes/device-tests/poll', headers=bearer(TOKENS[NODE]), json=identity).json()
        assert poll['job']['id'] == job['id']
        assert client.get('/api/admin/device-tests', headers=bearer(TOKENS[NODE])).status_code == 401


class LocalClient:
    def __init__(self, bench):
        self.b = bench
        self.lose_start = False

    def call(self, path, body):
        if path.endswith('/poll'):
            return self.b.poll(body['node_id'], body['instance_id'], body['profile'], body['available'])
        result = self.b.event(body['node_id'], body['instance_id'], body['job_id'], body['event_id'], body['kind'], body['data'])
        if self.lose_start and body['kind'] == 'STARTED':
            self.lose_start = False
            raise TimeoutError('lost ACK')
        return result


def test_agent_round_trip_and_durable_outbox(bench, tmp_path):
    b, _, _ = bench
    agent = Agent(LocalClient(b), {'node_id': NODE, 'instance_id': INSTANCE, 'mode': 'mock'}, tmp_path / 'outbox.json')
    try:
        job = create(b, 'PING'); agent.tick()
        if agent.future is not None:
            agent.future.result(timeout=2)
        agent.tick(); agent.tick()
        assert b.job(job['id'])['status'] == 'SUCCEEDED'
        assert b.job(job['id'])['result']['data']['reply'] == 'PONG'
        assert json.loads((tmp_path / 'outbox.json').read_text())['job'] is None
    finally:
        agent.close()


def test_ambiguous_start_ack_never_actuates_or_replays(bench, tmp_path, monkeypatch):
    b, _, _ = bench
    client = LocalClient(b); client.lose_start = True
    agent = Agent(client, {'node_id': NODE, 'instance_id': INSTANCE}, tmp_path / 'outbox.json')
    calls = []
    monkeypatch.setattr(agent, 'run', lambda job: calls.append(job))
    try:
        job = create(b)
        with pytest.raises(TimeoutError):
            agent.tick()
        agent.tick()
        assert not calls
        assert b.job(job['id'])['status'] == 'WAIT_REVIEW'
        assert b.job(job['id'])['result']['kind'] == 'ERROR'
    finally:
        agent.close()


def test_diagnostics_only_do_not_import_device_libraries():
    driver = HardwareTrials({'node_id': NODE}, None, execute=False)
    assert driver.arm is None and not driver.report['allow_motion']
    assert driver.report['camera_frames'] == '미확인'
    with pytest.raises(RuntimeError):
        driver.execute({'mode': 'hardware'}, None)


def test_omx_validation_can_be_separated_from_mobile_validation():
    config = json.loads(open('config/hardware-yolo.example.json', encoding='utf-8').read())
    full = validate(config, check_files=False)
    arm = validate(config, check_files=False, require_mobile=False)
    assert any('Pinky' in issue for issue in full) and not any('Pinky' in issue for issue in arm)
    assert any('armed' in issue for issue in arm)  # No other execution guard was bypassed.


def test_stop_between_dispatch_and_accept_never_runs(bench, tmp_path, monkeypatch):
    b, _, _ = bench
    agent = Agent(LocalClient(b), {'node_id': NODE, 'instance_id': INSTANCE}, tmp_path / 'outbox.json')
    calls = []
    monkeypatch.setattr(agent, 'run', lambda job: calls.append(job))
    try:
        job = create(b)
        b.poll(NODE, INSTANCE, PROFILE, True)
        b.stop(job['id'])
        agent.tick()
        assert not calls and agent.future is None
        assert b.job(job['id'])['status'] == 'WAIT_REVIEW'
        assert b.job(job['id'])['stop_ack_at'] is not None
        assert b.job(job['id'])['started_at'] is None
    finally:
        agent.close()


def test_hardware_cannot_use_missing_slot_or_simulated_failure():
    e = DistributedEngine(mode='hardware', test_only=True)
    try:
        e.node_heartbeat(NODE, INSTANCE, 'test')
        b = Bench(e)
        b.poll(NODE, INSTANCE, {**PROFILE, 'slots': {'pinky-1': [0]}}, False)
        with pytest.raises(DomainError):
            b.create(NODE, 'PICK', PARAMS, 'hardware-fault-request', True, True)
        with pytest.raises(DomainError):
            create(b, params={**PARAMS, 'slot': 1})
        assert create(b)['mode'] == 'hardware'
    finally:
        e.store.close()


def test_single_slot_trial_does_not_weaken_production_validation():
    config = json.loads(open('config/hardware-yolo.example.json', encoding='utf-8').read())
    config['yolo']['drop_slots'] = {'pinky-1': {'0': {'approach': 'slot0-high', 'release': 'slot0-low'}}}
    assert any('3곳' in i for i in validate(config, check_files=False))
    assert not any('3곳' in i for i in validate(config, check_files=False, require_mobile=False, check_slots=False))


def test_stop_racing_with_start_ack_is_a_clean_non_execution(bench, tmp_path, monkeypatch):
    b, _, _ = bench
    client = LocalClient(b)
    call = client.call

    def race(path, body):
        if body.get('kind') == 'STARTED':
            b.stop(body['job_id'])
            raise urllib.error.HTTPError('http://test', 409, 'start rejected', {}, None)
        return call(path, body)

    client.call = race
    agent = Agent(client, {'node_id': NODE, 'instance_id': INSTANCE}, tmp_path / 'outbox.json')
    calls = []
    monkeypatch.setattr(agent, 'run', lambda job: calls.append(job))
    try:
        job = create(b)
        agent.tick(); agent.tick()
        assert not calls and agent.future is None
        assert b.job(job['id'])['status'] == 'WAIT_REVIEW'
        assert b.job(job['id'])['started_at'] is None
    finally:
        agent.close()
