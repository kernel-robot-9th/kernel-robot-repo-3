"""Pinky reference contracts: fake clocks/devices, never physical actuation."""
from copy import deepcopy
import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import Clock
from server.api import create_app
from server.device_tests import Bench
from server.distributed import DistributedEngine
from server.domain import DomainError
from robots.pinky.catalog import BACKEND, FRAME, VERSION, bundle, route, public_map
from robots.pinky.simulator import ReferenceMobile
from test_distributed import ADMIN, TOKENS

NODE, INSTANCE = 'gateway-a', 'motion-instance-001'
PARAMS = {'robot_id': 'pinky-1', 'route_id': 'queue_advance', 'rate': 4}
PROFILE = dict(allow_motion=True, operations=['NAVIGATE'], motion_backend=BACKEND, source_hash=bundle()[3])


@pytest.fixture
def rig():
    clock = Clock()
    e = DistributedEngine(clock=clock)
    e.receiver_clock = clock
    e.node_heartbeat(NODE, INSTANCE)
    b = Bench(e); b.poll(NODE, INSTANCE, PROFILE, False)
    yield b, e, clock
    e.store.close()


def create(b, params=None, key=None):
    return b.create(NODE, 'NAVIGATE', params or PARAMS, key or str(uuid.uuid4()), True)


def event(b, job, kind, data=None, key=None):
    return b.event(NODE, INSTANCE, job['id'], key or str(uuid.uuid4()), kind, data or {})


def start(b, job):
    b.poll(NODE, INSTANCE, PROFILE, True)
    event(b, job, 'ACCEPTED'); event(b, job, 'STARTED')


def sample(e, job, t=0., seq=1, halted=False):
    r = route(job['parameters']['route_id']); pose, speed = r.sample(t)
    return dict(run_id=job['run_id'], command_id=job['id'], task_id=job['id'], session_id=None,
                robot_id=job['robot_id'], backend=BACKEND, observation_source=BACKEND, route_version=VERSION,
                source_hash=bundle()[3], frame_id=FRAME, sim_epoch='sim-epoch-001', sequence=seq,
                sim_time=t, observed_at=e.clock(), pose=pose, speed=0. if halted else speed,
                halted=halted, arrived=t >= r.duration, progress=t / r.duration)


def test_map_uses_pinned_source_and_every_imported_path_passes():
    m = public_map()
    assert m['route_version'] == 3 and len(m['routes']) == 16 and len(m['nodes']) == 19
    assert len(m['edges']) == 26 and m['physics_tracking'] is False
    for key in bundle()[1]:
        route(key).check()
    # Returned data cannot mutate the pinned source cache.
    m['layout']['width'] = 99
    assert public_map()['layout']['width'] == 2


def test_motion_request_is_idempotent_and_exclusive_without_stock_writes(rig):
    b, e, _ = rig
    before = deepcopy(e.state['stock'])
    job = create(b, key='same-request-001')
    assert create(b, key='same-request-001')['id'] == job['id']
    with pytest.raises(DomainError):
        create(b, {**PARAMS, 'robot_id': 'pinky-2'}, 'same-request-001')
    with pytest.raises(DomainError):
        create(b)
    sid = e.create_session('A')['session_id']
    with pytest.raises(DomainError):
        e.submit_order(sid, [{'sku':'SKU-RICE-CHIP','quantity':1}], 'order-during-motion')
    assert e.state['stock'] == before and not e.state['commands']


def test_acceptance_progress_and_stop_ack_are_not_success(rig):
    b, e, _ = rig; job = create(b)
    with pytest.raises(DomainError):
        event(b, job, 'PROGRESS', {'sample': sample(e, job)})
    start(b, job)
    event(b, job, 'PROGRESS', {'sample': sample(e, job)})
    b.stop(job['id']); event(b, job, 'STOP_ACK')
    assert b.job(job['id'])['status'] == 'RUNNING' and b.job(job['id'])['stopped'] is None
    event(b, job, 'ERROR', {'outcome':'CANCELLED','sample':sample(e, job, .1, 2, True)})
    assert b.job(job['id'])['status'] == 'CANCELLED'
    assert b.state['hold'] == job['id']
    b.release(job['id'], 'tester', True)
    assert b.state['hold'] is None


@pytest.mark.parametrize('patch', [
    {'run_id':'wrong'}, {'robot_id':'pinky-2'}, {'frame_id':'map'}, {'route_version':2},
    {'observation_source':'feedback'}, {'source_hash':'wrong'}, {'sim_time':float('nan')},
    {'pose':[0,0,0]}, {'speed':float('inf')}, {'sequence':True},
])
def test_wrong_or_nonfinite_observations_are_rejected(rig, patch):
    b, e, _ = rig; job = create(b); start(b, job)
    with pytest.raises(DomainError):
        event(b, job, 'PROGRESS', {'sample': {**sample(e, job), **patch}})
    assert b.job(job['id'])['telemetry'] is None


def test_sequence_epoch_and_freshness_do_not_refresh_on_duplicates(rig):
    b, e, clock = rig; job = create(b); start(b, job)
    first = sample(e, job, .1, 2)
    event(b, job, 'PROGRESS', {'sample':first})
    received = b.job(job['id'])['telemetry']['received_monotonic']
    clock.now += .5
    assert event(b, job, 'PROGRESS', {'sample':first})['duplicate']
    assert b.job(job['id'])['telemetry']['received_monotonic'] == received
    for bad in [sample(e,job,.2,1), sample(e,job,.05,3),
                {**sample(e,job,.2,3),'sim_epoch':'another-epoch'},
                {**sample(e,job,.2,3),'observed_at':clock()-3},
                {**sample(e,job,.2,3),'observed_at':clock()+2}]:
        with pytest.raises(DomainError):
            event(b, job, 'PROGRESS', {'sample':bad})


def test_success_requires_arrival_halted_and_no_stop_request(rig):
    b, e, _ = rig; job=create(b); start(b,job)
    for data in [{}, {'outcome':'SUCCEEDED','sample':sample(e,job,.1,1,True)}]:
        with pytest.raises(DomainError):
            event(b,job,'FINISHED',data)
    complete={'outcome':'SUCCEEDED','sample':sample(e,job,route(PARAMS['route_id']).duration,3,True)}
    event(b,job,'FINISHED',complete,key='repeat-finish-001')
    count=len(b.job(job['id'])['timeline'])
    event(b,job,'FINISHED',complete,key='repeat-finish-001')
    assert len(b.job(job['id'])['timeline'])==count
    assert b.job(job['id'])['status']=='SUCCEEDED' and b.state['hold']==job['id']


def test_late_arrival_after_stop_is_never_success(rig):
    b,e,_=rig;job=create(b);start(b,job);b.stop(job['id'])
    with pytest.raises(DomainError):
        event(b,job,'FINISHED',{'outcome':'SUCCEEDED','sample':sample(e,job,route(PARAMS['route_id']).duration,1,True)})
    assert b.job(job['id'])['stopped'] is None


def test_stale_receiver_time_holds_trial_even_if_gateway_alive(rig):
    b,e,clock=rig;job=create(b);start(b,job)
    event(b,job,'PROGRESS',{'sample':sample(e,job)})
    clock.now+=3.1;e.node_heartbeat(NODE,INSTANCE);b.watchdog()
    assert b.job(job['id'])['status']=='UNCERTAIN' and b.state['hold']==job['id']
    with pytest.raises(DomainError):
        event(b,job,'FINISHED',{'outcome':'SUCCEEDED','sample':sample(e,job,route(PARAMS['route_id']).duration,2,True)})
    # Fresh actual simulator stop can settle uncertainty, but cannot free the hold.
    event(b,job,'ERROR',{'outcome':'CANCELLED','sample':sample(e,job,.2,2,True)})
    assert b.job(job['id'])['status']=='CANCELLED' and b.state['hold']==job['id']


def test_process_exit_without_pose_is_uncertain_and_restart_retains_hold(tmp_path):
    file=tmp_path/'motion.db';e=DistributedEngine(str(file));e.node_heartbeat(NODE,INSTANCE)
    b=Bench(e);b.poll(NODE,INSTANCE,PROFILE,False);job=create(b);start(b,job)
    event(b,job,'PROGRESS',{'sample':sample(e,job)})
    event(b,job,'ERROR',{'error':'process exited'})
    assert b.job(job['id'])['status']=='UNCERTAIN' and b.job(job['id'])['stopped'] is None
    e.store.close();restored=DistributedEngine(str(file))
    try:
        s=Bench(restored).snapshot()
        assert s['hold']==job['id'] and s['jobs'][job['id']]['status']=='UNCERTAIN'
        assert s['jobs'][job['id']]['telemetry']['age_seconds'] is None
    finally:restored.store.close()


def test_hardware_and_wrong_backend_cannot_start_reference_trial():
    e=DistributedEngine(mode='hardware',test_only=True);e.node_heartbeat(NODE,INSTANCE)
    b=Bench(e);b.poll(NODE,INSTANCE,PROFILE,False)
    try:
        with pytest.raises(DomainError,match='모의 중계'):
            create(b)
    finally:e.store.close()


def test_map_api_requires_admin_and_motion_is_scoped(rig):
    _,e,_=rig
    with TestClient(create_app(e,ADMIN,node_tokens=TOKENS)) as client:
        assert client.get('/api/admin/motion-map').status_code==401
        assert client.get('/api/admin/motion-map',headers={'Authorization':'Bearer '+ADMIN}).status_code==200
        body=dict(node_id=NODE,kind='NAVIGATE',parameters=PARAMS,request_id='api-motion-test',prepared=True)
        assert client.post('/api/admin/device-tests',json=body).status_code==401
        job=client.post('/api/admin/device-tests',json=body,headers={'Authorization':'Bearer '+ADMIN}).json()
        wrong=dict(node_id=NODE,instance_id=INSTANCE,job_id=job['id'],event_id='wrong-instance',kind='ACCEPTED')
        assert client.post('/api/nodes/device-tests/events',json=wrong,
                           headers={'Authorization':'Bearer '+TOKENS['gateway-b']}).status_code==403


class FakeWait:
    def __init__(self):self.now=0.;self.cancelled=False
    def is_set(self):return self.cancelled
    def wait(self,dt):self.now+=dt;return self.cancelled


@pytest.mark.parametrize('scenario',['success','cancel','failure'])
def test_reference_adapter_moves_then_reports_separate_terminal_sample(rig,scenario):
    b,e,_=rig;job=create(b);job['simulate_failure']=scenario=='failure'
    timer=FakeWait();observations=[]
    def publish(value):
        observations.append(value)
        if scenario=='cancel' and len(observations)==3:timer.cancelled=True
    result=ReferenceMobile(publish,clock=lambda:timer.now,wall=e.clock).execute(job,timer)
    assert result['sample']['halted'] is True
    assert result['sample']['sequence']>observations[-1]['sequence']
    assert result['sample']['sim_epoch']==observations[0]['sim_epoch']
    assert observations[0]['pose']==route(PARAMS['route_id']).poses[0]
    assert result['outcome']=={'success':'SUCCEEDED','cancel':'CANCELLED','failure':'FAILED'}[scenario]
    assert result['sample']['arrived']==(scenario=='success')
