"""Record four overhead waiting targets. No ROS or motion commands."""
import hashlib
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np
import yaml

from robot_gateway.hardware.aruco_parking import detect_markers, plane_transform
from robot_gateway.hardware.overhead import marker_pose, project
from robot_gateway.hardware.pinky import atomic_json
from scripts.pinky_parking import TerminalKeys


def targets_path(config):
    return Path(config.get('wait_targets_file', str(Path(config['output_directory'])/'wait-targets.json')))


def save_target(config, args, marker, frame, preview, calibration=None):
    path = targets_path(config)
    targets = json.loads(path.read_text()) if path.exists() else {}
    key = args.slot+'/'+args.robot
    root = path.parent
    root.mkdir(parents=True, exist_ok=True)
    reference = root/(args.slot+'-'+args.robot+'-target.png')
    robot = {'robot': args.robot, 'front_yaw_from_edge': math.radians(args.front_angle_deg),
             'height_m': args.height_mm/1000 if args.height_mm is not None else None,
             'base_to_marker_m': ([args.marker_forward_mm/1000, args.marker_left_mm/1000]
                                 if args.marker_forward_mm is not None and args.marker_left_mm is not None else None)}
    lens = config.get('intrinsics_file')
    lens_hash = hashlib.sha256(Path(lens).read_bytes()).hexdigest() if lens else None
    pose = None
    if (calibration and robot['height_m'] is not None
            and calibration['image_size'] == [frame.shape[1], frame.shape[0]]
            and calibration.get('intrinsics_sha256') == lens_hash):
        pose = marker_pose(marker, calibration, robot)['base_pose']
    target = {**marker, 'robot': args.robot, 'slot': args.slot, 'recorded_at': time.time(),
              'marker_size_mm': args.size_mm, 'geometry': robot, 'camera': config['camera'],
              'image_size': [frame.shape[1], frame.shape[0]], 'reference_image': str(reference),
              'calibration_file': config['calibration_file'], 'intrinsics_sha256': lens_hash,
              'map_pose': pose, 'frame_id': 'map' if pose else None, 'record_only': True}
    if path.exists():
        path.with_name('wait-targets.previous.json').write_bytes(path.read_bytes())
    if not cv2.imwrite(str(reference), frame) or not cv2.imwrite(str(reference.with_name(reference.stem+'-view.jpg')), preview):
        raise RuntimeError('대기 목표 사진 저장 실패')
    targets[key] = target
    atomic_json(path, targets)
    print('대기 목표 저장 완료: '+key+' / '+str(path), flush=True)
    print('지도 차체 좌표: '+(json.dumps(pose) if pose else '미등록 — 영상 목표만 저장. 캘리·높이 등록 후 연결'), flush=True)
    return target


def run(args, config):
    path = targets_path(config)
    if args.mode == 'wait-list':
        targets = json.loads(path.read_text()) if path.exists() else {}
        print(json.dumps({k: {'marker_id': v['marker_id'], 'marker_size_mm': v['marker_size_mm'],
                             'front_angle_deg': math.degrees(v['geometry']['front_yaw_from_edge']),
                             'recorded_at': v['recorded_at'], 'map_pose': v['map_pose']}
                          for k, v in targets.items()}, ensure_ascii=False, indent=2))
        return
    if any(v is None for v in [args.robot, args.slot, args.marker_id, args.size_mm, args.front_angle_deg]):
        raise ValueError('wait: --robot --slot --marker-id --size-mm --front-angle-deg가 필요합니다.')
    calibration_path = Path(config['calibration_file'])
    calibration = json.loads(calibration_path.read_text()) if calibration_path.exists() else None
    lens = yaml.safe_load(Path(config['intrinsics_file']).read_text()) if config.get('intrinsics_file') else None
    cam = config['camera']
    window = 'Pinky wait target (NO MOTION)'
    cap = None
    print(f'{args.slot}/{args.robot}: ID {args.marker_id}, 앞방향 {args.front_angle_deg:g}도. 이동 명령 없음.', flush=True)
    print('실제 대기자리에 놓고 영상 창 또는 이 터미널에서 Enter/S: 저장·종료, Q: 취소.', flush=True)
    frames, began, fps, count, last_found = 0, time.monotonic(), 0., 0, None
    try:
        if not args.image:
            cap = cv2.VideoCapture(cam['camera_by_id'], cv2.CAP_V4L2)
            for prop, value in [(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG')),
                                (cv2.CAP_PROP_FRAME_WIDTH, cam['width']), (cv2.CAP_PROP_FRAME_HEIGHT, cam['height']),
                                (cv2.CAP_PROP_FPS, cam['fps']), (cv2.CAP_PROP_BUFFERSIZE, 1)]:
                cap.set(prop, value)
        if not args.headless:
            cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
        with TerminalKeys(not args.headless) as keys:
            while True:
                ok, frame = (True, cv2.imread(args.image)) if args.image else cap.read()
                if not ok or frame is None:
                    raise RuntimeError('전체 카메라 수신 실패. 다른 카메라 프로그램을 Q로 닫고 실행하세요.')
                if lens:
                    matrix = np.float64(lens['camera_matrix']['data']).reshape(3, 3)
                    matrix[0] *= frame.shape[1]/lens['image_width']
                    matrix[1] *= frame.shape[0]/lens['image_height']
                    frame = cv2.undistort(frame, matrix, np.float64(lens['distortion_coefficients']['data']))
                found = detect_markers(frame, config.get('dictionary') or 'DICT_5X5_1000', args.marker_id)
                marker = found[0] if found else None
                if bool(found) != last_found:
                    print('대상 마커: '+('검출됨' if found else '미검출'), flush=True)
                    last_found = bool(found)
                preview = frame.copy()
                if marker:
                    cv2.polylines(preview, [np.int32(marker['corners'])], True, (0, 255, 0), 3)
                    angle = math.radians(args.front_angle_deg)
                    arrow = project([[0, 0], [.8*math.cos(angle), .8*math.sin(angle)]],
                                    np.linalg.inv(plane_transform(marker)))
                    cv2.arrowedLine(preview, tuple(np.int32(arrow[0])), tuple(np.int32(arrow[1])), (0, 255, 255), 3)
                frames += 1
                now = time.monotonic()
                if now-began >= 1:
                    fps, frames, began = frames/(now-began), 0, now
                for row, text in enumerate([f'{args.slot}/{args.robot} ID:{args.marker_id} FRONT:{args.front_angle_deg:g}deg',
                                             f'{frame.shape[1]}x{frame.shape[0]} | {fps:.1f} FPS | Enter/S: save | Q: cancel',
                                             'YELLOW: ROBOT FRONT | NO ROS / NO MOTION']):
                    cv2.putText(preview, text, (15, 30+row*30), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 255, 255), 2)
                key = -1
                if not args.headless:
                    scale = min(1280/frame.shape[1], 800/frame.shape[0], 1.)
                    cv2.imshow(window, cv2.resize(preview, None, fx=scale, fy=scale))
                    key = cv2.waitKey(1) & 255
                    if key == 255:
                        key = keys.read()
                if key in (ord('q'), ord('Q'), 27):
                    break
                if key in (10, 13, ord('s'), ord('S')):
                    if marker is None:
                        print('대상 ID가 검출된 상태에서 저장하세요.', flush=True)
                    else:
                        save_target(config, args, marker, frame, preview, calibration)
                        break
                count += 1
                if args.frames and count >= args.frames:
                    break
    finally:
        if cap is not None:
            cap.release()
        if not args.headless:
            cv2.destroyAllWindows()
