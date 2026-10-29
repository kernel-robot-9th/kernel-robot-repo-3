"""Central execution of the existing two-position queue and station routes."""
import fcntl
import json
from pathlib import Path
import time

from .pinky import PinkyFleet, atomic_json
from .station_remote import configuration, run_station
from .wait_maneuvers import return_routes
from scripts.pinky_control import route_ids


class ControlFleet(PinkyFleet):
    def __init__(self, config, evidence):
        super().__init__(config['mobile_profiles'], evidence)
        self.control = configuration()
        self.state_path = Path(self.control['state_file'])

    def execute(self, command, cancelled):
        if command['kind'] not in ('NAVIGATE', 'LEAVE'):
            return super().execute(command, cancelled)
        robot = 'P'+command['robot_id'][-1]
        other = 'P2' if robot == 'P1' else 'P1'
        zone = {'load-a':'A','load-b':'B','handoff':'C'}[command['zone_id']]
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.with_suffix('.lock').open('a') as lock:
            while True:
                fcntl.flock(lock, fcntl.LOCK_EX)
                state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {'P1':'front','P2':'back'}
                if state[robot] != 'back' or state[other] != 'front' or command['kind'] != 'NAVIGATE':
                    break
                fcntl.flock(lock, fcntl.LOCK_UN)
                if cancelled.wait(.2):
                    raise RuntimeError('대기열 이동 취소')
            def travel(who, route):
                data = dict(command, robot_id='pinky-'+who[-1], device_id='pinky-'+who[-1], route_id=route)
                return super(ControlFleet, self).execute(data, cancelled)
            if command['kind'] == 'LEAVE':
                if zone in ('A','B'):
                    destination, routes = zone+'_exit', ['exit_'+zone]
                else:
                    destination, routes = return_routes(state[other])
            else:
                destination = zone
                routes = route_ids(state[robot], zone)
            results = []
            for route in routes:
                results.append(travel(robot,route))
                state[robot] = ('front' if route == 'queue_advance' else
                    route.removeprefix('handoff_to_home_') if route.startswith('handoff_to_home_') else destination)
                atomic_json(self.state_path,state)
            state[robot] = destination
            atomic_json(self.state_path, state)
            result = {'routes': results, 'location': destination, 'nav2_completed': True}
            if command['kind'] == 'NAVIGATE':
                result['parking'] = run_station(zone, {'operation':'parking','mode':'align',
                    'robot':robot,'zone':zone, 'options':{'start_at_observation':
                        bool(results and results[-1].get('parking_start') == 'observe')}}, cancelled=cancelled,
                                                frames=getattr(self, 'frames', None))
                if result['parking'].get('status') not in ('aligned','operator_confirmed'):
                    raise RuntimeError('영상 주차 종료: '+str(result['parking'].get('status')))
            return result


def create_mobile(config, evidence):
    return ControlFleet(config, evidence)
