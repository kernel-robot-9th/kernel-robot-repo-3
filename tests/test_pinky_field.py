"""Pinned route geometry; no ROS/motor execution."""
import json
import math

import pytest

from robot_gateway.hardware.pinky import atomic_json
from robots.pinky import compact
from robots.pinky.field_routes import command_route, plan


@pytest.fixture
def registry(tmp_path):
    path=tmp_path/'goals.json'
    atomic_json(path, {'robot_id':'pinky-1','frame_id':'map','map_sha256':'actual-map',
        'registration_confirmed':False,'goals':{'load-a':{
            'arrival':{'x':.8,'y':1.6,'yaw':math.pi},'exit':None,
            'arrival_route_id':'home_to_A','departure_route_id':None,
            'radius':.15,'xy_tolerance':.08,'yaw_tolerance':.25,
            'operator_alignment_required':True}}})
    return path


def command():
    return {'id':'abc','robot_id':'pinky-1','device_id':'pinky-1','mode':'hardware',
        'kind':'NAVIGATE','zone_id':'load-a','run_id':'run','task_id':'task','session_id':'session'}


def test_prepared_plan_keeps_reverse_sections_and_basket(registry):
    selected=plan(registry,'home_to_A')
    assert [s['direction'] for s in selected['segments']]==[0,-1,-1]
    assert selected['source_hash']==compact.bundle()[3]
    assert selected['footprint'][0][0]<-.23
    assert max(p[0] for p in selected['footprint'])>=.06
    assert selected['segments'][-1]['poses'][-1] == pytest.approx([.8,1.6,math.pi])
    assert not selected['registration_confirmed']


def test_route_contract_changes_when_operator_moves_A(registry):
    before=command_route(registry,command())
    data=json.loads(registry.read_text());data['goals']['load-a']['arrival']['x']+=.05
    atomic_json(registry,data)
    assert command_route(registry,command())['registration_sha256']!=before['registration_sha256']
