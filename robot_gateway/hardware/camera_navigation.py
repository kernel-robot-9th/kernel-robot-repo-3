"""Live overhead observations shared by the web server and navigation adapter."""
import json
import math
from pathlib import Path
import socket
import time

ROOT = Path(__file__).resolve().parents[2]
SOCKET = ROOT / 'runtime/field/pinky-overhead/navigation.sock'
CONFIG = ROOT / 'runtime/field/pinky-camera-navigation.json'


def observation(path=SOCKET):
    # A live socket avoids applying a saved pose after the camera has exited.
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(1)
            connection.connect(str(path))
            with connection.makefile('r') as stream:
                return json.loads(stream.readline())
    except (OSError, ValueError):
        return {'running': False, 'robots': {}}


def frame_observation(markers, calibration, robots, transform, observed_at):
    from .overhead import marker_pose
    c, s = math.cos(transform['yaw']), math.sin(transform['yaw'])
    result = {'running': True, 'observed_at': observed_at, 'frame_id': 'map', 'robots': {}}
    for name, robot in robots.items():
        match = next((m for m in markers if m['marker_id'] == robot['marker_id']
                      and m['dictionary'] == robot['dictionary']), None)
        entry = {'visible': bool(match), 'marker_id': robot['marker_id']}
        if match:
            pose = marker_pose(match, calibration, robot)['base_pose']
            if pose is not None:
                dx, dy = pose['x']-transform['x'], pose['y']-transform['y']
                yaw = pose['yaw']-transform['yaw']
                entry.update(map_pose=pose, layout_pose={'x': c*dx+s*dy, 'y': -s*dx+c*dy,
                             'yaw': math.atan2(math.sin(yaw), math.cos(yaw))})
        result['robots']['pinky-'+name[-1]] = entry
    return result


def correct_mobile(mobile, cancelled=None):
    value = observation(mobile.profile['camera_socket'])
    robot = value.get('robots', {}).get(mobile.profile['robot_id'], {})
    pose = robot.get('map_pose') if value.get('running') and robot.get('visible') else None
    if not pose:
        return {'published': False, 'reason': '현재 카메라 관측 없음; 기존 Nav2 추정 사용'}
    publisher = mobile.camera_initial_pose
    deadline = time.monotonic()+1
    while not publisher.get_subscription_count() and time.monotonic()<deadline:
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError('Pinky 명령이 취소되었습니다')
        time.sleep(.02)
    if not publisher.get_subscription_count():
        return {'published': False, 'reason': 'Nav2 /initialpose 구독 미연결; 기존 추정 사용'}
    if cancelled is not None and cancelled.is_set():
        raise RuntimeError('Pinky 명령이 취소되었습니다')
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from rclpy.duration import Duration
    message = PoseWithCovarianceStamped()
    message.header.frame_id = mobile.profile['frame_id']
    # Robot odom timestamps share AMCL's clock even if the notebook clock differs.
    with mobile.data_lock:
        if mobile.last_odom:
            message.header.stamp = mobile.last_odom.header.stamp
    message.pose.pose.position.x, message.pose.pose.position.y = pose['x'], pose['y']
    message.pose.pose.orientation.z = math.sin(pose['yaw']/2)
    message.pose.pose.orientation.w = math.cos(pose['yaw']/2)
    message.pose.covariance[0] = message.pose.covariance[7] = .1**2
    message.pose.covariance[35] = math.radians(10)**2
    publisher.publish(message)
    # Give a short-lived camera-pose CLI time to deliver before destroying its
    # publisher. DDS acknowledgement is not an AMCL application response.
    acked = publisher.wait_for_all_acked(timeout=Duration(seconds=.2))
    return {'published': True, 'transport_acked': acked, 'topic': '/initialpose',
            'pose': pose, 'observed_at': value['observed_at']}
