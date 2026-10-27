"""P1/P2 move to A/B/C, or A pick/both; no central order changes."""
import argparse
import json
from pathlib import Path
import threading
import time
import uuid

from robot_gateway.hardware.pinky import PinkyMobile, load_profile, atomic_json
from robot_gateway.hardware.yolo import YoloArm
from robot_gateway.hardware.evidence import EvidenceFiles
from robots.pinky.field_routes import command_route
from server.catalog import load_products


def wait_for_mobile(mobile):
    mobile.action.wait_for_server()
    mobile.spin_action.wait_for_server()
    if mobile.profile.get('entry_planner_id'):
        mobile.planner_action.wait_for_server()
    while not mobile.buffer.can_transform(mobile.profile['frame_id'], mobile.profile['base_frame'],
                                          mobile.rclpy.time.Time()):
        time.sleep(.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['move', 'pick', 'both'], nargs='?', default='both')
    parser.add_argument('--zone', type=str.upper, choices=['A', 'B', 'C'], default='A')
    parser.add_argument('--robot', type=str.upper, choices=['P1', 'P2'], default='P1')
    parser.add_argument('--parking', action='store_true', help='주행 뒤 상단 카메라 마커로 정렬')
    parser.add_argument('--parking-config', default='runtime/field/pinky-parking.json')
    args = parser.parse_args()
    if args.zone != 'A' and args.operation != 'move':
        parser.error('B/C는 move 이동만 지원합니다. pick/both는 A 적재용입니다.')
    uid = lambda: str(uuid.uuid4())
    cfg = json.loads(Path('runtime/field/gateway-a.hardware.json').read_text())
    profile = load_profile(cfg['mobile_config'] if args.robot == 'P1'
                           else 'runtime/field/pinky-mobile-p2.json')
    cancelled = threading.Event()
    command = {
        'id': uid(), 'run_id': uid(), 'task_id': uid(), 'session_id': uid(),
        'robot_id': profile['robot_id'], 'device_id': profile['robot_id'], 'mode': 'hardware',
        'kind': 'NAVIGATE', 'zone_id': {'A': 'load-a', 'B': 'load-b', 'C': 'handoff'}[args.zone],
        'created_at': time.time(),
        'scope': 'device_test',
        'items': [{'sku': 'SKU-JIN-RAMEN', 'slot': 0, 'item_id': uid()}],
    }
    parking_result = None
    if args.operation in ('move', 'both'):
        if args.operation == 'move':
            command['items'] = []
        command['path_plan'] = command_route(profile['goals_file'], command)
        mobile = PinkyMobile(profile)
        try:
            print('Nav2·지도 좌표 연결 대기...', flush=True)
            wait_for_mobile(mobile)
            print(f'{args.robot} 현재 위치 → {args.zone} 주행 시작', flush=True)
            print(f'{args.zone} Nav2 동작 완료:', json.dumps(mobile.execute(command, cancelled), ensure_ascii=False), flush=True)
        finally:
            mobile.close()
    if args.parking:
        from scripts.pinky_parking import run_parking
        parking_result = run_parking('align', args.robot, args.zone, args.parking_config)
        if parking_result['status'] not in ('aligned', 'operator_confirmed'):
            print('영상 주차를 종료했습니다. 집기는 실행하지 않았습니다.', flush=True)
            return
    if args.operation == 'move':
        return
    frames = type('Frames', (), {'offer': lambda *args, **kwargs: None})()
    arm = YoloArm(cfg['yolo'], EvidenceFiles(cfg['evidence_directory']), frames, load_products())
    command.update(id=uid(), device_id='omx-a', kind='PICK', created_at=time.time())
    print('진라면 1개 → 슬롯 0 적재 시작', flush=True)
    try:
        arm_result = arm.execute(command, cancelled)
    except Exception as exc:
        if parking_result:
            parking_result['arm_error'] = type(exc).__name__+': '+str(exc)
            atomic_json(parking_result['result_file'], parking_result)
        raise
    print('동작 종료:', json.dumps(arm_result, ensure_ascii=False), flush=True)
    if parking_result:
        parking_result['arm_result'] = arm_result
        atomic_json(parking_result['result_file'], parking_result)
    print('실제 진라면이 슬롯 0에 놓였는지 확인하세요.', flush=True)


if __name__ == '__main__':
    main()
