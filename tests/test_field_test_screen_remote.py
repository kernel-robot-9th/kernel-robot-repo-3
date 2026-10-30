"""Remote test-screen requests, without cameras or robot motion."""
from copy import deepcopy
import threading

from robot_gateway.hardware import station_remote
from robot_gateway.test_agent import RemoteHardwareTrials
from server.device_tests import Bench
from server.distributed import DistributedEngine


def test_remote_pick_forwards_selected_slot_and_reports_actual_status(monkeypatch):
    report = {'allow_motion': True, 'operations': ['PICK'], 'issues': [], 'checks': [],
              'slots': {'pinky-1': [0, 1, 2], 'pinky-2': [0, 1, 2]}}
    monkeypatch.setattr(station_remote, 'inspect_station', lambda zone: deepcopy(report))
    calls = []
    monkeypatch.setattr(station_remote.RemoteArm, 'execute',
                        lambda self, command, cancelled: calls.append((self.zone, command, cancelled)) or
                        {'operator_review_required': True})
    trial = RemoteHardwareTrials({'node_id': 'gateway-a', 'remote_arm_zone': 'A'}, None)
    cancelled = threading.Event()
    try:
        job = {'id': 'test-1', 'kind': 'PICK', 'mode': 'hardware',
               'parameters': {'sku': 'SKU-RICE-CHIP', 'robot_id': 'pinky-1', 'slot': 2}}
        result = trial.execute(job, cancelled)
        zone, command, token = calls[0]
        assert zone == 'A' and token is cancelled
        assert command['scope'] == 'device_test'
        assert command['items'][0]['sku'] == 'SKU-RICE-CHIP' and command['items'][0]['slot'] == 2
        assert result['operator_review_required'] is True
    finally:
        trial.close()


def test_previous_order_and_finished_pick_do_not_block_next_pick():
    engine = DistributedEngine()
    try:
        instance = 'field-test-instance'
        engine.node_heartbeat('gateway-a', instance)
        bench = Bench(engine)
        profile = {'allow_motion': True, 'operations': ['PICK'], 'slots': {'pinky-1': [0, 1]}}
        bench.poll('gateway-a', instance, profile, False)
        session = engine.create_session('test')['session_id']
        engine.submit_order(session, [{'sku': 'SKU-JIN-RAMEN', 'quantity': 1}], 'existing-order')
        params = {'sku': 'SKU-JIN-RAMEN', 'robot_id': 'pinky-1', 'slot': 0}
        job = bench.create('gateway-a', 'PICK', params, 'pick-1', prepared=True)
        bench.poll('gateway-a', instance, profile, True)
        bench.event('gateway-a', instance, job['id'], 'event-1', 'ACCEPTED', {})
        bench.event('gateway-a', instance, job['id'], 'event-2', 'STARTED', {})
        bench.event('gateway-a', instance, job['id'], 'event-3', 'FINISHED', {'operator_review_required': True})
        result = bench.job(job['id'])
        assert result['status'] == 'WAIT_REVIEW' and result['released_at'] is not None
        assert bench.state['hold'] is None
        assert bench.create('gateway-a', 'PICK', {**params, 'slot': 1}, 'pick-2', prepared=True)['status'] == 'CREATED'
    finally:
        engine.store.close()
