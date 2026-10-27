"""Central terminal: navigation here, camera and arm execution at each station."""
import argparse
import fcntl
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid

from robot_gateway.hardware.pinky import PinkyMobile, load_profile, atomic_json
from robot_gateway.hardware.station_remote import configuration, run_station, ssh

ZONES = {'A': 'load-a', 'B': 'load-b', 'C': 'handoff'}


def route_ids(source, destination):
    target = 'handoff' if destination == 'C' else destination
    if source == destination:
        return []
    if source == 'back' and destination == 'front':
        return ['queue_advance']
    if destination in ('front', 'back'):
        return ([] if source == 'C' else route_ids(source, 'C')) + ['handoff_to_home_'+destination]
    if source == 'back':
        return ['queue_advance', 'home_to_'+target]
    if source == 'front':
        return ['home_to_'+target]
    if source in ('A', 'A_exit') and destination in ('B', 'C') or source in ('B', 'B_exit') and destination == 'C':
        return [source+'_to_'+target]
    # Backward station visits use the existing return lane, not a new shortcut.
    return route_ids(source, 'front') + ['home_to_'+target]


def command_for(robot, zone):
    uid = lambda: str(uuid.uuid4())
    return dict(id=uid(), run_id=uid(), task_id=uid(), session_id=uid(), robot_id='pinky-'+robot[-1],
                device_id='pinky-'+robot[-1], kind='NAVIGATE', mode='hardware',
                zone_id=ZONES.get(zone, 'handoff'), items=[], created_at=time.time(), scope='device_test')


def navigate(config, robot, route, command=None):
    command = dict(command or command_for(robot, 'C'), route_id=route)
    mobile = PinkyMobile(load_profile(config['profiles'][robot]))
    try:
        print(robot+' Route Server → '+route, flush=True)
        return mobile.execute(command, threading.Event())
    finally:
        mobile.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['move','both','arm','parking','rviz','teleop','setup','list','locate'])
    p.add_argument('--robot', choices=['P1','P2'], default='P1')
    p.add_argument('--zone', choices=['A','B','C','front','back'], default='A')
    p.add_argument('--from', dest='source', choices=['front','back','A','B','C','A_exit','B_exit'])
    p.add_argument('--route')
    p.add_argument('--parking', action='store_true')
    p.add_argument('--start-at-observation', action='store_true')
    p.add_argument('--mode', choices=['view','teach','teach-observe','geometry','align','list','odom'], default='view')
    p.add_argument('--phase', choices=['localize','navigation','route','relay'], default='route')
    p.add_argument('--dictionary'); p.add_argument('--marker-id', type=int)
    p.add_argument('--marker-size-mm', type=float); p.add_argument('--marker-forward-mm', type=float)
    p.add_argument('--marker-left-mm', type=float); p.add_argument('--front-angle-deg', type=float)
    p.add_argument('--sku', default='SKU-JIN-RAMEN'); p.add_argument('--slot', type=int, default=0)
    p.add_argument('--side', choices=['left','right'])
    args = p.parse_args(); config = configuration()
    if args.operation == 'setup':
        domain = args.robot[-1]
        script = 'run_pinky_route_server.sh' if args.phase == 'route' else 'run_pinky_robot.sh'
        phase = '' if args.phase == 'route' else args.phase
        command = (f'PINKY_DOMAIN_ID={domain} PINKY_ROBOT_ID=pinky-{domain} '
                   f'PINKY_MAP_FILE="$HOME/cartrina-field/maps/pinky_map_new.yaml" '
                   f'bash ~/cartrina-field/{script} {phase}')
        subprocess.run(ssh(config, config['robots'][args.robot], command), check=True); return
    if args.operation == 'rviz':
        import os
        env = dict(os.environ, ROS_DOMAIN_ID=args.robot[-1])
        path = f'runtime/field/pinky-p{args.robot[-1]}-initial-pose.rviz'
        if not Path(path).exists(): path = 'config/pinky-field.rviz'
        subprocess.Popen(['rviz2', '-d', path], env=env, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); return
    if args.operation == 'teleop':
        subprocess.run(['/usr/bin/python3', '-m', 'scripts.pinky_teach_parking', '--robot', args.robot], check=True); return
    if args.operation == 'list':
        print(json.dumps(run_station(args.zone, {'operation':'inventory','zone':args.zone}), ensure_ascii=False, indent=2)); return
    if args.operation == 'parking':
        options = {k: getattr(args, k) for k in ['dictionary','marker_id','marker_size_mm','marker_forward_mm','marker_left_mm']
                   if getattr(args, k) is not None}
        if args.front_angle_deg is not None: options['forward_angle_deg'] = args.front_angle_deg
        if args.start_at_observation: options['start_at_observation'] = True
        run_station(args.zone, {'operation':'parking','robot':args.robot,'zone':args.zone,
                               'mode':args.mode,'options':options,'interactive':True}); return
    state_path = Path(config['state_file'])
    state = json.loads(state_path.read_text()) if state_path.exists() else {'P1':'front','P2':'back'}
    if args.operation == 'locate':
        state[args.robot] = args.source or args.zone
        atomic_json(state_path, state); print('배치 기록만 저장:', state); return
    if args.operation in ('move','both'):
        with state_path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(state_path.read_text()) if state_path.exists() else state
            source = args.source or state[args.robot]
            routes = [args.route] if args.route else route_ids(source, args.zone)
            arrival = {}
            for route in routes:
                arrival = navigate(config, args.robot, route, command_for(args.robot, args.zone))
                print(json.dumps(arrival, ensure_ascii=False))
            state[args.robot] = args.zone; atomic_json(state_path, state)
            if args.parking:
                result = run_station(args.zone, {'operation':'parking','mode':'align','robot':args.robot,'zone':args.zone,
                    'options':{'start_at_observation': args.start_at_observation or arrival.get('parking_start') == 'observe'}})
                print(json.dumps(result, ensure_ascii=False))
                if result.get('status') not in ('aligned','operator_confirmed'): return
    if args.operation in ('arm','both'):
        command = command_for(args.robot, args.zone)
        command.update(kind='HANDOFF' if args.zone == 'C' else 'PICK',
                       device_id='omx-handoff' if args.zone == 'C' else 'omx-'+args.zone.lower(),
                       basket_side=args.side or ('left' if args.robot == 'P1' else 'right'), basket_id='direct-test',
                       items=[{'sku':args.sku,'slot':args.slot,'item_id':str(uuid.uuid4())}])
        print(json.dumps(run_station(args.zone, {'operation':'arm','zone':args.zone,'command':command,
                                                'interactive':args.zone=='C'}), ensure_ascii=False))


if __name__ == '__main__':
    main()
