"""Four local processes; commissioning protocol only, no physical devices."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from demo_distributed import free_port
from preview import PreviewGroup
from prepare_distributed import ROOT
from robot_gateway.mock import Client


def run():
    directory = ROOT / 'runtime' / 'verification' / ('device-tests-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    results = []
    with PreviewGroup(directory, free_port(), auto=False) as group:
        admin = Client(group.base, group.credentials['admin'])

        def snapshot():
            return admin.call('/api/admin/device-tests')

        def until(predicate, timeout=30):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                state = snapshot()
                if predicate(state):
                    return state
                time.sleep(.1)
            raise AssertionError('commissioning timeout: ' + json.dumps(state, ensure_ascii=False)[:1000])

        def request(node, kind, parameters=None, failure=False):
            return admin.call('/api/admin/device-tests', {'node_id': node, 'kind': kind,
                'parameters': parameters or {}, 'request_id': str(uuid.uuid4()),
                'prepared': kind in {'PICK', 'HANDOFF'}, 'simulate_failure': failure})['id']

        def wait_job(jid, state):
            return until(lambda s: s['jobs'][jid]['status'] == state)['jobs'][jid]

        def review(jid, success):
            admin.call(f'/api/admin/device-tests/{jid}/review', {'operator': 'automated-mock-check',
                'success': success, 'stopped': True, 'note': 'MOCK simulation confirmation; no physical claim'})
            admin.call(f'/api/admin/device-tests/{jid}/release', {'operator': 'automated-mock-check', 'restored': True})

        until(lambda s: len(s['nodes']) == 3 and all(n['online'] for n in s['nodes'].values()))
        stock = admin.call('/api/admin/state')['stock']
        for node in ('gateway-a', 'gateway-b', 'gateway-c'):
            jid = request(node, 'PING')
            assert wait_job(jid, 'SUCCEEDED')['result']['data']['node_id'] == node
        results.append('three_gateway_ping')
        jid = request('gateway-a', 'INSPECT')
        wait_job(jid, 'SUCCEEDED'); results.append('inspection_without_devices')
        params = {'sku': 'SKU-JIN-RAMEN', 'slot': 2, 'robot_id': 'pinky-2'}
        jid = request('gateway-a', 'PICK', params)
        job = wait_job(jid, 'WAIT_REVIEW')
        assert job['accepted_at'] is not None and job['started_at'] is not None
        assert snapshot()['hold'] == jid
        review(jid, True); results.append('pick_review_and_restore')
        jid = request('gateway-c', 'HANDOFF', {'side': 'left', 'skus': ['SKU-JIN-RAMEN', 'SKU-RICE-CHIP']})
        wait_job(jid, 'RUNNING')
        admin.call(f'/api/admin/device-tests/{jid}/observe', {'operator': 'automated-mock-check',
                   'facts': dict.fromkeys(['cart_visible', 'cart_empty', 'last_item_placed', 'standby_reached'], True)})
        assert wait_job(jid, 'WAIT_REVIEW')['stopped']['source'] == 'simulation'
        review(jid, True); results.append('handoff_observation_and_stop_feedback')
        jid = request('gateway-c', 'HANDOFF', {'side': 'left', 'skus': ['SKU-JIN-RAMEN']})
        wait_job(jid, 'RUNNING')
        admin.call(f'/api/admin/device-tests/{jid}/stop', {})
        job = wait_job(jid, 'WAIT_REVIEW')
        assert job['stop_ack_at'] is not None and job['stopped'] is None
        review(jid, False); results.append('stop_ack_is_not_physical_stop')
        jid = request('gateway-b', 'PICK', {**params, 'sku': 'SKU-RICE-CHIP'}, True)
        assert wait_job(jid, 'WAIT_REVIEW')['result']['kind'] == 'ERROR'
        review(jid, False); results.append('pick_error_not_success')
        jid = request('gateway-b', 'PICK', {**params, 'sku': 'SKU-RICE-CHIP'})
        wait_job(jid, 'RUNNING')
        group.children['gateway-b'].terminate(); group.children['gateway-b'].wait(timeout=5)
        wait_job(jid, 'UNCERTAIN')
        assert snapshot()['hold'] == jid
        results.append('disconnect_retains_test_hold')
        assert admin.call('/api/admin/state')['stock'] == stock
        results.append('customer_inventory_unchanged')
    report = {'status': 'PASS', 'mode': 'mock', 'physical_hardware_verified': False,
              'checks': results, 'at': datetime.now(timezone.utc).isoformat()}
    (directory / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'PASS', 'checks': len(results), 'report': str(directory / 'verification.json')}))


if __name__ == '__main__':
    run()
