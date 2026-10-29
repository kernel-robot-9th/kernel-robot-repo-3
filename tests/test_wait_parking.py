import json
import math
from copy import deepcopy

import pytest

from robot_gateway.hardware.wait_parking import (
    load_config, footprint, relative, transfer_goal, waiting_route)
from robots.pinky.route_graph import build_graph


def test_basket_scale_preserves_body_and_uses_requested_dimensions():
    c=load_config();p=footprint(c);d=c['dimensions']
    assert max(v[0] for v in p)==d['body_front_m']
    assert max(v[1] for v in p)==d['body_width_m']/2
    assert min(v[0] for v in p)==pytest.approx(d['basket_mount_x_m']-.1085)
    assert p[4][1]*2==pytest.approx(.0889)
    assert min(v[0] for v in footprint(c,1))==pytest.approx(d['basket_mount_x_m']-.155)


def test_camera_and_odom_frame_offset_does_not_change_parking_error():
    goal=dict(x=1.,y=2.,yaw=.7);camera=dict(x=.9,y=2.1,yaw=-.4)
    odom=dict(x=-3.,y=.2,yaw=2.)
    assert relative(transfer_goal(goal,camera,odom),odom)==pytest.approx(relative(goal,camera))



def test_return_registers_open_turn_curve_and_straight_without_changing_stations():
    prepared={'targets':{'back/P1':{'map_pose':dict(x=.5,y=-1.34,yaw=0.)}}}
    original={'route_id':'handoff_to_home_back','frame_id':'map','registration_sha256':'test','segments':[
        {'name':'return_west','direction':1,'poses':[[1.6-i*.01,-1.1,math.pi] for i in range(130)]},
        {'name':'home_return_turn','direction':1,'poses':[[.31,-1.1,math.pi],[.5,-1.4,0.]]}]}
    before=deepcopy(original);plan=waiting_route(original,'P1',prepared)
    assert original==before
    camera=[s for s in plan['segments'] if s.get('camera_guided')]
    assert [s['direction'] for s in camera]==[0,1,1]
    assert camera[-1]['straight'] is True
    assert camera[-1]['poses'][-1]==[.5,-1.34,0.]
    _,index=build_graph([plan]);route=index['routes'][plan['route_id']]
    assert route['waiting_slot']=='back'
    assert route['segments'][-1]['camera_guided']
    original['route_id']='A_to_B'
    assert waiting_route(original,'P1',prepared)==original
