"""One offline demo flow. No ROS, camera, motor or operator wait."""
import threading

from fastapi.testclient import TestClient

from robot_gateway.hardware.field_status import FieldStatus
from robot_gateway.hardware.worker import Executor
from robot_gateway.mock import make_event
from server.api import create_app
from server.distributed import DistributedEngine


def test_demo_runs_without_time_pose_or_operator_gates(monkeypatch):
    now = [1000.]
    engine = DistributedEngine(mode='hardware',clock=lambda:now[0],readiness={'approved':True,'preferred_robot':'pinky-2'})
    identity = {'node_id':'gateway-a','instance_id':'offline-demo-a','mode':'hardware'}
    node_token,admin_token = 'offline-node-token-a','offline-admin-token'
    tokens = {node: node_token+node for node in ['gateway-a','gateway-b','gateway-c']}
    auth = {'Authorization':'Bearer '+tokens['gateway-a']}
    operator = {'Authorization':'Bearer '+admin_token}
    status = FieldStatus()
    executor = Executor.__new__(Executor)
    executor.config = {'parking':{'zones':['A'],'config':'unused'}}
    executor.status,executor.frames,executor.camera_lock = status,None,threading.Lock()
    class Mobile:
        def execute(self, command, cancelled):
            return {'nav2_completed':True,'pose':{'x':999,'y':999,'yaw':2.8}}
    class Arm:
        def execute(self, command, cancelled):
            return {'executed_items':command['items'],'physical_loading_confirmed':False}
    executor.mobile,executor.arm = Mobile(),Arm()
    parking_calls = []
    def parking(*args,**kwargs):
        parking_calls.append(args)
        return {'status':'aligned','physical_parking_confirmed':False}
    monkeypatch.setattr('scripts.pinky_parking.run_parking',parking)
    try:
        with TestClient(create_app(engine,admin_token,node_tokens=tokens)) as client:
            assert client.post('/api/nodes/heartbeat',headers=auth,json=identity).status_code == 200
            session = engine.create_session('P2 demo')['session_id']
            engine.submit_order(session,[{'sku':'SKU-JIN-RAMEN','quantity':1}],'offline-demo-order')
            kinds=[];pick=None
            while engine.state['sessions'][session]['current_task'] or not kinds:
                command = engine.node_claim(identity['node_id'],identity['instance_id'])
                assert command is not None
                assert command['robot_id']=='pinky-2'
                kinds.append(command['kind'])
                if command['kind']=='PICK': pick=command
                engine.node_event(identity['node_id'],identity['instance_id'],make_event(command,'ACCEPTED'))
                now[0]+=10000  # Exceeds all former timeouts; no fresh heartbeat or pose.
                event=executor.execute(command,threading.Event())
                engine.node_event(identity['node_id'],identity['instance_id'],event)
                if command['kind']=='NAVIGATE':
                    assert engine.state['tasks'][command['task_id']]['state']=='ARM_WORK'
                if command['kind']=='PICK':
                    assert engine.state['tasks'][command['task_id']]['state']=='LEAVING'
                assert len(kinds)<=3
            assert kinds==['NAVIGATE','PICK','LEAVE']
            assert parking_calls[0][1:3]==('P2','A')
            state=engine.state['sessions'][session]
            assert state['error'] is None and state['current_task'] is None
            assert engine.state['zones']['load-a']['owner'] is None
            assert state['inventory'][0]['physical_loading_confirmed'] is False
            # Optional confirmation works after the task, without a waiting stage.
            response=client.post('/api/admin/field/commands/'+pick['id']+'/observe',headers=operator,json={'observation':'pick-0'})
            assert response.status_code==200,response.text
            assert state['inventory'][0]['physical_loading_confirmed'] is True
            assert client.post('/api/admin/field/commands/'+pick['id']+'/observe',json={'observation':'pick-0'}).status_code==401
    finally:
        engine.store.close()
