"""Fixed-camera visual parking from a taught Pinky roof marker. No I/O on import."""
from datetime import datetime
import json
import math
from pathlib import Path
import threading
import time
import uuid

from .nav2_parking_control import docking_velocity


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def detect_markers(frame, dictionary=None, marker_id=None):
    import cv2
    import numpy as np
    names = [dictionary] if dictionary else [
        'DICT_4X4_1000', 'DICT_5X5_1000', 'DICT_6X6_1000',
        'DICT_7X7_1000', 'DICT_ARUCO_ORIGINAL']
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    found = []
    for name in names:
        book = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))
        parameters = (cv2.aruco.DetectorParameters() if hasattr(cv2.aruco, 'ArucoDetector')
                      else cv2.aruco.DetectorParameters_create())
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        if hasattr(cv2.aruco, 'ArucoDetector'):
            corners, ids, _ = cv2.aruco.ArucoDetector(book, parameters).detectMarkers(gray)
        else:
            corners, ids, _ = cv2.aruco.detectMarkers(gray, book, parameters=parameters)
        if ids is None:
            continue
        for points, identity in zip(corners, ids.ravel()):
            if marker_id is not None and int(identity) != marker_id:
                continue
            points = np.asarray(points, dtype=np.float32).reshape(4, 2)
            found.append({'dictionary': name, 'marker_id': int(identity),
                          'corners': points.tolist(),
                          'area': abs(float(cv2.contourArea(points)))})
    return sorted(found, key=lambda item: (-item['area'], item['dictionary'], item['marker_id']))


def plane_transform(target):
    import cv2
    import numpy as np
    # Clockwise image corners -> a right-handed floor plane, viewed from above.
    square = np.float32([[-.5, .5], [.5, .5], [.5, -.5], [-.5, -.5]])
    return cv2.getPerspectiveTransform(np.float32(target['corners']), square)


def project_points(target, points):
    import cv2
    import numpy as np
    return cv2.perspectiveTransform(np.float32([points]), plane_transform(target))[0]


def front_angle(target, image_point):
    x, y = project_points(target, [image_point])[0]
    return math.atan2(float(y), float(x))


def parking_error(target, observed):
    import numpy as np
    points = project_points(target, observed['corners'])
    x, y = map(float, points.mean(axis=0))
    edge = points[1] - points[0]
    marker_yaw = math.atan2(float(edge[1]), float(edge[0]))
    desired_yaw = target['forward_yaw']
    robot_yaw = wrap(marker_yaw + desired_yaw)
    c, s = math.cos(robot_yaw), math.sin(robot_yaw)
    result = {'x_marker_widths': x, 'y_marker_widths': y,
              'distance_marker_widths': math.hypot(x, y),
              'robot_yaw': robot_yaw, 'target_yaw': desired_yaw,
              'yaw_error': wrap(desired_yaw-robot_yaw),
              'forward_error_marker_widths': -c*x-s*y,
              'left_error_marker_widths': s*x-c*y}
    if target.get('marker_size_mm'):
        result.update(distance_mm=math.hypot(x, y)*target['marker_size_mm'],
                      forward_error_mm=result['forward_error_marker_widths']*target['marker_size_mm'],
                      left_error_mm=result['left_error_marker_widths']*target['marker_size_mm'])
    return result


def rotate(x, y, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return c*x-s*y, s*x+c*y


def camera_odom_goal(target, marker, geometry, odom):
    """Transfer a taught marker pose into odom, including its lever arm to base."""
    observed = parking_error(target, marker)
    scale = geometry['marker_size_mm']/1000.
    dx, dy = (v/1000. for v in geometry['base_to_marker_mm'])
    current_offset = rotate(dx, dy, observed['robot_yaw'])
    goal_offset = rotate(dx, dy, observed['target_yaw'])
    delta = [-observed['x_marker_widths']*scale+current_offset[0]-goal_offset[0],
             -observed['y_marker_widths']*scale+current_offset[1]-goal_offset[1]]
    x, y = rotate(*delta, odom['yaw']-observed['robot_yaw'])
    return {'x': odom['x']+x, 'y': odom['y']+y,
            'yaw': wrap(odom['yaw']+observed['yaw_error'])}


class OdomParking:
    """Reverse, observe, follow Nav2 docking curvature, verify and retry."""
    def __init__(self, target, geometry, control, observation, *, start_at_observation=False):
        self.target, self.geometry, self.control = target, geometry, control
        self.retreat_m = observation['retreat_m']
        self.goal, self.last_camera_at = None, None
        self.phase, self.phase_start, self.phase_since = 'reverse_observe', None, 0.
        if start_at_observation:
            self.phase, self.phase_since = 'observe', time.monotonic()
        self.attempt = 0
        self.verification_source = None

    def update(self, odom, marker=None, now=None):
        now = time.monotonic() if now is None else now
        phase = self.phase
        source = 'odom' if odom else 'waiting_for_odom'
        error = None
        command = {'linear': 0., 'angular': 0., 'aligned': False}
        if odom is not None:
            pose = odom['pose']
            scale = self.geometry['marker_size_mm']/1000.
            position_tolerance = self.control['position_tolerance_mm']/1000.
            yaw_tolerance = math.radians(self.control['yaw_tolerance_deg'])
            vmax, wmax = self.control['linear_speed_mps'], self.control['angular_speed_rps']
            heading_gain = self.control['heading_gain']

            def turn(angle):
                return max(-wmax, min(wmax, heading_gain*wrap(angle)))

            def stop_at(next_phase):
                self.phase, self.phase_since = next_phase, now

            # Only stationary observation phases are allowed to change the goal.
            if phase in ('observe', 'verify'):
                source = 'waiting_for_stationary_observation'
                if now-self.phase_since >= self.control.get('observation_settle_s', .25):
                    if marker is not None:
                        self.goal = camera_odom_goal(self.target, marker, self.geometry, pose)
                        self.last_camera_at = time.time()
                        source = 'camera+odom'
                    elif phase == 'verify':
                        source = 'odom'
                    else:
                        source = 'waiting_for_marker'
                    if phase == 'observe' and marker is not None:
                        self.attempt += 1
                        self.verification_source = None
                        stop_at('advance')
                    if phase == 'verify':
                        self.verification_source = source

            if phase == 'reverse_observe':
                if self.phase_start is None:
                    self.phase_start = dict(pose)
                start = self.phase_start
                progress = -rotate(pose['x']-start['x'], pose['y']-start['y'], -start['yaw'])[0]
                remaining = self.retreat_m-progress
                if remaining <= 0:
                    stop_at('observe')
                else:
                    command.update(linear=-vmax,
                                   angular=turn(start['yaw']-pose['yaw']))

        if odom is not None and self.goal is not None:
            pose = odom['pose']
            x, y = (pose[k]-self.goal[k] for k in ('x', 'y'))
            forward, left = rotate(-x, -y, -pose['yaw'])
            along, lateral = rotate(-x, -y, -self.goal['yaw'])
            error = {'x_marker_widths': x/scale, 'y_marker_widths': y/scale,
                     'distance_marker_widths': math.hypot(x, y)/scale,
                     'robot_yaw': pose['yaw'], 'target_yaw': self.goal['yaw'],
                     'yaw_error': wrap(self.goal['yaw']-pose['yaw']),
                     'distance_mm': math.hypot(x, y)*1000,
                     'forward_error_mm': forward*1000, 'left_error_mm': left*1000}
            if phase == 'advance':
                # Stop at the real goal; the controller aims beyond it to avoid
                # vanishing approach speed and the goal's polar singularity.
                if along <= 0 or (math.hypot(x, y) <= position_tolerance and
                                  abs(error['yaw_error']) <= yaw_tolerance):
                    stop_at('verify')
                else:
                    offset = self.control['virtual_goal_offset_mm']/1000.
                    dx, dy = rotate(offset, 0., self.goal['yaw'])
                    gx, gy = rotate(-x+dx, -y+dy, -pose['yaw'])
                    linear, angular = docking_velocity(gx, gy, error['yaw_error'], vmax, wmax)
                    command.update(linear=linear, angular=angular)
            elif phase == 'align_heading':
                # Hold the last stationary camera goal while turning in place.
                if abs(error['yaw_error']) <= yaw_tolerance:
                    stop_at('verify')
                else:
                    command['angular'] = turn(error['yaw_error'])
            elif phase == 'verify' and now-self.phase_since >= self.control.get('observation_settle_s', .25):
                if math.hypot(x, y) <= position_tolerance and abs(error['yaw_error']) <= yaw_tolerance:
                    stop_at('aligned')
                    command['aligned'] = True
                elif abs(lateral) <= position_tolerance and abs(error['yaw_error']) > yaw_tolerance:
                    stop_at('align_heading')
                elif along > 0 and abs(lateral) <= position_tolerance and abs(error['yaw_error']) <= yaw_tolerance:
                    # Re-observation can reveal a shortfall despite odom arrival.
                    # Keep the corrected goal and finish this approach in place.
                    stop_at('advance')
                else:
                    self.phase_start = None
                    stop_at('reverse_observe')
            elif phase == 'aligned':
                command['aligned'] = True
        return {'error': error, 'command': command, 'control_source': source,
                'odom': odom, 'odom_goal': self.goal, 'last_camera_at': self.last_camera_at,
                'parking_phase': self.phase, 'attempt': self.attempt,
                'verification_source': self.verification_source}


class ParkingOdometry:
    """Read only odom -> base TF in a dedicated ROS context, independently of video."""
    def __init__(self, profile):
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from tf2_ros import Buffer, TransformListener
        self.rclpy, self.profile = rclpy, profile
        self.context = Context()
        self.context.init(args=[], domain_id=profile['domain_id'])
        number = profile['robot_id'].split('-')[-1]
        self.node = Node(f'cartrina_p{number}_parking_odom', context=self.context)
        self.executor = SingleThreadedExecutor(context=self.context)
        self.executor.add_node(self.node)
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self.node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()

    def snapshot(self):
        from .pinky import pose_values
        try:
            t = self.buffer.lookup_transform(self.profile.get('odom_frame', 'odom'),
                                            self.profile['base_frame'], self.rclpy.time.Time())
        except Exception:
            return None
        pose = type('Pose', (), {'position': t.transform.translation, 'orientation': t.transform.rotation})()
        return {'pose': pose_values(pose), 'frame_id': t.header.frame_id,
                'base_frame': t.child_frame_id,
                'observed_at': t.header.stamp.sec+t.header.stamp.nanosec/1e9}

    def close(self):
        self.executor.shutdown()
        self.thread.join()
        self.node.destroy_node()
        self.context.shutdown()


class ParkingDrive(ParkingOdometry):
    """Use the same local odom input for camera-assisted final parking."""
    def __init__(self, profile, cancelled=None):
        from geometry_msgs.msg import Twist
        from std_msgs.msg import String
        from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
        super().__init__(profile)
        self.twist_type, self.string_type = Twist, String
        number = profile['robot_id'].split('-')[-1]
        self.velocity = self.node.create_publisher(Twist, f'/cartrina/p{number}/parking_cmd_vel', 10)
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                         reliability=ReliabilityPolicy.RELIABLE)
        self.source = self.node.create_publisher(String, f'/cartrina/p{number}/control_source', qos)
        print('영상 주차 명령 중계 연결 대기...', flush=True)
        while not self.velocity.get_subscription_count() or not self.source.get_subscription_count():
            if cancelled is not None and cancelled.is_set():
                super().close()
                raise RuntimeError('영상 주차 연결 대기 중 명령 취소')
            time.sleep(.05)
        self.source.publish(String(data='parking'))
        time.sleep(.1)

    def move(self, linear=0., angular=0.):
        value = self.twist_type()
        value.linear.x, value.angular.z = float(linear), float(angular)
        self.velocity.publish(value)

    def close(self):
        self.move()
        time.sleep(.1)
        self.source.publish(self.string_type(data='nav2'))
        time.sleep(.1)
        super().close()


class ParkingRecord:
    def __init__(self, root, robot, zone, mode):
        from robot_gateway.recording import VideoRecorder
        stamp = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')
        self.directory = Path(root)/f'{stamp}-{robot}-{zone}-{mode}-{uuid.uuid4().hex[:6]}'
        self.directory.mkdir(parents=True)
        self.events = (self.directory/'events.jsonl').open('w', buffering=1)
        self.video = VideoRecorder(self.directory, fps=10, prefix='parking')
        self.result = {'robot': robot, 'zone': zone, 'mode': mode,
                       'started_at': time.time(), 'status': 'running',
                       'physical_parking_confirmed': False,
                       'physical_loading_confirmed': False}

    def event(self, **values):
        self.events.write(json.dumps({'time': time.time(), **values}, ensure_ascii=False)+'\n')

    def frame(self, frame):
        self.video.offer('parking', frame)

    def close(self, status, **details):
        from robot_gateway.hardware.pinky import atomic_json
        self.result.update(status=status, ended_at=time.time(), **details)
        video = self.video.close()
        self.result.update(video=video, result_file=str(self.directory/'result.json'))
        self.events.close()
        atomic_json(self.directory/'result.json', self.result)
        return self.result
