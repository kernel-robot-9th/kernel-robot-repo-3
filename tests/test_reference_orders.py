"""V4 integration tests use synthetic pose/results, never hardware evidence."""
from copy import deepcopy
import uuid
import pytest
from fastapi.testclient import TestClient

from conftest import Clock
from robot_gateway.mock import next_action, make_event
from robots.pinky import compact
from server.reference import ReferenceEngine
from server.domain import DomainError
from server.api import create_app
from test_distributed import ADMIN, TOKENS

PROFILE = dict(allow_motion=True, motion_backend=compact.BACKEND, source_hash=compact.bundle()[3])
NODES = ('gateway-a','gateway-b','gateway-c')


class Rig:
    def __init__(self, path=':memory:'):
        self.clock = Clock(); self.e = ReferenceEngine(path, clock=self.clock)
        self.e.receiver_clock = self.clock
        self.beat()

    def beat(self):
        for n in NODES: self.e.node_heartbeat(n, n+'-test-instance')

    def sample(self, job, finished=False, seq=1):
        r = compact.route(job['parameters']['route_id']); t = r.duration if finished else r.duration/2
        pose, speed = r.sample(t)
        return dict(run_id=job['run_id'], command_id=job['id'], task_id=job['task_id'], session_id=job['session_id'],
            robot_id=job['robot_id'], backend=compact.BACKEND, observation_source=compact.BACKEND, route_version=4,
            frame_id=compact.FRAME, source_hash=compact.bundle()[3], sim_epoch='reference-test-001', sequence=seq,
            sim_time=t, observed_at=self.clock(), pose=pose, speed=0. if finished else speed,
            halted=finished, arrived=finished, progress=t/r.duration)

    def event(self, job, kind, data=None):
        return self.e.motion_event('gateway-a','gateway-a-test-instance',job['id'],str(uuid.uuid4()),kind,data or {})

    def start_motion(self):
        job = self.e.motion_poll('gateway-a','gateway-a-test-instance',PROFILE,True)['job']
        assert job
        self.event(job,'ACCEPTED'); self.event(job,'STARTED')
        return job

    def step(self, ready=True, finish=True):
        e = self.e; self.beat()
        job = e.state['road']['jobs'].get(e.state['road']['active'])
        if job and job['status'] == 'CREATED': job = self.start_motion()
        if job and job['status'] == 'RUNNING' and finish:
            self.event(job,'FINISHED',{'outcome':'SUCCEEDED','sample':self.sample(job,True)})
            return True
        for s in e.state['sessions'].values():
            t = e.state['tasks'].get(s['current_task'])
            if ready and t and t['state'] == 'WAIT_BASKET':
                e.basket_ready(s['id'],t['id'],s['basket_id']); return True
        for n in NODES:
            action = next_action(e.node_work(n,n+'-test-instance'))
            if action:
                kind, cmd = action
                if kind == 'CLAIM': e.node_claim(n,n+'-test-instance')
                else:
                    event = make_event(cmd,'ACCEPTED',observed_at=self.clock()) if kind == 'ACCEPTED' else e.mock_action(n,n+'-test-instance',cmd['id'],kind)
                    e.node_event(n,n+'-test-instance',event)
                return True
        return False

    def until(self, predicate, limit=300, **kwargs):
        for _ in range(limit):
            if predicate(): return
            self.step(**kwargs)
        assert predicate(), str([(s['label'],s['state'],self.e.state['tasks'].get(s['current_task'])) for s in self.e.state['sessions'].values()]) + str(self.e.state['road']['waiting'])

    def order(self, label, stations, checkout=True):
        e=self.e; sid=e.create_session(label)['session_id']
        items=[]
        for station in stations:
            sku=next(k for k,v in e.products.items() if v['station']==station and e.state['stock'][k]['on_hand']-e.state['stock'][k]['reserved']>0 and k not in [i['sku'] for i in items])
            items.append(dict(sku=sku,quantity=1))
        e.submit_order(sid,items,str(uuid.uuid4()))
        if checkout: e.checkout(sid)
        return sid

    def done(self):
        return all(s['state']=='COMPLETED' and s['current_task'] is None for s in self.e.state['sessions'].values()) and not self.e.state['road']['active']


@pytest.fixture
def rig():
    r=Rig(); yield r; r.e.store.close()


def test_all_v4_paths_have_valid_basket_footprints():
    assert len(compact.bundle()[1]) == 9
    for name in compact.bundle()[1]: compact.route(name).check()


@pytest.mark.parametrize('first', [('load-a',),('load-b',),('load-b','load-a')])
@pytest.mark.parametrize('second', [('load-a',),('load-b',),('load-b','load-a')])
def test_two_customers_direct_routes(rig, first, second):
    a=rig.order('A',first); b=rig.order('B',second)
    rig.until(rig.done)
    e=rig.e
    assert not any(s['error'] for s in e.state['sessions'].values())
    assert len(e.state['sessions'][a]['inventory'])==len(first)
    assert len(e.state['sessions'][b]['inventory'])==len(second)
    jobs=list(e.state['road']['jobs'].values())
    assert all(j['status']=='SUCCEEDED' for j in jobs)
    assert all('_to_home_' not in j['parameters']['route_id'] or j['parameters']['route_id'].startswith('handoff_') for j in jobs)
    for zone in e.state['zones'].values(): assert zone['owner'] is None and not zone['queue']


def test_six_items_three_slots_two_round_trips_and_idle_leader_rotation(rig):
    e=rig.e; sid=e.create_session('six')['session_id']
    e.submit_order(sid,[dict(sku='SKU-RICE-CHIP',quantity=6)],'six-items')
    e.checkout(sid); rig.until(rig.done)
    assert len(e.state['trips'])==2
    assert all(len(t['unit_ids'])==3 for t in e.state['trips'].values())
    assert len(e.state['sessions'][sid]['inventory'])==6
    assert e.state['stock']['SKU-RICE-CHIP']['on_hand']==2
    assert any(j['purpose']=='QUEUE_YIELD' for j in e.state['road']['jobs'].values())


def test_rear_customer_only_can_finish_without_front_order(rig):
    e=rig.e; e.create_session('idle front'); sid=rig.order('rear',('load-a',))
    rig.until(lambda:e.state['sessions'][sid]['state']=='COMPLETED' and not e.state['sessions'][sid]['current_task'])
    assert any(j['purpose']=='QUEUE_YIELD' for j in e.state['road']['jobs'].values())


def test_additional_order_is_deferred_and_basket_readiness_required(rig):
    sid=rig.order('first B',('load-b',),False); e=rig.e
    rig.until(lambda:any(i for i in e.state['sessions'][sid]['inventory']))
    sku=next(k for k,p in e.products.items() if p['station']=='load-a')
    order=e.submit_order(sid,[dict(sku=sku,quantity=1)],'extra-order')
    assert all(u['state']=='RESERVED' for u in e.state['units'].values() if u['order_id']==order['id'])
    e.checkout(sid)
    rig.until(lambda:any(t['state']=='WAIT_BASKET' for t in e.state['tasks'].values()),ready=False)
    assert not any(c['kind']=='HANDOFF' for c in e.state['commands'].values())
    rig.until(rig.done)
    assert len(e.state['trips'])==2


def test_transfer_retains_both_zones_until_arrival_and_fails_closed(rig):
    sid=rig.order('AB',('load-a','load-b')); e=rig.e
    rig.until(lambda:any(j['parameters']['route_id']=='A_to_B' for j in e.state['road']['jobs'].values()))
    job=rig.start_motion(); rig.event(job,'PROGRESS',{'sample':rig.sample(job)})
    owners=[e.state['zones'][z]['owner'] for z in ('load-a','load-b')]
    assert all(owners)
    e.motion_stop(); rig.event(job,'STOP_ACK')
    assert e.state['road']['active']==job['id'] and not e.state['road']['jobs'][job['id']]['stopped']
    assert [e.state['zones'][z]['owner'] for z in ('load-a','load-b')]==owners
    with pytest.raises(DomainError): rig.event(job,'FINISHED',{'outcome':'SUCCEEDED','sample':rig.sample(job,True,2)})
    assert e.state['sessions'][sid]['error']


def test_duplicate_result_stale_hash_and_recovery(rig,tmp_path):
    rig.order('A',('load-a',)); e=rig.e; job=rig.start_motion()
    with pytest.raises(DomainError): rig.event(job,'PROGRESS',{'sample':{**rig.sample(job),'source_hash':'old'}})
    data={'outcome':'SUCCEEDED','sample':rig.sample(job,True)}
    key=str(uuid.uuid4()); args=('gateway-a','gateway-a-test-instance',job['id'],key,'FINISHED',data)
    e.motion_event(*args); before=deepcopy(e.state); e.motion_event(*args)
    assert e.state==before
    assert rig.event(job,'FINISHED',data)['duplicate']
    r=Rig(str(tmp_path/'ref.db')); r.order('B',('load-b',)); active=r.e.state['road']['active']; r.e.store.close()
    restarted=ReferenceEngine(str(tmp_path/'ref.db'))
    assert restarted.state['road']['active']==active and restarted.state['road']['blocked']
    restarted.store.close()
    from server.distributed import DistributedEngine
    with pytest.raises(DomainError): DistributedEngine(str(tmp_path/'ref.db'))


def test_api_auth_modes_and_motion_ownership(rig):
    e=rig.e
    with TestClient(create_app(engine=e,admin_token=ADMIN,node_tokens=TOKENS)) as client:
        assert client.get('/api/admin/road').status_code==401
        assert client.get('/api/admin/road/map',headers={'Authorization':'Bearer '+ADMIN}).json()['route_version']==4
        body=dict(node_id='gateway-a',instance_id='gateway-a-test-instance',mode='mock',profile=PROFILE,available=True)
        assert client.post('/api/nodes/motion/poll',json=body,headers={'Authorization':'Bearer '+TOKENS['gateway-b']}).status_code==403
    with pytest.raises(DomainError): ReferenceEngine(mode='hardware',test_only=True)


def test_stationary_arm_can_work_while_other_robot_moves(rig):
    sid=rig.order('A',('load-a',)); rig.order('B',('load-b',))
    e=rig.e
    rig.until(lambda:e.state['tasks'][e.state['sessions'][sid]['current_task']]['state']=='ARM_WORK')
    rig.until(lambda:any(c['kind']=='PICK' and c['status']=='ACCEPTED' for c in e.state['commands'].values()),finish=False)
    assert e.state['road']['active'] and e.state['road']['jobs'][e.state['road']['active']]['robot_id']=='pinky-2'
    assert e.state['tasks'][e.state['sessions'][sid]['current_task']]['state']=='ARM_WORK'


def test_cancel_before_transmission_and_reorder(rig):
    e=rig.e;sid=e.create_session('cancel')['session_id']
    o=e.submit_order(sid,[dict(sku='SKU-RICE-CHIP',quantity=1)],'first-order')
    e.cancel_order(sid,o['id'])
    assert not e.state['road']['active'] and e.state['stock']['SKU-RICE-CHIP']['reserved']==0
    e.submit_order(sid,[dict(sku='SKU-RICE-CHIP',quantity=1)],'second-order')
    e.checkout(sid);rig.until(rig.done)


def test_stale_pose_retains_lease_and_duplicate_does_not_refresh(rig):
    rig.order('stale',('load-b',));job=rig.start_motion();e=rig.e
    sample=rig.sample(job);rig.event(job,'PROGRESS',{'sample':sample})
    received=e.state['road']['jobs'][job['id']]['telemetry']['received_monotonic']
    rig.clock.now+=1;rig.event(job,'PROGRESS',{'sample':sample})
    assert e.state['road']['jobs'][job['id']]['telemetry']['received_monotonic']==received
    rig.clock.now+=2.1;e.watchdog()
    assert e.state['road']['blocked'] and e.state['road']['active']==job['id']
    assert e.state['zones']['load-b']['owner']==job['task_id']


def test_generic_mock_navigation_cannot_bypass_pose_contract(rig):
    rig.order('no bypass',('load-a',));job=rig.start_motion();e=rig.e
    before=deepcopy(e.state['mock_world'])
    with pytest.raises(DomainError): e.mock_action('gateway-a','gateway-a-test-instance',job['order_command_id'],'EXECUTE')
    assert e.state['mock_world']==before
