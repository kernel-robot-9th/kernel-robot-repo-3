import json
import math
from copy import deepcopy
from unittest.mock import patch

import pytest

from robots.pinky.route_graph import build_graph, return_from_current, return_join_segments


def route():
    plan = {'route_id':'return', 'frame_id':'map', 'registration_sha256':'test', 'segments':[
        {'name':'leave_C', 'direction':1, 'poses':[[1.6, -.4-i*.01, -math.pi/2] for i in range(71)]},
        {'name':'face_west', 'direction':0, 'poses':[[1.6,-1.1,-math.pi/2],[1.6,-1.1,math.pi]]},
        {'name':'return_west', 'direction':1, 'poses':[[1.6-i*.01,-1.1,math.pi] for i in range(111)]},
        {'name':'wait_turn', 'direction':1, 'poses':[[.5,-1.1,math.pi],[.4,-1.2,-math.pi/2],[.5,-1.35,0.]]},
        {'name':'queue_advance', 'direction':1, 'poses':[[.5+i*.01,-1.35,0.] for i in range(35)]}]}
    graph, index = build_graph([plan])
    return graph, index['routes']['return']


def test_mid_lane_joins_directed_suffix_using_existing_node_ids():
    graph, original = route(); before = deepcopy(original)
    current = dict(x=1., y=-1.17, yaw=2.8)
    trimmed = return_from_current(original, current)
    assert trimmed['segments'][0]['name'] == 'return_west'
    first = trimmed['segments'][0]
    nodes = {f['properties']['id']: f['geometry']['coordinates'] for f in graph['features']
             if f['geometry']['type'] == 'Point'}
    assert nodes[first['start_id']] == first['poses'][0][:2]
    assert first['start_id'] < first['goal_id']
    planned = [[current['x'],current['y'],current['yaw']], [1.04,-1.17,2.8], [1.04,-1.24,2.9]]
    targets = []
    def planner(target):
        targets.append(target)
        return planned+[target]
    joined = return_join_segments(trimmed['segments'], planner)
    assert joined[0]['name'] == 'return_west'
    assert not any(s['name'] == 'face_return_join' for s in joined)
    assert targets[0] in first['poses']
    assert joined[0]['poses'][:len(planned)] == planned
    assert joined[0]['poses'][-10:] == first['poses'][-10:]
    assert joined[1:len(trimmed['segments'])] == trimmed['segments'][1:]
    assert joined[-1] == {'name':'waiting_heading', 'direction':0,
                          'poses':[original['segments'][-1]['poses'][-1]]}
    assert original == before


def test_planner_failure_has_no_unplanned_return_fallback():
    _, original = route()
    before = deepcopy(original)
    def planner(target):
        raise RuntimeError('no collision-free connection')
    with pytest.raises(RuntimeError, match='no collision-free connection'):
        return_join_segments(original['segments'], planner)
    assert original == before


def test_c_pose_still_leaves_c_and_back_target_keeps_back_endpoint():
    _, original = route()
    original['segments'] = original['segments'][:-1]
    trimmed = return_from_current(original, dict(x=1.59,y=-.41,yaw=-1.47))
    assert trimmed['segments'][0]['name'] == 'leave_C'
    assert trimmed['segments'][-1]['poses'][-1] == [.5,-1.35,0.]


@pytest.mark.parametrize('source', ['A', 'B'])
def test_wait_cli_leaves_station_before_return_and_never_calls_arm(tmp_path, source):
    from scripts.pinky_control import main
    state = tmp_path/'state.json'; state.write_text(json.dumps({'P1':source,'P2':'A'}))
    with patch('sys.argv',['pinky_control','wait','--robot','P1','--zone','front']), \
         patch('scripts.pinky_control.configuration', return_value={'state_file':str(state)}), \
         patch('scripts.pinky_control.navigate', return_value={'nav2_completed':True}) as navigate, \
         patch('scripts.pinky_control.run_station') as station:
        main()
    assert [c.args[2] for c in navigate.call_args_list] == ['exit_'+source,'handoff_to_home_back','queue_advance']
    assert 'join_return_from_current' not in navigate.call_args_list[0].args[3]
    assert navigate.call_args_list[1].args[3]['join_return_from_current'] is True
    assert 'join_return_from_current' not in navigate.call_args_list[2].args[3]
    assert json.loads(state.read_text()) == {'P1':'front','P2':'A'}
    station.assert_not_called()


def test_wait_retry_after_exit_does_not_repeat_station_exit(tmp_path):
    from scripts.pinky_control import main
    state = tmp_path/'state.json'; state.write_text('{"P1":"A","P2":"back"}')
    with patch('sys.argv',['pinky_control','wait','--robot','P1','--zone','front','--route-version','3']), \
         patch('scripts.pinky_control.configuration', return_value={'state_file':str(state)}), \
         patch('scripts.pinky_control.navigate', side_effect=[{}, RuntimeError('return failed')]) as navigate:
        with pytest.raises(RuntimeError, match='return failed'):
            main()
        assert json.loads(state.read_text())['P1'] == 'A_exit'
        assert [c.args[2] for c in navigate.call_args_list] == ['exit_A','handoff_to_home_front']
        navigate.reset_mock(side_effect=True); navigate.return_value = {}
        main()
        assert [c.args[2] for c in navigate.call_args_list] == ['handoff_to_home_front']
        assert navigate.call_args.args[3]['route_version'] == 3


def test_failed_return_does_not_mark_waiting_slot_arrived(tmp_path):
    from scripts.pinky_control import main
    state = tmp_path/'state.json'; state.write_text('{"P1":"A","P2":"C"}')
    with patch('sys.argv',['pinky_control','wait','--robot','P2','--zone','back']), \
         patch('scripts.pinky_control.configuration', return_value={'state_file':str(state)}), \
         patch('scripts.pinky_control.navigate', side_effect=RuntimeError('Nav2 failure')):
        with pytest.raises(RuntimeError):
            main()
    assert json.loads(state.read_text())['P2'] == 'C'
