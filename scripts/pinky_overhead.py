"""Overview camera calibration and roof-marker display; never connects to ROS."""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np
import yaml

from robot_gateway.hardware.aruco_parking import detect_markers, front_angle, plane_transform
from robot_gateway.hardware.overhead import fit_plane, layout_to_map, map_pixel, marker_pose, project
from robot_gateway.hardware.pinky import atomic_json


def read(path, default=None):
    return json.loads(Path(path).read_text()) if path and Path(path).is_file() else default


def label(image, text, point, color=(30, 230, 255)):
    cv2.putText(image, text, tuple(map(int, point)), cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1, cv2.LINE_AA)


def identity(marker):
    return marker['dictionary'], marker['marker_id']


def select_anchor(anchor, marker, transform):
    return {'pixel': project([[0, 0]], np.linalg.inv(plane_transform(marker)))[0].tolist(),
            'map_xy': layout_to_map([anchor['layout_xy']], transform)[0].tolist(),
            'anchor_id': anchor['id'], 'layout_xy': anchor['layout_xy']}


def save_calibration(config, points, height_mm, image_size):
    matrix, residual = fit_plane(points)
    lens = config.get('intrinsics_file')
    result = {'schema_version': 1, 'recorded_at': time.time(), 'frame_id': 'map',
              'camera': config['camera'], 'image_size': image_size,
              'map_yaml': config['map_yaml'], 'plane_height_m': height_mm/1000,
              'coordinate_plane': 'horizontal_roof_marker_plane', 'points': points,
              'image_to_map': matrix, 'intrinsics_file': lens,
              'intrinsics_sha256': hashlib.sha256(Path(lens).read_bytes()).hexdigest() if lens else None,
              'lens_correction_applied': bool(lens), 'independent_validation': [], **residual}
    atomic_json(config['calibration_file'], result)
    print(json.dumps({'saved': config['calibration_file'], **residual}, ensure_ascii=False), flush=True)
    print('위 오차는 등록점 적합 오차입니다. 다른 위치에서 check로 확인하세요.', flush=True)
    return result


def run(args):
    config = read(args.config or 'runtime/field/pinky-overhead.json',
                  read('config/pinky-overhead.example.json'))
    if args.camera:
        config['camera']['camera_by_id'] = args.camera
    if args.dictionary:
        config['dictionary'] = args.dictionary
    if args.calibration:
        config['calibration_file'] = args.calibration
    root = Path(config['output_directory'])
    root.mkdir(parents=True, exist_ok=True)
    if args.mode in ('wait', 'wait-list'):
        from scripts.pinky_wait_record import run
        return run(args, config)
    calibration = read(config['calibration_file'])
    robots = read(config['robots_file'], {})
    registry = read(config['layout_registry'])
    transform = registry['layout_to_map']
    anchors = read(args.anchors_file, {}).get('points', [])
    if args.mode == 'anchors':
        if anchors:
            for anchor in anchors:
                print(json.dumps({**anchor, 'map_xy': layout_to_map([anchor['layout_xy']], transform)[0].tolist()}, ensure_ascii=False))
            print('줄자로 바닥 기준점을 표시하고 P1 마커 중심을 각 점 바로 위에 놓아 기록하세요.')
            return
        for name, xy in [('back_left', [0, 0]), ('A_B_wall', [.6, 0]),
                         ('B_C_wall', [1.2, 0]), ('back_right', [2, 0]),
                         ('front_left', [0, -1.5]), ('front_right', [2, -1.5])]:
            print(json.dumps({'name': name, 'layout_xy': xy,
                              'map_xy': layout_to_map([xy], transform)[0].tolist()}))
        print('기준 좌표 목록입니다. 바닥 모서리 영상을 상단 평면 대응점으로 직접 사용하지 마세요.')
        return
    if args.mode == 'calibrate' and args.plane_height_mm is None:
        raise ValueError('--plane-height-mm에 실제 기준점/상단 마커 높이를 입력하세요.')
    if args.mode == 'robot' and any(x is None for x in [args.robot, args.size_mm, args.height_mm]):
        raise ValueError('robot 모드에는 --robot P1/P2 --size-mm 실제크기 --height-mm 실제높이가 필요합니다.')
    if args.mode == 'check' and not calibration:
        raise ValueError('먼저 calibrate로 영상·지도 대응점을 저장하세요.')
    if args.mode == 'calibrate' and args.points_file:
        saved = read(args.points_file)
        save_calibration(config, saved['points'], args.plane_height_mm, saved['image_size'])
        return

    meta_path = Path(config['map_yaml'])
    metadata = yaml.safe_load(meta_path.read_text())
    map_image = cv2.imread(str(meta_path.parent/metadata['image']))
    if map_image is None:
        raise ValueError('저장 지도 이미지를 읽을 수 없습니다: '+str(meta_path))
    map_height = map_image.shape[0]
    map_scale = min(580/map_image.shape[1], 700/map_height)
    map_background = cv2.resize(map_image, None, fx=map_scale, fy=map_scale)

    def on_map(xy):
        return tuple(np.int32(map_pixel([xy], metadata, map_height, inverse=True)[0]*map_scale))

    # Show existing measured walls, not live AMCL estimates.
    layout = read('robots/pinky/reference/data/v4/layout.json')
    w, d, sd = layout['width'], layout['depth'], layout['station_depth']
    lines = [([0, 0], [w, 0]), ([0, -d], [w, -d]), ([0, 0], [0, -d]), ([w, 0], [w, -d])]
    lines += [([float(x), 0], [float(x), -sd]) for x in np.cumsum(layout['station_widths'])[:-1]]
    for a, b in lines:
        a, b = layout_to_map([a, b], transform)
        cv2.line(map_background, on_map(a), on_map(b), (0, 150, 255), 1)

    lens = None
    if config.get('intrinsics_file'):
        lens = yaml.safe_load(Path(config['intrinsics_file']).read_text())
    if calibration and args.mode in ('view', 'check'):
        lens_hash = hashlib.sha256(Path(config['intrinsics_file']).read_bytes()).hexdigest() if lens else None
        if lens_hash != calibration.get('intrinsics_sha256'):
            raise ValueError('캘리 등록 당시와 렌즈 보정 파일이 다릅니다. 같은 설정을 사용하세요.')

    cap = None
    state = {'frozen': None, 'pixel': None, 'map_xy': None, 'front': None, 'scale': 1., 'left_width': 0, 'anchor_id': None}
    points = read(root/'points-draft.json', {}).get('points', []) if args.resume else []
    index, count, last_ids = 0, 0, None
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    record = (root/f'observations-{stamp}.jsonl').open('w', buffering=1)
    last_record = 0.
    window = 'Pinky overhead: camera | saved map (NO MOTION)'

    def click(event, x, y, flags, unused):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        if x < state['left_width']:
            pixel = [x/state['scale'], y/state['scale']]
            if args.mode == 'robot':
                state['front'] = pixel
            else:
                state['pixel'] = pixel
            state['frozen'] = frame.copy()
        else:
            pixel = [(x-state['left_width'])/map_scale, y/map_scale]
            state['map_xy'] = map_pixel([pixel], metadata, map_height)[0].tolist()
            print('선택 map x/y (m):', state['map_xy'], flush=True)

    print('왼쪽: 현재 카메라 / 오른쪽: 저장 지도 + 주황 실측 배치. 로봇 명령은 없습니다.', flush=True)
    print('Tab: 마커 선택 / M: 선택 마커 중심 고정 / 클릭: 영상점→지도점 / X: 정확한 layout x y 입력', flush=True)
    print('Y: 정확한 map x y 입력 / Enter: 대응점·검증·로봇 저장 / S: 캘리 저장 / U: 마지막 점 삭제 / R: 선택 해제 / Q: 종료', flush=True)
    print('robot 모드: --front-angle-deg 지정 시 클릭 없이 Enter. 생략하면 실제 앞쪽 클릭 후 Enter.', flush=True)
    if anchors:
        print('기준점 1~4: 선택 마커 중심과 실측 좌표 자동 선택 → Enter로 기록. 바닥 십자 바로 위에 놓은 뒤 선택하세요.', flush=True)
    try:
        if not args.image:
            cam = config['camera']
            cap = cv2.VideoCapture(cam['camera_by_id'], cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, cam['width'])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cam['height'])
            cap.set(cv2.CAP_PROP_FPS, cam['fps'])
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not args.headless:
            cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
            cv2.setMouseCallback(window, click)
        while True:
            if state['frozen'] is not None:
                frame = state['frozen'].copy()
            else:
                ok, frame = (True, cv2.imread(args.image)) if args.image else cap.read()
                if not ok or frame is None:
                    raise RuntimeError('관제 카메라 영상 읽기 실패. USB 연결과 다른 영상 프로그램 사용 여부를 확인하세요.')
                if lens:
                    k = np.float64(lens['camera_matrix']['data']).reshape(3, 3)
                    k[0] *= frame.shape[1]/lens['image_width']
                    k[1] *= frame.shape[0]/lens['image_height']
                    frame = cv2.undistort(frame, k, np.float64(lens['distortion_coefficients']['data']))
            image_size = [frame.shape[1], frame.shape[0]]
            if calibration and args.mode in ('view', 'check') and image_size != calibration['image_size']:
                raise ValueError('캘리 등록 해상도와 현재 영상 해상도가 다릅니다. 같은 해상도를 사용하세요.')
            found = detect_markers(frame, config.get('dictionary'), args.marker_id)
            ids = [identity(m) for m in found]
            if ids != last_ids:
                print('검출:', ids, flush=True)
                last_ids = ids
            selected = found[index % len(found)] if found else None
            overlay, chart, observed = frame.copy(), map_background.copy(), []
            for marker in found:
                color = (0, 255, 0) if marker is selected else (0, 180, 255)
                cv2.polylines(overlay, [np.int32(marker['corners'])], True, color, 2)
                label(overlay, f'{marker["dictionary"]}:{marker["marker_id"]}', marker['corners'][0], color)
                if calibration:
                    robot = next((r for r in robots.values() if (r['dictionary'], r['marker_id']) == identity(marker)), None)
                    pose = marker_pose(marker, calibration, robot)
                    observed.append(pose)
                    xy = pose['marker_xy']
                    cv2.circle(chart, on_map(xy), 5, color, -1)
                    name = robot['robot'] if robot else str(marker['marker_id'])
                    label(chart, f'{name} marker {xy[0]:.3f}, {xy[1]:.3f}', on_map(xy), color)
                    if robot:
                        yaw = pose['yaw']
                        tip = [xy[0]+.12*math.cos(yaw), xy[1]+.12*math.sin(yaw)]
                        cv2.arrowedLine(chart, on_map(xy), on_map(tip), color, 2)
                        label(chart, f'yaw {math.degrees(yaw):.1f} base:{"yes" if pose["base_pose"] else "unset"}',
                              np.array(on_map(xy))+[0, 18], color)
            for i, p in enumerate(points):
                cv2.circle(overlay, tuple(np.int32(p['pixel'])), 4, (255, 100, 0), -1)
                label(overlay, str(i+1), p['pixel'])
                label(chart, str(i+1), on_map(p['map_xy']))
            for anchor in anchors:
                xy = layout_to_map([anchor['layout_xy']], transform)[0]
                cv2.circle(chart, on_map(xy), 7, (255, 80, 200), 1)
                label(chart, f"K{anchor['id']}", np.array(on_map(xy))+[8, 0], (255, 80, 200))
            if state['pixel'] is not None:
                cv2.circle(overlay, tuple(np.int32(state['pixel'])), 6, (255, 0, 255), 2)
            if state['front'] is not None:
                cv2.circle(overlay, tuple(np.int32(state['front'])), 6, (255, 0, 255), 2)
            state['scale'] = min(960/frame.shape[1], 700/frame.shape[0], 1.)
            left = cv2.resize(overlay, None, fx=state['scale'], fy=state['scale'])
            state['left_width'] = left.shape[1]
            canvas = np.zeros((max(left.shape[0], chart.shape[0])+32, left.shape[1]+chart.shape[1], 3), np.uint8)
            canvas[:left.shape[0], :left.shape[1]] = left
            canvas[:chart.shape[0], left.shape[1]:] = chart
            label(canvas, f'{args.mode} | points:{len(points)} | anchor:{state["anchor_id"] or "-"} | lens:{"corrected" if lens else "not calibrated"} | NO ROS / NO MOTION', (8, canvas.shape[0]-10))
            now = time.time()
            if now-last_record > .2:
                status = {'observed_at': now, 'frame_id': 'map', 'image_size': image_size,
                          'calibrated': bool(calibration), 'markers': observed,
                          'detected_ids': ids, 'lens_correction_applied': bool(lens)}
                atomic_json(root/'latest.json', status)
                record.write(json.dumps(status, ensure_ascii=False)+'\n')
                cv2.imwrite(str(root/'latest.jpg'), canvas)
                last_record = now
            if args.headless:
                key = -1
            else:
                cv2.imshow(window, canvas)
                key = cv2.waitKey(20) & 255
            count += 1
            if key in (ord('q'), 27) or (args.frames and count >= args.frames):
                break
            if key == 9:
                index += 1
                state.update(front=None, frozen=None)
            elif anchors and args.mode in ('calibrate', 'check') and ord('1') <= key <= ord('9'):
                anchor = next((a for a in anchors if a['id'] == key-ord('0')), None)
                if anchor and selected:
                    state.update(select_anchor(anchor, selected, transform), frozen=frame.copy())
                    print(f"기준점 {anchor['id']} 선택 / layout {anchor['layout_xy']} / 마커 중심 자동 선택. Enter: 저장", flush=True)
                else:
                    print('해당 기준점과 검출 마커를 확인하세요.', flush=True)
            elif key == ord('r'):
                state.update(pixel=None, map_xy=None, front=None, frozen=None, anchor_id=None)
            elif key == ord('m') and selected:
                state['pixel'] = project([[0, 0]], np.linalg.inv(plane_transform(selected)))[0].tolist()
                state['frozen'] = frame.copy()
            elif key in (ord('x'), ord('y')):
                xy = [float(v) for v in input(('layout' if key == ord('x') else 'map')+' x y (m): ').split()]
                state['map_xy'] = layout_to_map([xy], transform)[0].tolist() if key == ord('x') else xy
            elif key == ord('u') and points:
                points.pop()
                atomic_json(root/'points-draft.json', {'points': points, 'image_size': image_size,
                            'plane_height_mm': args.plane_height_mm})
            elif key == ord('s') and args.mode == 'calibrate':
                calibration = save_calibration(config, points, args.plane_height_mm, image_size)
                cv2.imwrite(str(root/'calibration-reference.jpg'), canvas)
            elif key in (10, 13):
                if args.mode == 'robot' and selected and (args.front_angle_deg is not None or state['front'] is not None):
                    offset = ([args.marker_forward_mm/1000, args.marker_left_mm/1000]
                              if args.marker_forward_mm is not None and args.marker_left_mm is not None else None)
                    robots[args.robot] = {'robot': args.robot, 'dictionary': selected['dictionary'],
                        'marker_id': selected['marker_id'], 'marker_size_m': args.size_mm/1000,
                        'height_m': args.height_mm/1000, 'base_to_marker_m': offset,
                        'front_yaw_from_edge': (math.radians(args.front_angle_deg) if args.front_angle_deg is not None
                                               else front_angle(selected, state['front'])), 'recorded_at': now}
                    atomic_json(config['robots_file'], robots)
                    cv2.imwrite(str(root/f'{args.robot}-reference.jpg'), overlay)
                    print('로봇 마커 저장:', json.dumps(robots[args.robot], ensure_ascii=False), flush=True)
                    break
                if state['pixel'] is None or state['map_xy'] is None:
                    print('영상점과 실제 지도 좌표를 먼저 선택하세요.', flush=True)
                    continue
                point = {'pixel': state['pixel'], 'map_xy': state['map_xy'], 'recorded_at': now}
                if state['anchor_id'] is not None:
                    point.update(anchor_id=state['anchor_id'], layout_xy=state['layout_xy'])
                if args.mode == 'calibrate':
                    previous = next((i for i, p in enumerate(points) if point.get('anchor_id') is not None
                                     and p.get('anchor_id') == point['anchor_id']), None)
                    if previous is None:
                        points.append(point)
                        previous = len(points)-1
                    else:
                        points[previous] = point
                    cv2.imwrite(str(root/f'point-{previous+1:02d}.jpg'), frame)
                    atomic_json(root/'points-draft.json', {'points': points, 'image_size': image_size,
                                'plane_height_mm': args.plane_height_mm})
                    print('대응점 저장:', len(points), point, flush=True)
                elif args.mode == 'check':
                    predicted = project([point['pixel']], calibration['image_to_map'])[0]
                    delta = predicted-np.array(point['map_xy'])
                    point.update(predicted_xy=predicted.tolist(), error_xy_m=delta.tolist(),
                                 error_m=float(np.linalg.norm(delta)))
                    calibration['independent_validation'].append(point)
                    atomic_json(config['calibration_file'], calibration)
                    print('검증 결과:', json.dumps(point, ensure_ascii=False), flush=True)
                state.update(pixel=None, map_xy=None, frozen=None, anchor_id=None)
    finally:
        record.close()
        if cap is not None:
            cap.release()
        if not args.headless:
            cv2.destroyAllWindows()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['view', 'calibrate', 'robot', 'check', 'anchors', 'wait', 'wait-list'])
    p.add_argument('--config')
    p.add_argument('--camera')
    p.add_argument('--dictionary')
    p.add_argument('--calibration', help='다른 상단 높이의 평면은 별도 파일 사용')
    p.add_argument('--anchors-file', help='번호로 선택할 실측 기준점 layout 좌표 JSON')
    p.add_argument('--plane-height-mm', type=float)
    p.add_argument('--robot', choices=['P1', 'P2'])
    p.add_argument('--slot', choices=['front', 'back'], help='대기 선두/후열 목표 기록')
    p.add_argument('--marker-id', type=int)
    p.add_argument('--front-angle-deg', type=float, help='마커 0도 축에 대한 실제 앞방향; 클릭보다 우선')
    p.add_argument('--size-mm', type=float)
    p.add_argument('--height-mm', type=float)
    p.add_argument('--marker-forward-mm', type=float, help='차체 원점→마커 중심의 전방 거리')
    p.add_argument('--marker-left-mm', type=float, help='차체 원점→마커 중심의 좌측 거리')
    p.add_argument('--points-file', help='이미 기록한 points/image_size JSON으로 평면 계산')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--image', help='저장 사진으로 확인, 카메라를 열지 않음')
    p.add_argument('--headless', action='store_true')
    p.add_argument('--frames', type=int, default=0)
    run(p.parse_args())


if __name__ == '__main__':
    main()
