"""HTTP stop/failure/disconnect contracts for v4. MOCK ONLY."""
from datetime import datetime, timezone
import json
import time
import uuid

from demo_distributed import free_port
from preview import PreviewGroup
from prepare_distributed import ROOT
from robot_gateway.mock import Client


def run():
    root=ROOT/'runtime'/'verification'/('v4-faults-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    checks=[]; report={'status':'RUNNING','physical_hardware_verified':False,'route_version':4,'checks':checks}
    try:
        for scenario in ('stop','failure','disconnect'):
            with PreviewGroup(root/scenario,free_port(),auto=True,reference=True) as group:
                admin=Client(group.base,group.credentials['admin']); anon=Client(group.base,'')
                if scenario=='failure': admin.call('/api/admin/road/failure',{})
                s=anon.call('/api/sessions',{'label':scenario}); customer=Client(group.base,s['token'])
                customer.call('/api/customer/orders',{'items':[{'sku':'SKU-RICE-CHIP','quantity':1}],'request_id':str(uuid.uuid4())})
                deadline=time.monotonic()+25; triggered=False; job=None
                while time.monotonic()<deadline:
                    road=admin.call('/api/admin/road'); job=road['jobs'].get(road['active'])
                    if job and job['status']=='RUNNING' and job['telemetry'] and not triggered:
                        triggered=True
                        if scenario=='stop': admin.call('/api/admin/road/stop',{})
                        if scenario=='disconnect':
                            group.children['gateway-a'].terminate();group.children['gateway-a'].wait(timeout=5)
                    if road['blocked'] and job and (scenario=='disconnect' or job['stopped']): break
                    time.sleep(.1)
                else: raise AssertionError(scenario+' timeout')
                state=admin.call('/api/admin/state')
                assert job and road['active']==job['id']
                assert state['zones']['load-b']['owner'] and state['sessions'][s['session_id']]['error']
                assert not state['sessions'][s['session_id']]['inventory']
                assert state['stock']['SKU-RICE-CHIP']=={'on_hand':8,'reserved':1}
                if scenario=='stop': assert job['stop_ack_at'] is not None and job['stopped']
                if scenario=='disconnect': assert not job['stopped'] and job['status']=='UNCERTAIN'
                if scenario=='failure': assert job['status']=='FAILED' and not job['telemetry']['arrived']
                checks.append({'scenario':scenario,'status':'PASS','job':job,'zone_retained':True})
        report['status']='PASS'
    except Exception as exc:
        report.update(status='FAIL',error=str(exc));raise
    finally:
        root.mkdir(parents=True,exist_ok=True);path=root/'verification.json'
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'status':report['status'],'report':str(path)},ensure_ascii=False))


if __name__=='__main__': run()
