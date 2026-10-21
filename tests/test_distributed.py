"""Distributed command isolation and interlocks; no physical hardware tests."""
import uuid

import pytest
from fastapi.testclient import TestClient

from server.api import create_app
from server.distributed import DistributedEngine
from server.domain import DomainError, Engine
from server.store import Store
from robot_gateway.mock import make_event, next_action
from conftest import Clock


NODES = {n: str(uuid.uuid4()) for n in ['gateway-a', 'gateway-b', 'gateway-c']}
TOKENS = {n: 'test-only-secret-token-for-' + n for n in NODES}
ADMIN = 'test-only-admin-token-1234'


@pytest.fixture
def dist():
    clock = Clock()
    engine = DistributedEngine(clock=clock)
    for node, instance in NODES.items():
        engine.node_heartbeat(node, instance)
    yield engine, clock
    engine.store.close()


def step(engine, node):
    instance = NODES[node]
    engine.node_heartbeat(node, instance)
    choice = next_action(engine.node_work(node, instance))
    if not choice:
        return False
    action, cmd = choice
    if action == 'CLAIM':
        engine.node_claim(node, instance)
    else:
        event = make_event(cmd, 'ACCEPTED') if action == 'ACCEPTED' else engine.mock_action(node, instance, cmd['id'], action)
        engine.node_event(node, instance, event)
    return True


def test_three_nodes_two_customers_and_shared_world(dist):
    e, _ = dist
    customers = [e.create_session(name)['session_id'] for name in ['A', 'B']]
    assert len({e.state['sessions'][sid]['robot_id'] for sid in customers}) == 2
    for index, sid in enumerate(customers):
        e.submit_order(sid, [{'sku': ['SKU-JIN-RAMEN', 'SKU-SHIN-RAMEN'][index], 'quantity': 1}, {'sku': 'SKU-RICE-CHIP', 'quantity': 1}], 'request-' + sid)
        e.checkout(sid)
    saw_wait = any(z['queue'] for z in e.state['zones'].values())
    for _ in range(200):
        for node in NODES:
            step(e, node)
        for s in e.state['sessions'].values():
            if s['current_task']:
                t = e.state['tasks'][s['current_task']]
                if t['state'] == 'WAIT_BASKET':
                    e.basket_ready(s['id'], t['id'], s['basket_id'])
        if all(s['state'] == 'COMPLETED' and s['current_task'] is None for s in e.state['sessions'].values()):
            break
    else:
        pytest.fail('distributed scenario did not complete')
    assert saw_wait
    assert all(z['owner'] is None for z in e.state['zones'].values())
    assert all(len(s['inventory']) == 2 and all(i['delivered'] for i in s['inventory']) for s in e.state['sessions'].values())
    for cmd in e.state['commands'].values():
        if cmd['status'] == 'SUCCEEDED':
            assert cmd['device_id'] in e.profiles[cmd['gateway_id']]['devices']


def test_auth_identity_and_cross_node_event_rejected(dist):
    e, _ = dist
    sid = e.create_session('A')['session_id']
    e.submit_order(sid, [{'sku': 'SKU-JIN-RAMEN', 'quantity': 1}], 'request-0001')
    cmd = e.node_claim('gateway-a', NODES['gateway-a'])
    assert e.node_claim('gateway-b', NODES['gateway-b']) is None
    with pytest.raises(DomainError):
        e.node_event('gateway-b', NODES['gateway-b'], make_event(cmd, 'ACCEPTED'))
    with TestClient(create_app(e, ADMIN, node_tokens=TOKENS)) as client:
        wrong = client.post('/api/nodes/heartbeat', headers={'Authorization': 'Bearer ' + TOKENS['gateway-a']},
                            json={'node_id': 'gateway-b', 'instance_id': NODES['gateway-b']})
        assert wrong.status_code == 403
        assert client.post('/api/gateway/heartbeat', headers={'Authorization': 'Bearer ' + TOKENS['gateway-a']},
                           json={'gateway_id': 'legacy-gateway'}).status_code == 409


def test_expired_b_does_not_disconnect_a_or_c(dist):
    e, clock = dist
    sid = e.create_session('A')['session_id']
    e.submit_order(sid, [{'sku': 'SKU-JIN-RAMEN', 'quantity': 1}], 'request-0001')
    for seconds in [5, 5, 1]:
        clock.now += seconds
        for n in ['gateway-a', 'gateway-c']:
            e.node_heartbeat(n, NODES[n])
    e.watchdog()
    assert not e.state['devices']['omx-b']['connected']
    assert e.state['devices']['omx-a']['connected']
    assert e.state['devices']['omx-handoff']['connected']
    assert e.state['sessions'][sid]['error'] is None


def test_active_b_fault_retains_zone_and_restart_cannot_replay(dist):
    e, clock = dist
    sid = e.create_session('A')['session_id']
    e.submit_order(sid, [{'sku': 'SKU-RICE-CHIP', 'quantity': 1}], 'request-0001')
    for _ in range(20):
        for n in NODES:
            step(e, n)
        if any(c['kind'] == 'PICK' and c['status'] == 'ACCEPTED' for c in e.state['commands'].values()):
            break
    pick = next(c for c in e.state['commands'].values() if c['kind'] == 'PICK')
    for seconds in [5, 5, 1]:
        clock.now += seconds
        for n in ['gateway-a', 'gateway-c']:
            e.node_heartbeat(n, NODES[n])
    e.watchdog()
    e.node_heartbeat('gateway-b', 'replacement-instance')
    assert e.state['sessions'][sid]['error']
    assert e.state['zones']['load-b']['owner'] == pick['task_id']
    assert not e.state['sessions'][sid]['inventory']
    with pytest.raises(DomainError):
        e.node_event('gateway-b', NODES['gateway-b'], make_event(pick, 'SUCCEEDED', {'confirmed_items': pick['items']}))
    clock.now += e.heartbeat_timeout + 1
    with pytest.raises(DomainError):
        e.node_heartbeat('gateway-b', NODES['gateway-b'])


def test_duplicate_instance_cannot_displace_live_node(dist):
    e, _ = dist
    with pytest.raises(DomainError):
        e.node_heartbeat('gateway-a', 'accidental-second-instance')
    assert e.state['gateways']['gateway-a']['instance_id'] == NODES['gateway-a']


def test_mock_action_and_report_retries_do_not_repeat_cargo(dist):
    e, _ = dist
    sid = e.create_session('A')['session_id']
    e.submit_order(sid, [{'sku': 'SKU-JIN-RAMEN', 'quantity': 1}], 'request-0001')
    for _ in range(20):
        step(e, 'gateway-a')
        pick = next((c for c in e.state['commands'].values() if c['kind'] == 'PICK' and c['status'] == 'ACCEPTED'), None)
        if pick:
            break
    first = e.mock_action('gateway-a', NODES['gateway-a'], pick['id'], 'EXECUTE')
    retry = e.mock_action('gateway-a', NODES['gateway-a'], pick['id'], 'EXECUTE')
    assert first == retry
    e.node_event('gateway-a', NODES['gateway-a'], first)
    assert e.node_event('gateway-a', NODES['gateway-a'], retry)['duplicate']
    assert len(e.state['sessions'][sid]['inventory']) == 1


def test_mock_pick_failure_stops_and_does_not_add_inventory(dist):
    e, _ = dist
    sid = e.create_session('A')['session_id']
    e.submit_order(sid, [{'sku': 'SKU-JIN-RAMEN', 'quantity': 1}], 'request-0001')
    e.inject_failure('omx-a', 'PICK_FAIL')
    for _ in range(30):
        step(e, 'gateway-a')
        if e.state['sessions'][sid]['error']:
            break
    assert e.state['sessions'][sid]['error']
    assert not e.state['sessions'][sid]['inventory']
    assert e.state['zones']['load-a']['owner']


def test_node_snapshot_does_not_expose_other_customer_or_world(dist):
    e, _ = dist
    e.create_session('private customer name')
    snapshot = e.node_work('gateway-b', NODES['gateway-b'])
    assert not snapshot['sessions']
    assert 'mock_world' not in snapshot
    assert 'private customer name' not in str(snapshot)


def test_server_restart_keeps_unconfirmed_task_blocked(tmp_path):
    path = str(tmp_path / 'distributed.db')
    clock = Clock()
    engine = DistributedEngine(path, clock=clock)
    engine.node_heartbeat('gateway-a', NODES['gateway-a'])
    sid = engine.create_session('A')['session_id']
    engine.submit_order(sid, [{'sku': 'SKU-JIN-RAMEN', 'quantity': 1}], 'request-0001')
    command = engine.node_claim('gateway-a', NODES['gateway-a'])
    engine.node_event('gateway-a', NODES['gateway-a'], make_event(command, 'ACCEPTED'))
    engine.store.close()
    restored = DistributedEngine(path, clock=clock)
    try:
        assert restored.state['sessions'][sid]['error']
        assert not restored.state['sessions'][sid]['inventory']
        assert not any(n['connected'] for n in restored.state['gateways'].values())
        restored.node_heartbeat('gateway-a', 'after-server-restart')
        claimed = restored.node_claim('gateway-a', 'after-server-restart')
        assert claimed is None or claimed['kind'] == 'STOP'
    finally:
        restored.store.close()


def test_wrong_database_mode_does_not_change_checkpoint(tmp_path):
    path = str(tmp_path / 'legacy.db')
    legacy = Engine(path)
    legacy.create_session('legacy customer')
    before = legacy.store.load()
    legacy.store.close()
    with pytest.raises(DomainError):
        DistributedEngine(path)
    store = Store(path)
    try:
        assert store.load() == before
    finally:
        store.close()
