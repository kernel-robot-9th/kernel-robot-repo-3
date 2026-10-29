import json
from pathlib import Path

from fastapi.testclient import TestClient
from server.api import create_app
from server.distributed import DistributedEngine
from robots.pinky.field_routes import version_plan
from robots.pinky.route_graph import build_graph
from tests.test_api import ADMIN, bearer


def test_selected_route_only_changes_new_sessions_and_persists(tmp_path):
    db=str(tmp_path/'mode.db');e=DistributedEngine(db)
    old=e.create_session('기존 고객')['session_id']
    e.select_field_route(3)
    new=e.create_session('다음 고객')['session_id']
    assert e.state['sessions'][old]['route_version']==4
    assert e.state['sessions'][new]['route_version']==3
    for sid,version in [(old,4),(new,3)]:
        task=e._task(e._session(sid),'LOAD','load-a',[])
        cmd=e._command(task,'NAVIGATE',e._session(sid)['robot_id'])
        assert cmd['route_version']==version
    e.store.close()
    reopened=DistributedEngine(db)
    assert reopened.state['field_route_version']==3
    reopened.store.close()


def test_admin_selection_and_preview_never_issue_commands():
    e=DistributedEngine();tokens={n:'test-node-token-'+n for n in e.profiles}
    with TestClient(create_app(e,ADMIN,node_tokens=tokens)) as client:
        assert client.post('/api/admin/field/routes',json={'version':3}).status_code==401
        assert client.post('/api/admin/field/routes',headers=bearer(ADMIN),json={'version':5}).status_code==422
        assert client.post('/api/admin/field/routes',headers=bearer(ADMIN),json={'version':3}).status_code==200
        result=client.get('/api/admin/field/routes',headers=bearer(ADMIN)).json()
        assert result['selected']==3
        assert [r['version'] for r in result['options']]==[3,4]
        assert all(o['routes']['home_to_A'] for o in result['options'])
        assert e.state['commands']=={}
    e.store.close()


def test_two_road_geometries_share_taught_station_and_have_disjoint_node_ids(tmp_path):
    from tests.test_pinky_control import registry
    goals=registry(tmp_path)
    a=version_plan(goals,'A_to_B',3);b=version_plan(goals,'A_to_B',4)
    assert a['segments'][-1]['poses'][-1]==b['segments'][-1]['poses'][-1]
    assert len(a['segments'])!=len(b['segments'])
    a['route_id']='v3/A_to_B';b['route_id']='v4/A_to_B'
    _,index=build_graph([a,b])
    ids=[]
    for name in ['v3/A_to_B','v4/A_to_B']:
        ids.append({i for s in index['routes'][name]['segments'] if s['direction']
                    for i in range(s['start_id'],s['goal_id']+1)})
    assert ids[0].isdisjoint(ids[1])
