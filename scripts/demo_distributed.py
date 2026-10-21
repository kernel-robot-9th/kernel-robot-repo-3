"""Separate-process HTTP validation. Results are explicitly virtual, not physical."""
from datetime import datetime, timezone
import json
import socket
import time
from pathlib import Path

from robot_gateway.mock import Client
from preview import PreviewGroup
from prepare_distributed import ROOT


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def scenario(name, root):
    report = {'scenario': name, 'mode': 'mock', 'physical_hardware_verified': False}
    with PreviewGroup(root / name, free_port(), auto=True) as group:
        admin = Client(group.base, group.credentials['admin'])
        guests = []
        for label in ['고객 A', '고객 B']:
            guest = Client(group.base, '').call('/api/sessions', {'label': label})
            guests.append((guest, Client(group.base, guest['token'])))
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            snapshot = admin.call('/api/admin/state')
            if all(n['connected'] for n in snapshot['gateways'].values()):
                break
            time.sleep(0.1)
        else:
            raise AssertionError('중개 3개 연결 시간 초과')
        sku = 'SKU-RICE-CHIP' if name == 'disconnect' else 'SKU-JIN-RAMEN'
        if name == 'pick-failure':
            admin.call('/api/admin/mock/fault', {'device_id': 'omx-a', 'kind': 'PICK_FAIL'})
        killed = False
        if name == 'disconnect':
            # Terminate before submission; polling for SENT can miss a short
            # execution and accidentally test an already completed job.
            group.children['gateway-b'].terminate()
            group.children['gateway-b'].wait(timeout=5)
            killed = True
        for index, (guest, client) in enumerate(guests):
            selected_sku = 'SKU-SHIN-RAMEN' if index == 1 and sku == 'SKU-JIN-RAMEN' else sku
            items = [{'sku': selected_sku, 'quantity': 1}]
            if name == 'complete':
                items.append({'sku': 'SKU-RICE-CHIP', 'quantity': 3})
            client.call('/api/customer/orders', {'request_id': f'http-order-{index:04d}', 'items': items})
            client.call('/api/customer/checkout', {})
        saw_wait = False
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            snapshot = admin.call('/api/admin/state')
            saw_wait |= any(z['queue'] for z in snapshot['zones'].values())
            sessions = list(snapshot['sessions'].values())
            if name == 'complete':
                for session in sessions:
                    task = snapshot['tasks'].get(session['current_task'])
                    if task and task['state'] == 'WAIT_BASKET':
                        admin.call('/api/admin/basket-ready', {'session_id': session['id'], 'task_id': task['id'],
                                                             'basket_id': session['basket_id']})
                if all(s['state'] == 'COMPLETED' and s['current_task'] is None for s in sessions):
                    assert saw_wait
                    assert len({s['robot_id'] for s in sessions}) == 2
                    assert all(len(s['inventory']) == 4 and all(i['delivered'] for i in s['inventory']) for s in sessions)
                    assert len(snapshot['trips']) == 4
                    assert all(z['owner'] is None for z in snapshot['zones'].values())
                    break
            elif name == 'pick-failure' and any(s['error'] for s in sessions):
                failed = next(s for s in sessions if s['error'])
                assert failed['inventory'] == []
                assert snapshot['zones']['load-a']['owner'] == failed['current_task']
                break
            elif name == 'disconnect':
                # Freshness may expire just before the periodic watchdog saves
                # the fault. Wait for both observations within the deadline.
                if killed and not snapshot['gateways']['gateway-b']['connected'] and any(s['error'] for s in sessions):
                    assert snapshot['gateways']['gateway-a']['connected']
                    assert snapshot['gateways']['gateway-c']['connected']
                    assert any(s['error'] for s in sessions)
                    assert snapshot['zones']['load-b']['owner']
                    assert all(not s['inventory'] for s in sessions)
                    break
            time.sleep(0.05)
        else:
            raise AssertionError(f'{name}: scenario deadline exceeded')
        report.update(status='PASS', saw_zone_wait=saw_wait,
                      session_states=[s['state'] for s in snapshot['sessions'].values()],
                      inventory_counts=[len(s['inventory']) for s in snapshot['sessions'].values()],
                      command_count=len(snapshot['commands']),
                      nodes={k: n['connected'] for k, n in snapshot['gateways'].items()})
    return report


def main():
    root = ROOT / 'runtime' / 'verification' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    root.mkdir(parents=True)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'mode': 'mock',
              'physical_hardware_verified': False, 'checks': [], 'status': 'RUNNING'}
    try:
        for name in ['complete', 'pick-failure', 'disconnect']:
            report['checks'].append(scenario(name, root))
            print(name + ': PASS', flush=True)
        report['status'] = 'PASS'
    except Exception as exc:
        report.update(status='FAIL', error=str(exc))
        raise
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        (root / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('결과: ' + str(root / 'verification.json'), flush=True)


if __name__ == '__main__':
    main()
