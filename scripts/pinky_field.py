"""Register a stationary map goal or inspect ROS. Never sends navigation goals."""
import argparse
import json
import math
from pathlib import Path
import time

from robot_gateway.hardware.pinky import PinkyMobile, atomic_json, load_profile, pose_values


def register(profile, zone, operation, output, timeout):
    from geometry_msgs.msg import PoseStamped
    mobile = PinkyMobile(profile)
    done = []
    def selected(message):
        try:
            if message.header.frame_id != profile['frame_id']:
                raise ValueError('map frame이 다른 목표입니다')
            at = message.header.stamp.sec + message.header.stamp.nanosec/1e9
            if not -1 <= time.time()-at <= 2:
                raise ValueError('목표 입력 시각이 오래됐습니다')
            goal = pose_values(message.pose)
            with mobile.data_lock:
                grid, signature = mobile.map, mobile.map_hash
            if grid is None:
                raise ValueError('지도 수신 대기')
            info = grid.info
            if abs(info.origin.orientation.z) > 1e-6:
                raise ValueError('회전된 지도 원점은 별도 좌표 검증이 필요합니다')
            x = math.floor((goal['x']-info.origin.position.x)/info.resolution)
            y = math.floor((goal['y']-info.origin.position.y)/info.resolution)
            if not (0 <= x < info.width and 0 <= y < info.height) or grid.data[y*info.width+x] != 0:
                raise ValueError('지도에서 확인된 빈 공간을 선택하세요')
            path = Path(output)
            registry = json.loads(path.read_text()) if path.exists() else {
                'schema_version': 1, 'robot_id': profile['robot_id'], 'frame_id': profile['frame_id'],
                'map_sha256': signature, 'goals': {}}
            if registry['map_sha256'] != signature or registry['robot_id'] != profile['robot_id']:
                raise ValueError('기존 목표 파일의 로봇·지도와 다릅니다')
            entry = registry['goals'].setdefault(zone, {'arrival': None, 'exit': None, 'radius': .15,
                'measured': True})
            entry[operation] = goal
            entry['registered_at'] = time.time()
            atomic_json(path, registry)
            print(json.dumps({'registered': zone, 'operation': operation, 'pose': goal,
                              'output': str(path), 'motion_executed': False}, ensure_ascii=False), flush=True)
            done.append(True)
        except (ValueError, KeyError, OSError) as exc:
            print('등록 보류: ' + str(exc), flush=True)
    subscription = mobile.node.create_subscription(PoseStamped, profile['registration_topic'], selected, 10)
    print('READY: RViz 2D Goal Pose에서 A 도착점을 누르고 P1 앞방향으로 드래그하세요. 실제 이동 없음.', flush=True)
    try:
        deadline = time.monotonic()+timeout
        while not done and time.monotonic() < deadline:
            time.sleep(.1)
        if not done:
            raise RuntimeError('목표 등록 대기 종료: 파일을 만들지 않았습니다')
    finally:
        mobile.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['inspect', 'register', 'aligned'])
    parser.add_argument('--profile', default='runtime/field/pinky-mobile.json')
    parser.add_argument('--zone', default='load-a')
    parser.add_argument('--target', choices=['arrival', 'exit'], default='arrival')
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--command', help='관제에서 받은 실제 명령 JSON 파일')
    parser.add_argument('--evidence-directory', default='runtime/observations')
    args = parser.parse_args()
    profile = load_profile(args.profile)
    if args.operation == 'register':
        register(profile, args.zone, args.target, profile['goals_file'], args.timeout)
    elif args.operation == 'aligned':
        command = json.loads(Path(args.command).read_text())
        if command['mode'] != 'hardware' or command['robot_id'] != profile['robot_id'] or command['kind'] != 'NAVIGATE':
            raise ValueError('현재 실물 Pinky 이동 명령이 필요합니다')
        if any(c not in '0123456789abcdef-' for c in command['id'].lower()):
            raise ValueError('invalid command id')
        input('실제 바구니 정렬·Pinky 정지를 확인한 뒤 Enter: ')
        atomic_json(Path(args.evidence_directory)/(command['id']+'.aligned.json'), {
            **{k:command[k] for k in ('run_id','task_id','session_id','device_id')},
            'observed_at': time.time(), 'source': 'operator',
            'data': {'aligned': True, 'zone_id': command['zone_id']}})
        print('운영자 정렬 확인 전달 완료 · 물체 적재 성공 확인과 별개')
    else:
        mobile = PinkyMobile(profile)
        try:
            deadline = time.monotonic()+min(args.timeout, 5)
            while time.monotonic()<deadline:
                report = mobile.inspect()
                if report['connected']:
                    break
                time.sleep(.1)
            print(json.dumps(report, ensure_ascii=False))
        finally:
            mobile.close()


if __name__ == '__main__':
    main()
