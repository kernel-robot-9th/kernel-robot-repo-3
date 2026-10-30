"""Order/worker result contract only; no robot, camera or network access."""
from copy import deepcopy
import json

import pytest

from robot_gateway.mock import make_event
from server.catalog import PRODUCTS_PATH
from server.device_tests import Bench
from server.distributed import DistributedEngine
from server.domain import DomainError


@pytest.fixture
def fleet(tmp_path):
    products = json.loads(PRODUCTS_PATH.read_text())
    for product in products:
        product['station'] = 'load-a' if product['sku'] == 'SKU-RICE-CHIP' else 'load-b'
    catalog = tmp_path/'products.json'
    catalog.write_text(json.dumps(products))
    engine = DistributedEngine(mode='hardware', readiness={'approved': True, 'parallel_order': True,
        'unload_engine': 'yolo', 'handoff_arrival_only': False, 'products_file': str(catalog)})
    for node in ('gateway-a', 'gateway-b', 'gateway-c'):
        engine.node_heartbeat(node, node+'-test')
    yield engine
    engine.store.close()


def finish(engine, command, kind='SUCCEEDED', data=None):
    node = command['gateway_id']
    engine.node_event(node, node+'-test', make_event(command, kind, data or {}))


def next_handoff(engine):
    for _ in range(24):
        for node in ('gateway-a', 'gateway-b', 'gateway-c'):
            command = engine.node_claim(node, node+'-test')
            if not command:
                continue
            finish(engine, command, 'ACCEPTED')
            if command['kind'] == 'HANDOFF':
                return command
            finish(engine, command, data={'executed_items': command['items']} if command['kind'] == 'PICK' else {})
    raise AssertionError('HANDOFF not reached')


def order(engine, six=False):
    sid = engine.create_session('C 연결 시험')['session_id']
    items = [{'sku': 'SKU-RICE-CHIP', 'quantity': 3 if six else 1}]
    if six:
        items += [{'sku': sku, 'quantity': 1} for sku in ('SKU-JIN-RAMEN','SKU-SHIN-RAMEN','SKU-CHEETOS')]
    engine.submit_order(sid, items, 'c-yolo-test')
    engine.checkout(sid)
    return sid


@pytest.mark.parametrize('reason', ['no_detections_rechecked', 'pick_limit_reached'])
def test_all_result_waits_for_explicit_confirmation_and_returns_once(fleet, reason):
    sid = order(fleet)
    cmd = next_handoff(fleet)
    assert cmd['unload_engine'] == 'yolo' and 'model_id' not in cmd
    with pytest.raises(DomainError):
        fleet.field_observe(cmd['id'], 'delivered', 'tester')
    result = {'engine': 'yolo_unload', 'selection_mode': 'all', 'executed_items': [],
              'attempted_items': [{'class': 'jin_ramen'}] * 12, 'reason': reason,
              'physical_delivery_confirmed': False, 'operator_review_required': True}
    finish(fleet, cmd, data=result)
    task = fleet.state['tasks'][cmd['task_id']]
    assert task['state'] == 'WAIT_UNLOAD_REVIEW'
    assert not any(c['kind']=='LEAVE' and c['task_id']==task['id'] for c in fleet.state['commands'].values())
    assert all(u['state']=='LOADED' for u in fleet.state['units'].values())
    assert fleet.state['commands'][cmd['id']]['result']['data'] == result
    fleet.field_observe(cmd['id'], 'delivered', 'tester')
    assert fleet.field_observe(cmd['id'], 'delivered', 'tester')['duplicate']
    leaves = [c for c in fleet.state['commands'].values() if c['task_id']==task['id'] and c['kind']=='LEAVE']
    assert len(leaves)==1
    item = fleet.state['sessions'][sid]['inventory'][0]
    assert item['delivered'] and item['physical_delivery_confirmed']
    cmd = fleet.node_claim('gateway-a', 'gateway-a-test')
    assert cmd['kind']=='LEAVE'
    finish(fleet, cmd, 'ACCEPTED'); finish(fleet, cmd)
    assert fleet.state['sessions'][sid]['state']=='COMPLETED'


def test_six_item_confirmation_applies_to_only_current_robot(fleet):
    sid = order(fleet, six=True)
    seen = []
    for _ in range(2):
        cmd = next_handoff(fleet)
        seen.append(cmd['robot_id'])
        finish(fleet, cmd, data={'engine':'yolo_unload','executed_items':[], 'operator_review_required':True})
        before = {i['item_id'] for run in fleet._runs(fleet.state['sessions'][sid]) for i in run['inventory'] if i['delivered']}
        fleet.field_observe(cmd['id'], 'delivered', 'tester')
        after = {i['item_id'] for run in fleet._runs(fleet.state['sessions'][sid]) for i in run['inventory'] if i['delivered']}
        assert after-before == {i['item_id'] for i in cmd['items']}
        leave = fleet.node_claim('gateway-a','gateway-a-test')
        assert leave['kind']=='LEAVE' and leave['robot_id']==cmd['robot_id']
        finish(fleet, leave, 'ACCEPTED'); finish(fleet, leave)
    assert set(seen)=={'pinky-1','pinky-2'}
    assert fleet.state['sessions'][sid]['state']=='COMPLETED'


def test_failed_handoff_does_not_turn_attempts_into_delivery(fleet):
    order(fleet)
    cmd = next_handoff(fleet)
    finish(fleet, cmd, 'FAILED', {'engine':'yolo_unload','executed_items':cmd['items'], 'reason':'camera lost'})
    assert all(u['state']=='LOADED' for u in fleet.state['units'].values())
    with pytest.raises(DomainError):
        fleet.field_observe(cmd['id'], 'delivered', 'tester')


def test_yolo_test_review_uses_operator_confirmation_without_act_observation(fleet):
    bench = Bench(fleet)
    profile = {'allow_motion':True, 'operations':['HANDOFF'], 'sides':['left','right'], 'unload_engine':'yolo'}
    bench.poll('gateway-c','gateway-c-test',profile,False)
    job = bench.create('gateway-c','HANDOFF',{'side':'right','skus':['SKU-RICE-CHIP'], 'robot_id':'pinky-2'},'test',True)
    bench.poll('gateway-c','gateway-c-test',profile,True)
    for kind, data in [('ACCEPTED',{}),('STARTED',{}),('FINISHED',{'engine':'yolo_unload', 'executed_items':[]})]:
        bench.event('gateway-c','gateway-c-test',job['id'],kind,kind,data)
    bench.review(job['id'],'tester',True,True,'바구니 비움과 우측 상품 확인')
    assert bench.job(job['id'])['observation']['facts']['physical_delivery_confirmed']
    assert not fleet.state['units']


def test_c_configuration_preserves_db_and_parking_python(tmp_path):
    from scripts.six_item_demo import configure_c
    control = tmp_path/'pinky-control.json'
    value = {'stations':{'C':{'root':'/c/project','python':'/old/il','parking_python':'/camera/python'}}}
    control.write_text(json.dumps(value))
    (tmp_path/'readiness.json').write_text(json.dumps({'approved':True,'handoff_arrival_only':True}))
    (tmp_path/'worker-b.json').write_text(json.dumps({'node_id':'gateway-b','remote_arm_zone':'B','state_directory':'keep'}))
    db = tmp_path/'shopping.db'; db.write_bytes(b'existing database')
    configure_c(tmp_path, control)
    result = json.loads(control.read_text())
    assert result['stations']['C']['parking_python']=='/camera/python'
    assert result['stations']['C']['python']=='/c/project/runtime/field/c-yolo-venv/bin/python'
    assert json.loads((tmp_path/'worker-c.json').read_text())['state_directory']=='keep'
    assert json.loads((tmp_path/'readiness.json').read_text())['unload_engine']=='yolo'
    assert db.read_bytes()==b'existing database'
    assert list(tmp_path.glob('before-c-link-*/pinky-control.json'))


def test_c_arm_uses_clean_environment_but_parking_keeps_ros():
    from robot_gateway.hardware.station_remote import station_command
    config = {'ssh_key':'/key','stations':{'C':{'root':'/c','host':'team2@c',
                                             'python':'/yolo/python','parking_python':'/camera/python'}}}
    arm = station_command(config,'C',{'operation':'arm'})[-1]
    inspect = station_command(config,'C',{'operation':'inspect'})[-1]
    parking = station_command(config,'C',{'operation':'parking'})[-1]
    assert 'env -u PYTHONPATH -u PYTHONHOME /yolo/python' in arm and '/yolo/python' in inspect
    assert 'run_pinky_station.sh /camera/python' in parking
