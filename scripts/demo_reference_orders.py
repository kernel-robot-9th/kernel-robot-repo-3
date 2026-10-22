"""Real HTTP/processes, virtual robots/arms only. Never opens a device."""
from datetime import datetime, timezone
import json
import time
import uuid

from demo_distributed import free_port
from preview import PreviewGroup
from prepare_distributed import ROOT
from robot_gateway.mock import Client


def run():
    directory=ROOT/'runtime'/'verification'/('v4-orders-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    report={'status':'RUNNING','route_version':4,'physical_hardware_verified':False,'checks':[]}
    try:
        with PreviewGroup(directory,free_port(),auto=True,reference=True) as group:
            admin=Client(group.base,group.credentials['admin']); anonymous=Client(group.base,'')
            products=anonymous.call('/api/products')['items']
            a=next(p['sku'] for p in products if p['station']=='load-a')
            customers=[]
            for name,items in [('A',[{'sku':a,'quantity':1},{'sku':'SKU-RICE-CHIP','quantity':1}]),
                               ('B',[{'sku':'SKU-RICE-CHIP','quantity':6}])]:
                s=anonymous.call('/api/sessions',{'label':'HTTP '+name})
                client=Client(group.base,s['token']); customers.append(s)
                client.call('/api/customer/orders',{'items':items,'request_id':str(uuid.uuid4())})
                client.call('/api/customer/checkout',{})
            deadline=time.monotonic()+240; basket_tasks=set(); saw_parallel=False
            while time.monotonic()<deadline:
                state=admin.call('/api/admin/state'); road=admin.call('/api/admin/road')
                assert not road['blocked'],road['blocked']
                assert not any(s['error'] for s in state['sessions'].values())
                active=road['jobs'].get(road['active'])
                if active:
                    saw_parallel |= any(t['state']=='ARM_WORK' and t['robot_id']!=active['robot_id'] for t in state['tasks'].values())
                for s in state['sessions'].values():
                    t=state['tasks'].get(s['current_task'])
                    if t and t['state']=='WAIT_BASKET' and t['id'] not in basket_tasks:
                        # Explicit test-harness observation, not automatic field basket readiness.
                        admin.call('/api/admin/basket-ready',dict(session_id=s['id'],task_id=t['id'],basket_id=s['basket_id']))
                        basket_tasks.add(t['id'])
                if all(s['state']=='COMPLETED' and not s['current_task'] for s in state['sessions'].values()) and not road['active']:
                    break
                time.sleep(.2)
            else: raise AssertionError('v4 HTTP timeout; inspect owned server/gateway logs')
            assert len(state['trips'])==3 and len(state['units'])==8
            assert all(u['state']=='DELIVERED' for u in state['units'].values())
            assert all(z['owner'] is None for z in state['zones'].values())
            routes=[j['parameters']['route_id'] for j in road['jobs'].values()]
            assert 'A_to_B' in routes and routes.count('B_to_handoff')==3
            assert state['stock']['SKU-RICE-CHIP']=={'on_hand':1,'reserved':0}
            report.update(status='PASS',checks=['two_customers_separate_robots','eight_confirmed_items','six_item_order_two_trips',
                'direct_A_to_B','handoff_stop_and_clear_before_return','all_zones_released_after_home'],
                parallel_arm_observed=saw_parallel,source_hash=road['source_hash'],state=state,road=road)
    except Exception as exc:
        report.update(status='FAIL',error=str(exc)); raise
    finally:
        directory.mkdir(parents=True,exist_ok=True)
        report['at']=datetime.now(timezone.utc).isoformat()
        path=directory/'verification.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'status':report['status'],'report':str(path)},ensure_ascii=False))


if __name__=='__main__': run()
