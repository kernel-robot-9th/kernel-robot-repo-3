import json
import math
import threading
from unittest.mock import patch

import pytest

from robot_gateway.hardware.wait_parking import load_config, relative, waiting_route
from robot_gateway.hardware.wait_maneuvers import PathController, entry, envelope, queue_segment, return_routes
from scripts.pinky_wait_preview import report


def targets():
    result={'targets':{},'layout_to_map':dict(x=0.,y=0.,yaw=0.)}
    for robot in ('P1','P2'):
        yaw=math.atan2(.03,.47)
        for slot,x,y in [('back',.5,-1.34),('front',.97,-1.31)]:
            result['targets'][slot+'/'+robot]={'map_pose':dict(x=x,y=y,yaw=yaw)}
    return result


@pytest.mark.parametrize('other,destination,routes',[
    ('C','front',['handoff_to_home_back','queue_advance']),
    ('front','back',['handoff_to_home_back']),
    ('back','front',['handoff_to_home_front']),
])
def test_return_occupancy_selects_rear_first_or_front_reverse(other,destination,routes):
    assert return_routes(other)==(destination,routes)


@pytest.mark.parametrize('slot',['back','front','advance'])
@pytest.mark.parametrize('error',[-1.,0.,1.])
def test_fixed_path_tracks_with_initial_position_heading_error_without_wall_spin(slot,error):
    cfg=load_config();t=targets()['targets']
    if slot=='advance':
        segments=[queue_segment(t['back/P1']['map_pose'],t['front/P1']['map_pose'])]
        pose=dict(t['back/P1']['map_pose'])
    else:
        pose,segments=entry(t[slot+'/P1']['map_pose'],slot,cfg)
    pose=dict(pose,x=pose['x']+.015*error,y=pose['y']+.015*error,yaw=pose['yaw']+.08*error)
    control=PathController(segments,cfg)
    for _ in range(10000):
        state=control.step(pose)
        if state['phase'] in ('aligned','advanced'):break
        if abs(state['linear'])<1e-9 and abs(state['angular'])>1e-9:
            assert state['phase']=='waiting_open_turn'
        # Include tracking error, not just the ideal path's sampled footprints.
        assert all(0.<x<2. and -1.5<y<0. for x,y in envelope(pose,cfg))
        pose['x']+=state['linear']*math.cos(pose['yaw'])*.05
        pose['y']+=state['linear']*math.sin(pose['yaw'])*.05
        pose['yaw']+=state['angular']*.05
    assert state['phase']==('advanced' if slot=='advance' else 'aligned'),state
    if slot!='advance':
        assert state['distance_m']<=.03
        assert abs(state['yaw_error'])<=math.radians(7)


def test_real_basket_sweep_including_open_turn_avoids_wall_and_occupied_neighbour():
    rows=report(targets(),load_config())
    assert len(rows)==6
    for row in rows:
        assert row['minimum_model_wall_gap_m']>.04,row
        assert row['maximum_other_robot_overlap_m2']==0.,row


def test_queue_is_one_forward_straight_and_has_no_final_precision_park():
    d=targets();plan=waiting_route({'route_id':'queue_advance','segments':[]},'P1',d)
    assert len(plan['segments'])==1
    segment=plan['segments'][0]
    assert segment['advance_only'] and segment['direction']==1 and segment['camera_guided']
    assert len({round(p[2],8) for p in segment['poses']})==1


@pytest.mark.parametrize('resume_curve',[False,True])
def test_recorded_p2_entry_error_and_curve_end_do_not_orbit(resume_curve):
    # 2026-10-28 / 1793157193818044558-P2-back: 11.55cm handoff error,
    # then 1.7cm / 24-degree curve-end error. These are measured map poses.
    cfg=load_config()
    goal=dict(x=-.02018244005739689,y=1.3825165033340454,yaw=-1.4697890940438791)
    stage,segments=entry(goal,'back',cfg)
    pose=(dict(x=-.044705348391321356,y=1.4909952759441971,yaw=-1.0543620699593632)
          if resume_curve else dict(x=.2928244771555701,y=1.489277845960731,yaw=1.1952653853627042))
    layout=dict(x=1.3109359527158224,y=1.925124302621229,yaw=-1.540963519299225)
    controller=PathController(segments,cfg);controller.index=int(resume_curve)
    phases=[]
    for _ in range(2000):
        state=controller.step(pose)
        if not phases or phases[-1]!=state['phase']:
            phases.append(state['phase'])
            if state['phase']=='waiting_open_turn':
                assert math.hypot(*relative(stage,pose)[:2])<=.03
            if state['phase']=='waiting_back_curve':
                assert abs(relative(stage,pose)[2])<=math.radians(7)
        if not resume_curve:
            local=dict(zip(('x','y','yaw'),relative(pose,layout)))
            assert all(0.<x<2. and -1.5<y<0. for x,y in envelope(local,cfg))
        if state['phase']=='aligned':break
        if state['phase'] in ('waiting_back_curve','waiting_back_straight'):
            assert state['linear']>0.  # No intermediate stop/spin for endpoint yaw.
        pose['x']+=state['linear']*math.cos(pose['yaw'])*.05
        pose['y']+=state['linear']*math.sin(pose['yaw'])*.05
        pose['yaw']+=state['angular']*.05
    assert phases==(['waiting_back_straight','aligned'] if resume_curve else
                    ['waiting_entry_position','waiting_open_turn','waiting_back_curve',
                     'waiting_back_straight','aligned'])
    assert state['distance_m']<=.03
    assert abs(state['yaw_error'])<=math.radians(7)


def test_empty_queue_returns_via_back_and_preserves_back_arrival_if_advance_fails(tmp_path):
    from robot_gateway.hardware.control_fleet import ControlFleet
    path=tmp_path/'state.json';path.write_text(json.dumps({'P1':'C','P2':'A'}))
    fleet=ControlFleet.__new__(ControlFleet);fleet.state_path=path
    calls=[]
    def execute(self,command,cancelled):
        calls.append((command['robot_id'],command['route_id']))
        if command['route_id']=='queue_advance':raise RuntimeError('advance failed')
        return {'nav2_completed':True}
    with patch('robot_gateway.hardware.pinky.PinkyFleet.execute',execute):
        with pytest.raises(RuntimeError,match='advance failed'):
            fleet.execute(dict(kind='LEAVE',robot_id='pinky-1',zone_id='handoff'),threading.Event())
    assert calls==[('pinky-1','handoff_to_home_back'),('pinky-1','queue_advance')]
    assert json.loads(path.read_text())=={'P1':'back','P2':'A'}
