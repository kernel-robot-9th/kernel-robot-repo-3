"""Record overhead corners and odometry during explicit calibration movements."""
import argparse
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np

from robot_gateway.hardware.aruco_parking import detect_markers
from robot_gateway.hardware.overhead import project
from robot_gateway.hardware.pinky import atomic_json, pose_values


def rotation(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s], [s, c]])


def corners_in_odom(sample, angle, offset, size=.08):
    pose = sample['odom']
    square = np.array([[-1, 1], [1, 1], [1, -1], [-1, -1]]) * size / 2
    return ((square @ rotation(angle).T + offset) @ rotation(pose['yaw']).T
            + [pose['x'], pose['y']])


def fit_samples(samples):
    """Odom establishes relative coordinates; known square also constrains scale."""
    from scipy.optimize import least_squares
    pixels = np.concatenate([s['corners'] for s in samples])
    initial = np.concatenate([corners_in_odom(s, math.pi, [0, 0]) for s in samples])
    matrix, _ = cv2.findHomography(pixels, initial, 0)
    # Normalize pixels for numerical conditioning.
    normalize = np.diag([1 / 1920, 1 / 1080, 1])
    uv = project(pixels, normalize)
    matrix = matrix @ np.linalg.inv(normalize)
    matrix /= matrix[2, 2]

    def residual(p):
        h = np.r_[p[:8], 1].reshape(3, 3)
        expected = np.concatenate([corners_in_odom(s, p[8], p[9:11]) for s in samples])
        return (project(uv, h) - expected).ravel()

    solved = least_squares(residual, np.r_[matrix.ravel()[:8], math.pi, 0, 0],
                           loss='soft_l1', f_scale=.005, max_nfev=400)
    h = np.r_[solved.x[:8], 1].reshape(3, 3) @ normalize
    errors = np.linalg.norm(residual(solved.x).reshape(-1, 2), axis=1)
    return {'image_to_odom': h.tolist(), 'marker_edge_from_base_rad': float(solved.x[8]),
            'base_to_marker_m': solved.x[9:11].tolist(),
            'fit_corner_rms_m': float(np.sqrt(np.mean(errors**2))),
            'fit_corner_max_m': float(errors.max()), 'optimizer_success': bool(solved.success)}


def evaluate(sample, result):
    measured = project(sample['corners'], result['image_to_odom'])
    expected = corners_in_odom(sample, result['marker_edge_from_base_rad'], result['base_to_marker_m'])
    return {'name': sample['name'], 'center_error_m': float(np.linalg.norm(measured.mean(0)-expected.mean(0))),
            'corner_rms_m': float(np.sqrt(np.mean(np.sum((measured-expected)**2, axis=1)))),
            'side_lengths_m': np.linalg.norm(np.roll(measured, -1, axis=0)-measured, axis=1).tolist()}


def register_map(result, reference):
    """Keep measured anchors as absolute references; never silently scale odom."""
    source = project([p['pixel'] for p in reference['points']], result['image_to_odom'])
    target = np.array([p['map_xy'] for p in reference['points']])
    u, _, vt = np.linalg.svd((source-source.mean(0)).T @ (target-target.mean(0)))
    correction = np.diag([1., np.linalg.det(vt.T @ u.T)])
    r = vt.T @ correction @ u.T
    t = target.mean(0)-r @ source.mean(0)
    rigid = np.eye(3); rigid[:2, :2] = r; rigid[:2, 2] = t
    matrix = rigid @ np.array(result['image_to_odom'])
    errors = np.linalg.norm(project([p['pixel'] for p in reference['points']], matrix)-target, axis=1)
    checks = []
    for p in reference.get('independent_validation', []):
        xy = project([p['pixel']], matrix)[0]
        checks.append(dict(p, predicted_xy=xy.tolist(), error_xy_m=(xy-p['map_xy']).tolist(),
                           error_m=float(np.linalg.norm(xy-p['map_xy']))))
    return dict(reference, image_to_map=matrix.tolist(), recorded_at=time.time(),
                method='stationary_marker_corners_and_odom_then_rigid_measured_anchor_alignment',
                fit_rms_m=float(np.sqrt(np.mean(errors**2))), fit_max_m=float(errors.max()),
                point_errors_m=errors.tolist(), independent_validation=checks,
                drive_fit=result, status='candidate_not_applied_to_navigation')


def collect(args):
    import rclpy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    rclpy.init(domain_id=1)
    node = rclpy.create_node('pinky_camera_calibration')
    latest = {}

    def receive(message):
        latest.update(odom=pose_values(message.pose.pose),
                      stamp=message.header.stamp.sec+message.header.stamp.nanosec/1e9,
                      received=time.time())

    sub = node.create_subscription(Odometry, '/odom', receive, qos_profile_sensor_data)
    publisher = node.create_publisher(Twist, '/cartrina/p1/drive_cmd_vel', 10)
    config = json.loads(Path(args.config).read_text())
    cam = config['camera']
    cap = cv2.VideoCapture(cam['camera_by_id'], cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cam['width'])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cam['height'])
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    root = Path(args.output); root.mkdir(parents=True, exist_ok=True)
    rows, trace = [], []

    def tick(linear=0., angular=0.):
        rclpy.spin_once(node, timeout_sec=.02)
        command = Twist(); command.linear.x = linear; command.angular.z = angular
        publisher.publish(command)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError('카메라 프레임 읽기 실패')
        markers = detect_markers(frame, 'DICT_5X5_1000', 0)
        value = dict(latest, captured_at=time.time(), markers=markers)
        trace.append(value)
        return frame, markers

    try:
        deadline = time.monotonic()+10
        while not latest and time.monotonic() < deadline:
            tick()
        if not latest:
            raise RuntimeError('P1 /odom 수신 없음: 구동부와 ROS_DOMAIN_ID=1 연결 확인')
        start = latest['odom'].copy()
        if args.distance or args.turn:
            print('이동 시작:', args.distance, 'm,', args.turn, 'deg', flush=True)
        turned, previous = 0., start['yaw']
        while args.distance or args.turn:
            pose = latest['odom']
            turned += math.atan2(math.sin(pose['yaw']-previous), math.cos(pose['yaw']-previous))
            previous = pose['yaw']
            if args.turn:
                remaining = math.radians(args.turn)-turned
                if abs(remaining) < .015:
                    break
                tick(angular=float(np.clip(remaining*1.5, -.3, .3)))
            else:
                travelled = ((pose['x']-start['x'])*math.cos(start['yaw'])
                             + (pose['y']-start['y'])*math.sin(start['yaw']))
                remaining = args.distance-travelled
                if abs(remaining) < .003:
                    break
                heading = math.atan2(math.sin(start['yaw']-pose['yaw']), math.cos(start['yaw']-pose['yaw']))
                tick(float(np.clip(remaining, -.06, .06)), float(np.clip(heading, -.2, .2)))
        # Settle first, then collect stationary images; acquisition time does not
        # need to substitute for an uncertain ROS/camera clock offset in motion.
        until = time.monotonic()+1
        while time.monotonic() < until:
            tick()
        until = time.monotonic()+2
        frame = None
        while time.monotonic() < until:
            frame, markers = tick()
            if markers:
                rows.append(dict(latest, captured_at=time.time(), corners=markers[0]['corners']))
        cv2.imwrite(str(root/(args.name+'.jpg')), frame)
        if rows:
            sample = dict(rows[len(rows)//2], name=args.name, validation=args.validation,
                          corners=np.median([s['corners'] for s in rows], axis=0).tolist(),
                          frame_count=len(rows), image_size=[frame.shape[1], frame.shape[0]])
            atomic_json(root/(args.name+'.json'), sample)
            print(json.dumps(sample, ensure_ascii=False), flush=True)
        else:
            print('이동 종료, 정차 영상에서 ID 0 미검출. 사진과 이동 기록 저장.', flush=True)
    finally:
        publisher.publish(Twist())
        time.sleep(.1)
        cap.release()
        atomic_json(root/(args.name+'-trace.json'), trace)
        node.destroy_node(); rclpy.shutdown()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['collect', 'fit'])
    p.add_argument('--config', default='runtime/field/pinky-overhead.json')
    p.add_argument('--output', required=True)
    p.add_argument('--name', default='start')
    p.add_argument('--distance', type=float, default=0.)
    p.add_argument('--turn', type=float, default=0.)
    p.add_argument('--validation', action='store_true')
    args = p.parse_args()
    if args.operation == 'collect':
        collect(args)
    else:
        root = Path(args.output)
        samples = [json.loads(f.read_text()) for f in sorted(root.glob('[0-9]*.json'))
                   if not f.name.endswith('-trace.json')]
        training = [s for s in samples if not s['validation']]
        result = fit_samples(training)
        result.update(training=[evaluate(s, result) for s in training],
                      validation=[evaluate(s, result) for s in samples if s['validation']],
                      coordinate_frame='P1 odom; absolute map registration is separate',
                      plane_height_m=.143, marker_size_m=.08)
        config = json.loads(Path(args.config).read_text())
        reference = json.loads(Path(config['calibration_file']).read_text())
        candidate = register_map(result, reference)
        atomic_json(root/'calibration-candidate.json', candidate)
        result['absolute_anchor_errors_m'] = candidate['point_errors_m']
        result['absolute_check_errors_m'] = [p['error_m'] for p in candidate['independent_validation']]
        atomic_json(root/'fit.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
