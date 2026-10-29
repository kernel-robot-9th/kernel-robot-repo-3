"""Prepare one six-item order; hardware execution starts only in worker commands."""
import argparse
import json
import os
from pathlib import Path
import sys
import subprocess
import signal
from datetime import datetime
from zoneinfo import ZoneInfo

POINTER = Path('runtime/field/six-item-demo-current.json')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def prepare():
    if POINTER.exists():
        return json.loads(POINTER.read_text())['directory']
    directory = Path('runtime/field/six-item-demo-'+datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d-%H%M%S'))
    products = json.loads(Path('config/products.json').read_text())
    for product in products:
        product['station'] = 'load-a' if product['sku'] == 'SKU-RICE-CHIP' else 'load-b'
        product['initial_stock'] = 3 if product['sku'] == 'SKU-RICE-CHIP' else 1
    save(directory/'products.json', products)
    readiness = json.loads(Path('runtime/field/pinky-demo/readiness.json').read_text())
    readiness.update(parallel_order=True, handoff_arrival_only=True, preferred_robot='pinky-1',
                     products_file=str(directory/'products.json'))
    save(directory/'readiness.json', readiness)
    source = json.loads(Path('runtime/field/pinky-control-worker.json').read_text())
    for zone in ('A', 'B'):
        config = dict(source, node_id='gateway-'+zone.lower(), remote_arm_zone=zone,
                      state_directory=str(directory/'worker-state'))
        if zone == 'B':
            config.pop('mobile_factory', None)
            config.pop('mobile_profiles', None)
        save(directory/('worker-'+zone.lower()+'.json'), config)
    from server.distributed import DistributedEngine
    engine = DistributedEngine(str(directory/'shopping.db'), mode='hardware', readiness=readiness)
    engine.select_field_route(3)
    engine.store.close()
    save(POINTER, {'directory':str(directory)})
    return str(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'server', 'worker-a', 'worker-b', 'queue', 'start-workers', 'stop-workers'])
    args = parser.parse_args()
    if args.operation == 'prepare':
        print('준비 완료 (장비 실행 없음): '+prepare())
        return
    directory = Path(json.loads(POINTER.read_text())['directory'])
    if args.operation in ('start-workers', 'stop-workers'):
        for zone in ('a', 'b'):
            pidfile = directory/('worker-'+zone+'.pid')
            pid = int(pidfile.read_text()) if pidfile.exists() else 0
            process = Path('/proc')/str(pid)/'cmdline'
            running = process.exists() and ('worker-'+zone).encode() in process.read_bytes()
            if args.operation == 'stop-workers':
                if running: os.kill(pid, signal.SIGINT)
            elif not running:
                with (directory/('worker-'+zone+'.log')).open('ab') as log:
                    child = subprocess.Popen(['bash','scripts/run_six_item_demo.sh','worker-'+zone],
                        stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
                pidfile.write_text(str(child.pid)+'\n')
        print('worker '+args.operation+': '+str(directory))
        return
    if args.operation == 'queue':
        from robot_gateway.hardware.station_remote import configuration
        from robot_gateway.hardware.pinky import atomic_json
        atomic_json(configuration()['state_file'], {'P1':'front', 'P2':'back'})
        print('배치 기록: P1 전열 / P2 후열. 로봇 위치·방향은 camera-pose로 갱신하세요.')
        return
    credentials = json.loads(Path('runtime/field/credentials.json').read_text())
    if args.operation == 'server':
        os.environ.update(SHOP_DB=str(directory/'shopping.db'), SHOP_DEVICE_MODE='hardware',
            SHOP_GATEWAY_MODE='distributed', SHOP_TEST_ONLY='0', SHOP_ADMIN_TOKEN=credentials['admin'],
            SHOP_NODE_TOKENS=json.dumps(credentials['nodes']), SHOP_HARDWARE_READINESS=str(directory/'readiness.json'))
        os.environ.pop('SHOP_MOTION_BACKEND', None)
        argv = ['uvicorn', 'server.api:create_app', '--factory', '--host', '0.0.0.0', '--port', '8000', '--workers', '1']
    else:
        zone = args.operation[-1]
        os.environ['SHOP_NODE_TOKEN'] = credentials['nodes']['gateway-'+zone]
        argv = ['robot_gateway.hardware.worker', '--config', str(directory/('worker-'+zone+'.json')),
                '--server', 'http://127.0.0.1:8000', '--execute']
    # Keep venv packages ahead of Ubuntu packages while making ROS/OpenCV available.
    sys.path.append('/usr/lib/python3/dist-packages')
    sys.argv = argv
    import runpy
    runpy.run_module(argv[0], run_name='__main__')


if __name__ == '__main__':
    main()
