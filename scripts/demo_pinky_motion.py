"""Separate-process reference-path trials. No ROS, Isaac, or physical robots."""
from datetime import datetime, timezone
import json
import time
import uuid

from demo_distributed import free_port
from preview import PreviewGroup
from prepare_distributed import ROOT
from robot_gateway.mock import Client


def run():
    directory = ROOT / 'runtime' / 'verification' / ('pinky-motion-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    checks, jobs = [], []
    with PreviewGroup(directory, free_port(), auto=False) as group:
        admin = Client(group.base, group.credentials['admin'])

        def snapshot():
            return admin.call('/api/admin/device-tests')

        def until(predicate, timeout=20):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                state = snapshot()
                if predicate(state):
                    return state
                time.sleep(.1)
            raise AssertionError('reference trial timeout: ' + json.dumps(state, ensure_ascii=False)[:1500])

        def request(route_id, rate=4, failure=False):
            return admin.call('/api/admin/device-tests', {
                'node_id': 'gateway-a', 'kind': 'NAVIGATE', 'prepared': True,
                'request_id': str(uuid.uuid4()), 'simulate_failure': failure,
                'parameters': {'robot_id': 'pinky-1', 'route_id': route_id, 'rate': rate},
            })['id']

        def wait_job(jid, status):
            return until(lambda s: s['jobs'][jid]['status'] == status)['jobs'][jid]

        def release(jid):
            assert snapshot()['hold'] == jid
            admin.call(f'/api/admin/device-tests/{jid}/release', {
                'operator': 'automated-reference-check', 'restored': True})

        until(lambda s: s['nodes'].get('gateway-a', {}).get('motion_backend') == 'reference_path')
        layout = admin.call('/api/admin/motion-map')
        before = admin.call('/api/admin/state')
        jid = request('queue_advance')
        job = wait_job(jid, 'SUCCEEDED')
        assert job['accepted_at'] is not None and job['started_at'] is not None
        assert job['telemetry']['arrived'] and job['telemetry']['halted'] and job['stopped']
        jobs.append(job); release(jid); checks.append('arrival_and_halt_confirmed')

        jid = request('home_to_A', rate=1)
        until(lambda s: s['jobs'][jid]['status'] == 'RUNNING' and s['jobs'][jid]['telemetry'] is not None)
        admin.call(f'/api/admin/device-tests/{jid}/stop', {})
        job = wait_job(jid, 'CANCELLED')
        assert job['stop_ack_at'] is not None and job['stopped'] and job['telemetry']['halted']
        assert not job['telemetry']['arrived']
        jobs.append(job); release(jid); checks.append('stop_receipt_and_simulated_halt_separate')

        jid = request('queue_advance', failure=True)
        job = wait_job(jid, 'FAILED')
        assert job['stopped'] and not job['telemetry']['arrived']
        jobs.append(job); release(jid); checks.append('failure_not_arrival')

        jid = request('home_to_A', rate=1)
        until(lambda s: s['jobs'][jid]['status'] == 'RUNNING' and s['jobs'][jid]['telemetry'] is not None)
        group.children['gateway-a'].terminate()
        group.children['gateway-a'].wait(timeout=5)
        job = wait_job(jid, 'UNCERTAIN')
        assert snapshot()['hold'] == jid and job['stop_requested_at'] is not None and not job['stopped']
        jobs.append(job); checks.append('lost_observation_retains_hold')
        after = admin.call('/api/admin/state')
        assert after['stock'] == before['stock'] and after['sessions'] == before['sessions']
        checks.append('customer_inventory_and_sessions_unchanged')
    report = {'status': 'PASS', 'backend': 'reference_path', 'physical_hardware_verified': False,
              'physics_tracking_verified': False, 'route_version': layout['route_version'],
              'source_hash': layout['source_hash'], 'checks': checks, 'jobs': jobs,
              'at': datetime.now(timezone.utc).isoformat()}
    path = directory / 'verification.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'PASS', 'checks': len(checks), 'report': str(path)}, ensure_ascii=False))


if __name__ == '__main__':
    run()
