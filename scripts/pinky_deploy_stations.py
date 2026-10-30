"""Deploy camera/arm entrypoints; never start a worker or move equipment."""
import argparse
import json
from pathlib import Path
import time

import paramiko

from robot_gateway.hardware.station_remote import configuration

FILES = ['scripts/pinky_station.py', 'scripts/run_pinky_station.sh', 'scripts/pinky_parking.py',
         'robot_gateway/recording.py',
         'scripts/run_pinky_station_worker.sh', 'robot_gateway/hardware/worker.py',
         'robot_gateway/hardware/field_status.py', 'robot_gateway/hardware/station_remote.py',
         'robot_gateway/hardware/aruco_parking.py', 'robot_gateway/hardware/nav2_parking_control.py',
         'robot_gateway/hardware/pinky.py', 'robots/pinky/field_routes.py', 'robots/pinky/route_graph.py',
         'robots/pinky/TWO_ROBOT_FIELD_COMMANDS.md',
         'runtime/field/pinky-mobile.json', 'runtime/field/pinky-mobile-p2.json',
         'runtime/field/pinky-p1-measured-goals.json', 'runtime/field/pinky-p2-measured-goals.json',
         'runtime/field/pinky-shared-parking.json', 'runtime/field/pinky-route-network.json',
         'runtime/field/pinky-route-network-p1.json', 'runtime/field/pinky-route-network-p2.json',
         'runtime/field/pinky-observation-goals.json']


def deploy(zone, config):
    station = config['stations'][zone]; user, host = station['host'].split('@')
    client = paramiko.SSHClient(); client.load_system_host_keys()
    client.connect(host, username=user, key_filename=str(Path(config['ssh_key']).expanduser()), timeout=5)
    sftp = client.open_sftp(); root = station['root']
    def mkdir(path):
        try: sftp.stat(path)
        except OSError:
            mkdir(str(Path(path).parent)); sftp.mkdir(path)
    backup = root+'/runtime/field/control-backup-'+time.strftime('%Y%m%d-%H%M%S')
    def put(path, content):
        target = root+'/'+path; mkdir(str(Path(target).parent))
        try:
            with sftp.open(target) as f: previous = f.read()
            saved = backup+'/'+path; mkdir(str(Path(saved).parent))
            with sftp.open(saved, 'wb') as f: f.write(previous)
        except FileNotFoundError: pass
        with sftp.open(target, 'wb') as f: f.write(content)
    try:
        for path in FILES:
            if Path(path).exists(): put(path, Path(path).read_bytes())
        if zone == 'C':
            from scripts.package_c_yolo import source_files
            for path in source_files():
                put(str(path), path.read_bytes())
        path = 'runtime/field/pinky-parking.json'
        try:
            with sftp.open(root+'/'+path) as f: parking = json.loads(f.read())
        except FileNotFoundError:
            parking = json.loads(Path('config/pinky-parking.example.json').read_text())
        if zone == 'C':
            with sftp.open(root+'/runtime/field/gateway-c.hardware.json') as f: hardware = json.loads(f.read())
            if hardware.get('unload_engine') != 'yolo':
                parking['zones']['C']['camera'] = {'camera_by_id': hardware['act']['front_by_id'],
                                                  'width':1920,'height':1080,'fps':30}
        put(path, json.dumps(parking, indent=2).encode())
        if zone in ('B', 'C'):
            node = 'gateway-'+zone.lower()
            with sftp.open(root+'/runtime/field/'+node+'.hardware.json') as f: worker = json.loads(f.read())
            worker.pop('mobile_factory', None); worker.pop('parking', None)
            worker['state_directory'] = 'runtime/hardware/pinky-control'
            put('runtime/field/pinky-control-'+node+'.json', json.dumps(worker, indent=2).encode())
        path = 'runtime/field/pinky-parking/geometry.json'
        try:
            with sftp.open(root+'/'+path) as f: geometry = json.loads(f.read())
        except FileNotFoundError: geometry = {}
        geometry.setdefault('P2', json.loads(Path(path).read_text())['P2'])
        put(path, json.dumps(geometry, indent=2).encode())
        print(zone+' 배포 완료. 기존 목표·관측·OMX hardware 파일 보존. 백업: '+backup)
    finally:
        sftp.close(); client.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--zone', choices=['A','B','C','all'], default='all')
    args = p.parse_args(); config = configuration()
    failed = []
    for zone in (config['stations'] if args.zone == 'all' else [args.zone]):
        try: deploy(zone, config)
        except Exception as exc:
            failed.append(zone); print(zone+' 배포 미완료: '+str(exc))
    raise SystemExit(bool(failed))
