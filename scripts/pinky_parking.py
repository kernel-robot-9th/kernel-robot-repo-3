"""A camera preview/target teaching/visual parking. Imports do not open devices."""
import argparse
from contextlib import AbstractContextManager
import json
import math
from pathlib import Path
import select
import sys
import time

from robot_gateway.hardware.aruco_parking import (
    OdomParking, ParkingDrive, ParkingOdometry, ParkingRecord, camera_odom_goal,
    detect_markers, front_angle, parking_error, rotate)
from robot_gateway.hardware.pinky import atomic_json, load_profile

DEFAULT_CONFIG = 'runtime/field/pinky-parking.json'


def read_targets(config):
    path = Path(config['targets_file'])
    return json.loads(path.read_text()) if path.is_file() else {'schema_version': 1, 'targets': {}}


class TerminalKeys(AbstractContextManager):
    def __init__(self, enabled=True):
        self.enabled = enabled

    def __enter__(self):
        self.saved = None
        if self.enabled and sys.stdin.isatty():
            import termios
            import tty
            self.saved = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin)
        return self

    def read(self):
        if self.saved is not None and select.select([sys.stdin], [], [], 0)[0]:
            return ord(sys.stdin.read(1))
        return -1

    def __exit__(self, *_):
        if self.saved is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.saved)


def run_parking(mode='align', robot='P2', zone='A', config_file=DEFAULT_CONFIG, *,
                marker_id=None, dictionary=None, marker_size_mm=None,
                marker_forward_mm=None, marker_left_mm=None,
                forward_angle_deg=None, headless=False, cancelled=None,
                progress=None, frames=None, terminal=True, start_at_observation=False):
    config = json.loads(Path(config_file).read_text())
    saved = read_targets(config)
    key = zone+'/'+robot
    target = saved['targets'].get(key)
    observation_file = Path(config.get('observation_file', Path(config['targets_file']).with_name('observations.json')))
    observations = json.loads(observation_file.read_text()) if observation_file.is_file() else {}
    geometry_file = Path(config.get('geometry_file', Path(config['targets_file']).with_name('geometry.json')))
    geometries = json.loads(geometry_file.read_text()) if geometry_file.is_file() else {}
    geometry = dict(geometries.get(robot, {}))
    if marker_size_mm is not None:
        geometry['marker_size_mm'] = marker_size_mm
    offset = geometry.get('base_to_marker_mm', [None, None])
    if marker_forward_mm is not None or marker_left_mm is not None:
        geometry['base_to_marker_mm'] = [marker_forward_mm if marker_forward_mm is not None else offset[0],
                                         marker_left_mm if marker_left_mm is not None else offset[1]]
    if mode == 'geometry':
        geometries[robot] = geometry
        atomic_json(geometry_file, geometries)
        return {'status': 'geometry_saved', 'robot': robot, 'geometry': geometry,
                'geometry_file': str(geometry_file)}
    if mode == 'odom':
        reader = ParkingOdometry(load_profile(config['robot_profiles'][robot]))
        try:
            until = time.monotonic()+3
            while reader.snapshot() is None and time.monotonic() < until:
                time.sleep(.05)
            return {'robot': robot, 'odom': reader.snapshot(), 'motion_command_sent': False}
        finally:
            reader.close()
    if mode == 'list':
        print(json.dumps(saved, ensure_ascii=False, indent=2))
        return saved
    if mode == 'release':
        drive = ParkingDrive(load_profile(config['robot_profiles'][robot]))
        drive.close()
        print(robot+' 주행 명령 선택을 Nav2로 돌렸습니다.')
        return {'status': 'released'}
    if mode == 'align' and target is None:
        raise RuntimeError(f'{key} 목표 영상이 없습니다. teach로 실제 주차 자세부터 저장하세요.')
    if mode == 'align' and (not geometry.get('marker_size_mm') or
                           any(v is None for v in geometry.get('base_to_marker_mm', [None, None]))):
        raise ValueError('실측 등록 필요: geometry --robot '+robot+
                         ' --marker-size-mm 한변mm --marker-forward-mm 전방mm --marker-left-mm 좌측mm')
    if mode == 'align' and key not in observations:
        raise ValueError(f'{key} 후진 관측 위치를 teach-observe로 먼저 등록하세요.')
    if mode == 'teach-observe' and (target is None or not geometry.get('marker_size_mm') or
                                    'base_to_marker_mm' not in geometry):
        raise ValueError('기존 주차 목표와 geometry 등록이 먼저 필요합니다.')
    import cv2
    import numpy as np
    gateway = json.loads(Path(config['zones'][zone]['gateway_config']).read_text())
    camera_config = config['zones'][zone].get('camera') or gateway.get('yolo')
    if camera_config is None:
        raise RuntimeError(f'{zone} 상단 카메라 입력을 parking 설정의 zones.{zone}.camera에 지정하세요.')
    dictionary = dictionary or (target or {}).get('dictionary')
    if marker_id is None:
        marker_id = (target or {}).get('marker_id')
    camera = None
    drive = None
    reader = None
    record = ParkingRecord(config['runs_directory'], robot, zone, mode)
    status, final_error, detail = 'cancelled', None, {}
    controller = (OdomParking(target, geometry, config['control'], observations[key],
                              start_at_observation=start_at_observation) if mode == 'align' else None)
    state = {}
    window = f'Pinky parking {robot}/{zone}: {mode}'
    mouse = {'point': None, 'scale': 1.}
    last_ids, selected_index, last_preview = None, 0, 0.
    last_source = None

    def click(event, x, y, flags, unused):
        if event == cv2.EVENT_LBUTTONDOWN:
            mouse['point'] = [x/mouse['scale'], y/mouse['scale']]

    try:
        camera = cv2.VideoCapture(camera_config['camera_by_id'], cv2.CAP_V4L2)
        if not camera.isOpened():
            raise RuntimeError('A 작업대 카메라를 열 수 없습니다. 카메라 사용 프로그램을 확인하세요.')
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, camera_config['width'])
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_config['height'])
        camera.set(cv2.CAP_PROP_FPS, camera_config['fps'])
        camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not headless:
            cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
            cv2.setMouseCallback(window, click)
        if mode == 'align':
            drive = ParkingDrive(load_profile(config['robot_profiles'][robot]), cancelled=cancelled)
            reader = drive
        elif mode == 'teach-observe':
            reader = ParkingOdometry(load_profile(config['robot_profiles'][robot]))
        print('Q: 종료 / Tab: 마커 선택 / teach: 로봇 앞쪽 방향 클릭 후 Enter 또는 S로 저장', flush=True)
        if mode == 'align':
            start_label = '관측 위치 도착 → 추가 후진 없이 관측' if start_at_observation else '후진 관측'
            print(start_label+' → Nav2 제어식 곡선 접근 → 확인/재시도. 완료 기준: 5mm·2°. Enter: 작업자 확인 종료 / Q: 취소', flush=True)
            detail.update(control_method='nav2_smooth_control_law_python', geometry=geometry, observation=observations[key])
        elif mode == 'teach-observe':
            print('마커가 잘 보이는 후진 위치에서 Enter로 등록합니다. 앞방향 클릭·이동 명령은 없습니다.', flush=True)
        print('기록 폴더: '+str(record.directory), flush=True)
        with TerminalKeys(terminal) as keys:
            while True:
                if cancelled is not None and cancelled.is_set():
                    status = 'cancelled'
                    break
                for _ in range(2):
                    camera.grab()
                ok, frame = camera.read()
                if not ok or frame is None:
                    raise RuntimeError('작업대 카메라 영상을 읽을 수 없습니다.')
                observed = detect_markers(frame, dictionary, marker_id)
                identities = [(o['dictionary'], o['marker_id']) for o in observed]
                if identities != last_ids:
                    print('검출 마커: '+str(identities), flush=True)
                    last_ids = identities
                current = observed[selected_index % len(observed)] if observed else None
                command = {'linear': 0., 'angular': 0., 'aligned': False}
                error = None
                camera_error = parking_error(target, current) if current is not None and target is not None else None
                odom = reader.snapshot() if reader else None
                if controller:
                    state = controller.update(odom, current)
                    error, command = state['error'], state['command']
                    source = (state['parking_phase'], state['control_source'], state['attempt'])
                    if source != last_source:
                        last_source = source
                        print(f"주차 단계: {source[0]} / 기준: {source[1]} / 시도: {source[2]}", flush=True)
                elif camera_error is not None:
                    error = camera_error
                if error is not None:
                    final_error = error
                if drive:
                    drive.move(command['linear'], command['angular'])
                overlay = frame.copy()
                for item in observed:
                    points = np.int32(item['corners'])
                    cv2.polylines(overlay, [points], True,
                                  (30, 255, 80) if item is current else (150, 150, 150), 2)
                    label = f"{item['dictionary']} ID={item['marker_id']}"
                    cv2.putText(overlay, label, tuple(points[0]), cv2.FONT_HERSHEY_SIMPLEX, .65, (30,255,80), 2)
                    if item is current:
                        center = np.asarray(item['corners']).mean(axis=0)
                        edge = np.asarray(item['corners'][1])-np.asarray(item['corners'][0])
                        cv2.arrowedLine(overlay, tuple(np.int32(center)), tuple(np.int32(center+edge)),
                                       (255,255,0), 3)
                        cv2.putText(overlay, '0 deg', tuple(np.int32(center+edge)),
                                    cv2.FONT_HERSHEY_SIMPLEX, .6, (255,255,0), 2)
                if target:
                    cv2.polylines(overlay, [np.int32(target['corners'])], True, (255,180,20), 2)
                if current and mouse['point']:
                    center = np.int32(np.asarray(current['corners']).mean(axis=0))
                    cv2.arrowedLine(overlay, tuple(center), tuple(map(int, mouse['point'])), (0,255,255), 3)
                lines = [f'{robot} / {zone} / {mode} / Q=quit',
                         'Target=blue / Observed=green / teach: click robot front, Enter=save']
                if error:
                    text = (f"distance={error['distance_mm']:.1f}mm" if 'distance_mm' in error else
                            f"distance={error['distance_marker_widths']:.3f} marker widths")
                    lines.append(text+f" yaw={math.degrees(error['yaw_error']):+.2f}deg")
                lines.append(f"v={command['linear']:+.3f}m/s w={command['angular']:+.3f}rad/s")
                if controller:
                    lines.append(f"Phase: {state['parking_phase']} / attempt {state['attempt']} / {state['control_source']}")
                if current is None:
                    lines.append('Marker not visible: '+('odom motion continues' if state.get('parking_phase')
                                 in ('reverse_observe', 'advance', 'align_heading') else 'stationary observation'))
                for row, text in enumerate(lines):
                    cv2.putText(overlay, text, (12, 30+row*27), cv2.FONT_HERSHEY_SIMPLEX, .65, (0,255,255), 2)
                record.event(marker=current, error=error, command=command, camera_error=camera_error,
                             **{k: v for k, v in state.items() if k not in ('error', 'command')},
                             observation='detected' if current else 'marker_missing')
                record.frame(overlay)
                if frames is not None:
                    frames.offer({'A': 'load-a', 'B': 'load-b', 'C': 'handoff-front'}[zone], overlay)
                if progress is not None:
                    progress(stage='parking', marker_id=marker_id,
                             marker_visible=current is not None, parking_error=error,
                             parking_command=command, parking_control_source=state.get('control_source'),
                             parking_phase=state.get('parking_phase'), parking_attempt=state.get('attempt'),
                             parking_odom=state.get('odom'), parking_odom_goal=state.get('odom_goal'),
                             result_file=str(record.directory/'result.json'))
                if time.monotonic()-last_preview > .5:
                    cv2.imwrite(str(record.directory/'latest.jpg'), overlay)
                    last_preview = time.monotonic()
                gui_key = -1
                if not headless:
                    mouse['scale'] = min(1., 960./frame.shape[1])
                    shown = cv2.resize(overlay, None, fx=mouse['scale'], fy=mouse['scale'])
                    cv2.imshow(window, shown)
                    gui_key = cv2.waitKey(1)
                keypress = gui_key if gui_key != -1 else (keys.read() if terminal else -1)
                if keypress in (ord('q'), ord('Q'), 27):
                    break
                if keypress == 9:
                    selected_index += 1
                    mouse['point'] = None
                if mode == 'teach-observe' and keypress in (10, 13, ord('s'), ord('S')):
                    if current is None or odom is None:
                        print('현재 마커 검출과 odom 수신이 필요합니다.', flush=True)
                        continue
                    goal = camera_odom_goal(target, current, geometry, odom['pose'])
                    dx, dy = goal['x']-odom['pose']['x'], goal['y']-odom['pose']['y']
                    forward, left = rotate(dx, dy, -goal['yaw'])
                    entry = {'retreat_m': math.hypot(dx, dy), 'goal_forward_m': forward,
                             'goal_left_m': left, 'recorded_at': time.time(),
                             'odom_pose_at_teach': odom, 'marker': current}
                    observations[key] = entry
                    atomic_json(observation_file, observations)
                    cv2.imwrite(str(observation_file.parent/f'{zone}-{robot}-observation.png'), frame)
                    detail['observation'] = entry
                    print('관측 위치 등록: '+json.dumps(entry, ensure_ascii=False), flush=True)
                    status = 'observation_saved'
                    break
                if mode == 'teach' and keypress in (10, 13, ord('s'), ord('S')):
                    if current is None:
                        print('저장할 마커가 영상에 없습니다.', flush=True)
                        continue
                    if forward_angle_deg is None and mouse['point'] is None:
                        print('영상에서 로봇 앞쪽 방향을 한 번 클릭하고 다시 저장하세요.', flush=True)
                        continue
                    target = {k: current[k] for k in ('dictionary','marker_id','corners')}
                    target.update(robot=robot, zone=zone, recorded_at=time.time(),
                                  marker_location='robot_roof', marker_size_mm=marker_size_mm,
                                  image_size=[frame.shape[1], frame.shape[0]],
                                  gateway_config=config['zones'][zone]['gateway_config'])
                    target['forward_yaw'] = (math.radians(forward_angle_deg) if forward_angle_deg is not None
                                             else front_angle(target, mouse['point']))
                    target['front_click_pixel'] = mouse['point']
                    reference = Path(config['targets_file']).parent/f'{zone}-{robot}-target.png'
                    reference.parent.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(reference), frame)
                    target['reference_image'] = str(reference)
                    saved['targets'][key] = target
                    atomic_json(config['targets_file'], saved)
                    detail['target'] = target
                    record.event(event='target_saved', target=target)
                    print('목표 저장 완료: '+str(reference), flush=True)
                    status = 'target_saved'
                    break
                if mode == 'align' and keypress in (10, 13):
                    status = 'operator_confirmed'
                    detail['physical_parking_confirmed'] = True
                    break
                if mode == 'align' and command['aligned']:
                    status = 'aligned'
                    break
    except KeyboardInterrupt:
        status = 'cancelled'
    except Exception as exc:
        status = 'error'
        detail['error'] = type(exc).__name__+': '+str(exc)
        raise
    finally:
        if drive:
            drive.close()
        elif reader:
            reader.close()
        if controller:
            detail.update(odom_goal=state.get('odom_goal'), final_odom=state.get('odom'),
                          alignment_basis=state.get('control_source'), last_camera_at=state.get('last_camera_at'),
                          final_phase=state.get('parking_phase'), attempts=state.get('attempt'),
                          verification_source=state.get('verification_source'),
                          control_method='nav2_smooth_control_law_python',
                          completion_tolerance={'position_mm': config['control']['position_tolerance_mm'],
                                                'yaw_deg': config['control']['yaw_tolerance_deg']},
                          final_marker_visible=current is not None if state else False)
        if camera is not None:
            camera.release()
        if not headless:
            cv2.destroyAllWindows()
        result = record.close(status, final_error=final_error, **detail)
        print('주차 실행 기록: '+result['result_file'], flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['view','teach','teach-observe','align','list','release','geometry','odom'])
    parser.add_argument('--robot', type=str.upper, choices=['P1','P2'], default='P2')
    parser.add_argument('--zone', type=str.upper, choices=['A','B','C'], default='A')
    parser.add_argument('--config', default=DEFAULT_CONFIG)
    parser.add_argument('--marker-id', type=int)
    parser.add_argument('--dictionary')
    parser.add_argument('--marker-size-mm', type=float)
    parser.add_argument('--marker-forward-mm', type=float)
    parser.add_argument('--marker-left-mm', type=float)
    parser.add_argument('--front-angle-deg', type=float)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--start-at-observation', action='store_true')
    args = parser.parse_args()
    result = run_parking(args.mode, args.robot, args.zone, args.config,
                         marker_id=args.marker_id, dictionary=args.dictionary,
                         marker_size_mm=args.marker_size_mm, forward_angle_deg=args.front_angle_deg,
                         marker_forward_mm=args.marker_forward_mm, marker_left_mm=args.marker_left_mm,
                         headless=args.headless, start_at_observation=args.start_at_observation)
    if args.mode not in ('list','release'):
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
