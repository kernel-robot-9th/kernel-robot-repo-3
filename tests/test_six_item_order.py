import json
import threading
from concurrent.futures import ThreadPoolExecutor

from robot_gateway.mock import make_event
from server.distributed import DistributedEngine
from server.catalog import PRODUCTS_PATH


def engine(tmp_path):
    products = json.loads(PRODUCTS_PATH.read_text())
    for p in products:
        p['station'] = 'load-a' if p['sku'] == 'SKU-RICE-CHIP' else 'load-b'
    catalog = tmp_path/'products.json'
    catalog.write_text(json.dumps(products))
    e = DistributedEngine(mode='hardware', readiness={'approved': True, 'parallel_order': True,
        'handoff_arrival_only': True, 'products_file': str(catalog)})
    for node in ['gateway-a', 'gateway-b']:
        e.node_heartbeat(node, node+'-test')
    return e


def test_partial_pick_failure_records_only_finished_item(tmp_path):
    e = engine(tmp_path)
    try:
        sid = e.create_session('부분 적재')['session_id']
        e.submit_order(sid, [{'sku':'SKU-RICE-CHIP','quantity':3},
            {'sku':'SKU-JIN-RAMEN','quantity':1}, {'sku':'SKU-SHIN-RAMEN','quantity':1},
            {'sku':'SKU-CHEETOS','quantity':1}], 'partial-order')
        for _ in range(6):
            cmd = e.node_claim('gateway-a','gateway-a-test')
            if not cmd:
                break
            e.node_event('gateway-a','gateway-a-test',make_event(cmd,'ACCEPTED'))
            e.node_event('gateway-a','gateway-a-test',make_event(cmd,'SUCCEEDED',{}))
            if cmd['robot_id'] == 'pinky-2':
                break
        cmd = e.node_claim('gateway-b','gateway-b-test')
        assert cmd['kind'] == 'PICK'
        e.node_event('gateway-b','gateway-b-test',make_event(cmd,'ACCEPTED'))
        first = cmd['items'][0]
        e.node_event('gateway-b','gateway-b-test',make_event(cmd,'FAILED',
            {'executed_items':[first], 'reason':'작업대 카메라 수신 실패'}))
        run = e.state['sessions'][sid]['robot_runs']['pinky-2']
        assert run['state'] == 'ERROR'
        assert [i['item_id'] for i in run['inventory']] == [first['item_id']]
        assert run['inventory'][0]['physical_loading_confirmed'] is False
        assert [e.state['units'][i['item_id']]['state'] for i in cmd['items']] == ['LOADED','PLANNED','PLANNED']
    finally:
        e.store.close()


def test_one_order_two_carts_and_only_one_c_arrival(tmp_path):
    e = engine(tmp_path)
    try:
        sid = e.create_session('6개 한 주문')['session_id']
        items = [{'sku':'SKU-RICE-CHIP', 'quantity':3}] + [
            {'sku':sku, 'quantity':1} for sku in ['SKU-JIN-RAMEN','SKU-SHIN-RAMEN','SKU-CHEETOS']]
        order = e.submit_order(sid, items, 'one-order')
        assert e.submit_order(sid, items, 'one-order')['id'] == order['id']
        assert len(e.state['sessions']) == len(e.state['orders']) == 1
        assert {(t['robot_id'],t['zone_id']) for t in e.state['tasks'].values()} == {
            ('pinky-1','load-a'), ('pinky-2','load-b')}
        assert all(len(t['items']) == 3 and t['order_id'] == order['id'] for t in e.state['tasks'].values())
        e.checkout(sid)
        commands=[]
        for _ in range(16):
            progressed=False
            for node in ['gateway-a','gateway-b']:
                cmd=e.node_claim(node,node+'-test')
                if cmd is None: continue
                progressed=True;commands.append(cmd)
                e.node_event(node,node+'-test',make_event(cmd,'ACCEPTED'))
                if cmd['zone_id']=='handoff':
                    assert all(u['state']=='LOADED' for u in e.state['units'].values())
                    assert all(t['state'] in {'DONE','WAIT_LOADED'} for t in e.state['tasks'].values() if t['kind']=='LOAD')
                    assert cmd['handoff_arrival_only']
                data={'executed_items':cmd['items']} if cmd['kind']=='PICK' else {'nav2_completed':True}
                e.node_event(node,node+'-test',make_event(cmd,'SUCCEEDED',data))
            if not progressed: break
        snap=e.snapshot(sid)
        session=snap['sessions'][sid]
        assert session['state']=='WAIT_UNLOAD' and session['completed_at'] is None
        assert len(session['inventory'])==6
        assert all(not i['delivered'] and not i['physical_loading_confirmed'] for i in session['inventory'])
        assert {i['robot_id'] for i in session['inventory']}=={'pinky-1','pinky-2'}
        assert len([c for c in commands if c['zone_id']=='handoff'])==1
        assert not any(c['kind']=='HANDOFF' for c in commands)
        assert not any(c['kind']=='LEAVE' and c['robot_id']=='pinky-2' for c in commands)
        assert all('token_hash' not in r for r in session['robot_runs'].values())
        assert all(t['session_id']==sid for t in snap['tasks'].values())
    finally:
        e.store.close()


def test_rear_moves_after_departure_before_front_parking(tmp_path, monkeypatch):
    from robot_gateway.hardware.control_fleet import ControlFleet
    fleet=ControlFleet.__new__(ControlFleet)
    fleet.state_path=tmp_path/'state.json'
    depart=threading.Event();rear=threading.Event();front_started=threading.Event()
    class Mobile:
        def __init__(self, robot): self.robot=robot
        def execute(self, command, cancelled, segment_done=None):
            if self.robot=='pinky-1':
                front_started.set()
                assert depart.wait(2)
                segment_done('home_depart')
                assert rear.wait(2), 'Rear was blocked until the front completed its trip'
            else:
                assert depart.is_set()
                rear.set()
            return {'parking_start':'observe'}
    fleet.mobile=lambda robot:Mobile(robot)
    monkeypatch.setattr('robot_gateway.hardware.control_fleet.run_station',lambda *a,**kw:{'status':'aligned'})
    def run(robot,zone):
        return fleet.execute({'kind':'NAVIGATE','robot_id':robot,'device_id':robot,'zone_id':zone},threading.Event())
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(run,'pinky-1','load-a')
        assert front_started.wait(2)
        second=pool.submit(run,'pinky-2','load-b')
        assert not rear.wait(.15)
        depart.set()
        assert first.result(timeout=3)['location']=='A'
        assert second.result(timeout=3)['location']=='B'
    assert fleet.state()=={'P1':'A','P2':'B'}
