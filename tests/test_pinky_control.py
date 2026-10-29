import json
import math
from pathlib import Path
import threading
from unittest.mock import patch

from robots.pinky import compact
from robots.pinky.field_routes import network_plan, plan
from scripts.pinky_control import route_ids


def registry(tmp_path):
    goals = {}
    for zone, key, x, y, angle in [('load-a','A',.33,-.50,-1.51),
                                  ('load-b','B',.88,-.51,-1.61),
                                  ('handoff','handoff',1.62,-.48,-1.59)]:
        goals[zone] = {'arrival_route_id':'home_to_'+key, 'arrival':dict(x=x,y=y,yaw=angle)}
    shared = tmp_path/'shared.json'; shared.write_text(json.dumps({'goals': goals}))
    path = tmp_path/'goals.json'
    path.write_text(json.dumps(dict(robot_id='pinky-1', frame_id='map', map_sha256='test',
                                   layout_to_map=dict(x=0,y=0,yaw=0), goals=goals,
                                   shared_goals_file=str(shared))))
    return path


def test_shared_waits_and_taught_docks_have_continuous_routes(tmp_path):
    path = registry(tmp_path)
    routes = {key:network_plan(path,key) for key in compact.bundle()[1]}
    front = routes['queue_advance']['segments'][0]['poses'][-1]
    for key in ('home_to_A','home_to_B','home_to_handoff'):
        assert routes[key]['segments'][0]['poses'][0][:2] == front[:2]
    for route in routes.values():
        for a,b in zip(route['segments'],route['segments'][1:]):
            assert math.dist(a['poses'][-1][:2],b['poses'][0][:2]) < 1e-8
    for source,target in [('A','B'),('A','handoff'),('B','handoff')]:
        transfer = routes[source+'_to_'+target]['segments']
        assert transfer[0]['poses'][0] == routes['home_to_'+source]['segments'][-1]['poses'][-1]
        assert transfer[-1]['poses'][-1] == routes['home_to_'+target]['segments'][-1]['poses'][-1]
        tail = network_plan(path,source+'_exit_to_'+target)
        assert tail['segments'] == transfer[1:]


def test_departure_route_does_not_restart_at_home():
    assert route_ids('A_exit','B') == ['A_exit_to_B']
    assert route_ids('B_exit','C') == ['B_exit_to_handoff']
    assert route_ids('back','A') == ['queue_advance','home_to_A']
    assert route_ids('back','front') == ['queue_advance']
    assert route_ids('C','back') == ['handoff_to_home_back']


def test_home_departures_do_not_approach_the_occupied_back_wait(tmp_path):
    path = registry(tmp_path)
    queue = network_plan(path, 'queue_advance')['segments'][0]['poses']
    back, front = queue[0][:2], queue[-1][:2]
    separation = math.dist(back, front)
    for zone in ('A', 'B', 'handoff'):
        route = network_plan(path, 'home_to_'+zone)
        departure = route['segments'][1]['poses']
        assert min(math.dist(p[:2], back) for p in departure) >= separation-1e-8


def test_home_curve_flows_into_dock_without_intermediate_arrival(tmp_path):
    path = registry(tmp_path)
    for zone in ('A', 'B', 'handoff'):
        route = network_plan(path, 'home_to_'+zone)
        moving = [s for s in route['segments'] if s['direction']]
        dock = plan(path, 'home_to_'+zone)['segments'][-1]['poses']
        assert len(moving) == 1
        assert moving[0]['direction'] == -1
        assert moving[0]['poses'][-len(dock):] == dock


def test_return_keeps_back_robot_and_reverse_parks_front(tmp_path):
    from robot_gateway.hardware.control_fleet import ControlFleet
    path = tmp_path/'state.json'; path.write_text(json.dumps({'P1':'C','P2':'back'}))
    fleet = ControlFleet.__new__(ControlFleet); fleet.state_path = path
    calls = []
    def execute(self, command, cancelled):
        calls.append((command['robot_id'], command['route_id'])); return {'nav2_completed':True}
    with patch('robot_gateway.hardware.pinky.PinkyFleet.execute', execute):
        result = fleet.execute({'kind':'LEAVE','robot_id':'pinky-1','device_id':'pinky-1',
                                'zone_id':'handoff'},threading.Event())
    assert calls == [('pinky-1','handoff_to_home_front')]
    assert json.loads(path.read_text()) == {'P1':'front','P2':'back'}
    assert result['location'] == 'front'


def test_c_station_uses_ros_python_for_parking_and_il_python_for_arm():
    from robot_gateway.hardware.station_remote import station_command
    config = {'ssh_key':'~/.ssh/example','stations':{'C':{'host':'c@example','root':'/repo',
              'python':'/il/python','parking_python':'/camera/python'}}}
    assert '/camera/python' in station_command(config,'C',{'operation':'parking'})[-1]
    assert '/il/python' in station_command(config,'C',{'operation':'arm'})[-1]


def test_direct_control_hands_observation_arrival_to_parking(tmp_path):
    from scripts.pinky_control import main
    state = tmp_path/'state.json'; state.write_text('{"P1":"front","P2":"back"}')
    with patch('sys.argv', ['pinky_control', 'both', '--robot','P1','--zone','A','--parking']), \
         patch('scripts.pinky_control.configuration', return_value={'state_file':str(state)}), \
         patch('scripts.pinky_control.navigate', return_value={'parking_start':'observe'}) as navigate, \
         patch('scripts.pinky_control.run_station', return_value={'status':'aligned'}) as station:
        main()
    assert navigate.call_args.args[3]['zone_id'] == 'load-a'
    assert station.call_args_list[0].args[1]['options']['start_at_observation'] is True


def test_order_control_hands_observation_arrival_to_parking(tmp_path):
    from robot_gateway.hardware.control_fleet import ControlFleet
    state = tmp_path/'state.json'; state.write_text('{"P1":"front","P2":"back"}')
    fleet = ControlFleet.__new__(ControlFleet); fleet.state_path = state
    with patch('robot_gateway.hardware.pinky.PinkyFleet.execute', return_value={'parking_start':'observe'}), \
         patch('robot_gateway.hardware.control_fleet.run_station', return_value={'status':'aligned'}) as station:
        fleet.execute({'kind':'NAVIGATE','robot_id':'pinky-1','zone_id':'load-a'}, threading.Event())
    assert station.call_args.args[1]['options']['start_at_observation'] is True
