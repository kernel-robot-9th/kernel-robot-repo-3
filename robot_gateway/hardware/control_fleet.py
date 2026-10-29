"""Central execution of the existing two-position queue and station routes."""
import fcntl
import json
from pathlib import Path

from .pinky import PinkyFleet, atomic_json
from .station_remote import configuration, run_station
from .wait_maneuvers import return_routes
from scripts.pinky_control import route_ids


class ControlFleet(PinkyFleet):
    def __init__(self, config, evidence):
        super().__init__(config['mobile_profiles'], evidence)
        self.control = configuration()
        self.state_path = Path(self.control['state_file'])

    def state(self, update=None):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {'P1':'front','P2':'back'}
            if update:
                state.update(update)
                atomic_json(self.state_path, state)
            return state

    def execute(self, command, cancelled):
        if command['kind'] not in ('NAVIGATE', 'LEAVE'):
            return super().execute(command, cancelled)
        robot = 'P'+command['robot_id'][-1]
        other = 'P2' if robot == 'P1' else 'P1'
        zone = {'load-a':'A','load-b':'B','handoff':'C'}[command['zone_id']]
        while True:
            state = self.state()
            occupied = state[other] == 'front' or state[other].startswith('departing:')
            if command['kind'] != 'NAVIGATE' or state[robot] != 'back' or not occupied:
                break
            if cancelled.wait(.1):
                raise RuntimeError('대기열 이동 취소')
        if command['kind'] == 'LEAVE':
            destination, routes = (zone+'_exit', ['exit_'+zone]) if zone in ('A','B') else return_routes(state[other])
        else:
            destination, routes = zone, route_ids(state[robot], zone)
        def segment_done(name):
            if name == 'home_depart':
                self.state({robot:'enroute:'+destination})
                print(robot+' 전열 출차 구간 통과 → 후열 이동 허용', flush=True)
        results = []
        for route in routes:
            if route.startswith('home_to_'):
                self.state({robot:'departing:'+destination})
            data = dict(command, route_id=route, device_id=command['robot_id'])
            results.append(super().execute(data, cancelled, segment_done=segment_done))
            location = ('front' if route == 'queue_advance' else
                route.removeprefix('handoff_to_home_') if route.startswith('handoff_to_home_') else destination)
            self.state({robot:location})
        self.state({robot:destination})
        result = {'routes': results, 'location': destination, 'nav2_completed': True}
        if command['kind'] == 'NAVIGATE' and not command.get('handoff_arrival_only'):
            result['parking'] = run_station(zone, {'operation':'parking','mode':'align',
                'robot':robot,'zone':zone, 'options':{'start_at_observation':
                    bool(results and results[-1].get('parking_start') == 'observe')}}, cancelled=cancelled,
                                            frames=getattr(self, 'frames', None))
            if result['parking'].get('status') not in ('aligned','operator_confirmed'):
                raise RuntimeError('영상 주차 종료: '+str(result['parking'].get('status')))
        return result


def create_mobile(config, evidence):
    return ControlFleet(config, evidence)
