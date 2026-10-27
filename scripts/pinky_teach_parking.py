"""Pinky keyboard parking teaching on the control laptop; does not change route goals.

Run from /home/noma/dev_ws/kernel-robot-repo-3:
  source /opt/ros/jazzy/setup.bash
  python3 -m scripts.pinky_teach_parking
  python3 -m scripts.pinky_teach_parking --list

W/S: forward/reverse, A/D: turn (repeat/hold to move), Space: stop.
1/2/3: choose A/B/C, Enter: stop then record map->base_footprint, Q: exit.
The selected robot drive relay forwards /cmd_vel.
No Nav2 goal or robot-arm command is sent by this tool.
"""
import argparse
import curses
import json
import math
from pathlib import Path
import threading
import time

from robot_gateway.hardware.pinky import atomic_json, load_profile, map_signature, pose_values

ZONES = {'1': ('load-a', 'A 적재'), '2': ('load-b', 'B 적재'), '3': ('handoff', 'C 하역')}
DEFAULT_OUTPUT = 'runtime/field/pinky-p1-taught-parking.json'


def read_saved(path):
    return json.loads(Path(path).read_text()) if Path(path).is_file() else {'goals': {}}


def save_parking(path, profile, signature, zone, pose, pose_stamp):
    identity = {'robot_id': profile['robot_id'], 'physical_id': profile.get('physical_id'),
                'frame_id': profile['frame_id'], 'base_frame': profile['base_frame'],
                'map_sha256': signature}
    data = read_saved(path)
    if data['goals'] and any(data.get(k) != v for k, v in identity.items()):
        raise ValueError('기존 저장 파일의 로봇·지도·좌표계가 다릅니다. --output으로 새 파일을 지정하세요.')
    data.update(schema_version=1, source='operator_keyboard_teaching', **identity)
    data['goals'][zone] = {'arrival': dict(pose), 'recorded_at': time.time(),
                           'pose_stamp': pose_stamp}
    atomic_json(path, data)
    return data


def list_saved(path):
    data = read_saved(path)
    print(f'저장 파일: {path}')
    for zone, label in ZONES.values():
        saved = data['goals'].get(zone)
        if saved:
            p = saved['arrival']
            print(f"{label}: x={p['x']:.6f}, y={p['y']:.6f}, "
                  f"yaw={p['yaw']:.6f} rad ({math.degrees(p['yaw']):.2f}°)")
        else:
            print(f'{label}: 미저장')


class Teacher:
    def __init__(self, profile):
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import OccupancyGrid
        from tf2_ros import Buffer, TransformListener

        self.profile, self.rclpy = profile, rclpy
        self.context = Context()
        self.context.init(args=[], domain_id=profile['domain_id'])
        number = profile['robot_id'].split('-')[-1]
        self.node = Node(f'cartrina_p{number}_parking_teacher', context=self.context)
        self.executor = SingleThreadedExecutor(context=self.context)
        self.executor.add_node(self.node)
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self.node)
        self.signature, self.motion, self.last_key = None, (0., 0.), 0.
        self.twist_type = Twist
        self.velocity = self.node.create_publisher(Twist, '/cmd_vel', 10)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.map_sub = self.node.create_subscription(OccupancyGrid, profile['map_topic'], self.on_map, latched)
        self.timer = self.node.create_timer(.1, self.tick)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()

    def on_map(self, message):
        self.signature = map_signature(message)

    def tick(self):
        value = self.twist_type()
        # Terminal key-repeat provides motion while held; Space stops immediately.
        if time.monotonic() - self.last_key < .3:
            value.linear.x, value.angular.z = self.motion
        self.velocity.publish(value)

    def move(self, linear, angular):
        self.motion, self.last_key = (linear, angular), time.monotonic()

    def stop(self):
        self.motion, self.last_key = (0., 0.), 0.
        self.velocity.publish(self.twist_type())

    def pose(self):
        if not self.signature:
            raise RuntimeError('지도 수신 대기')
        t = self.buffer.lookup_transform(self.profile['frame_id'], self.profile['base_frame'],
                                         self.rclpy.time.Time())
        p = type('Pose', (), {'position': t.transform.translation, 'orientation': t.transform.rotation})()
        return pose_values(p), t.header.stamp.sec + t.header.stamp.nanosec/1e9

    def close(self):
        self.node.destroy_timer(self.timer)
        self.stop()
        time.sleep(.1)
        self.executor.shutdown(timeout_sec=2)
        self.thread.join(timeout=2)
        self.node.destroy_node()
        self.context.shutdown()


def teach(screen, profile, output, linear, angular):
    screen.nodelay(True)
    screen.keypad(True)
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    selected, status, pending = '1', 'A/B/C에서 바구니를 맞춘 뒤 Enter로 저장하세요.', None
    saved = read_saved(output)
    mobile = Teacher(profile)

    def line(row, text):
        try:
            screen.addnstr(row, 0, text, max(1, screen.getmaxyx()[1]-1))
        except curses.error:
            pass

    try:
        while True:
            key = screen.getch()
            letter = chr(key).lower() if 0 <= key < 256 else ''
            if letter == 'q':
                break
            movement = {'w': (linear, 0.), 's': (-linear, 0.),
                        'a': (0., angular), 'd': (0., -angular)}
            if letter in movement:
                if pending:
                    pending = None
                    status = '이동 입력으로 저장을 취소했습니다. 정렬 후 Enter를 누르세요.'
                mobile.move(*movement[letter])
            elif letter == ' ':
                mobile.stop()
            elif letter in ZONES:
                mobile.stop()
                selected, pending = letter, None
                status = f'{ZONES[selected][1]} 선택. 정렬 후 Enter로 저장/갱신합니다.'
            elif key in (10, 13, curses.KEY_ENTER):
                mobile.stop()
                pending = (selected, time.monotonic()+1.)
                status = '정지 후 좌표 저장 중...'
            if pending and time.monotonic() >= pending[1]:
                choice, _ = pending
                pending = None
                try:
                    pose, stamp = mobile.pose()
                    saved = save_parking(output, profile, mobile.signature, ZONES[choice][0], pose, stamp)
                    status = f'{ZONES[choice][1]} 저장 완료. 다른 구역을 선택하거나 Q로 종료하세요.'
                except Exception as exc:
                    status = f'저장하지 못했습니다: {str(exc)[:160]}'
            screen.erase()
            line(0, f"주차 좌표 교시 | {profile.get('physical_id', profile['robot_id'])} | Domain {profile['domain_id']}")
            line(2, 'W/S 전진·후진  A/D 회전 | WASD를 반복/길게 눌러 이동 | Space 정지')
            line(3, '1 A 적재 / 2 B 적재 / 3 C 하역 | Enter 현재 구역 저장·갱신 | Q 종료')
            line(4, f'속도: {linear:.3f}m/s, {angular:.3f}rad/s | 선택: {ZONES[selected][1]}')
            try:
                p, _ = mobile.pose()
                line(6, f"현재 map 좌표: x={p['x']:.4f}, y={p['y']:.4f}, yaw={p['yaw']:.5f}rad ({math.degrees(p['yaw']):.2f}°)")
            except Exception as exc:
                line(6, '현재 좌표 수신 대기: '+str(exc)[:130])
            for row, (zone, label) in enumerate(ZONES.values(), 8):
                item = saved['goals'].get(zone)
                if item:
                    p = item['arrival']
                    line(row, f"{label}: x={p['x']:.5f}, y={p['y']:.5f}, yaw={p['yaw']:.6f}rad")
                else:
                    line(row, f'{label}: 미저장')
            line(12, status)
            line(14, '저장 파일: '+str(output))
            screen.refresh()
            time.sleep(.05)
    finally:
        mobile.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--robot', type=str.upper, choices=['P1', 'P2'], default='P1')
    parser.add_argument('--profile', help='기본값: 선택한 로봇의 현장 프로필')
    parser.add_argument('--output', help='기본값: 선택한 로봇의 주차 교시 JSON')
    parser.add_argument('--list', action='store_true', help='저장값만 조회. ROS·모터 연결 없음')
    parser.add_argument('--linear-speed', type=float, default=.02)
    parser.add_argument('--angular-speed', type=float, default=.15)
    args = parser.parse_args()
    args.profile = args.profile or ('runtime/field/pinky-mobile-p2.json' if args.robot == 'P2'
                                    else 'runtime/field/pinky-mobile.json')
    args.output = args.output or ('runtime/field/pinky-p2-taught-parking.json' if args.robot == 'P2'
                                  else DEFAULT_OUTPUT)
    if args.list:
        list_saved(args.output)
        return
    profile = load_profile(args.profile)
    try:
        curses.wrapper(teach, profile, args.output, args.linear_speed, args.angular_speed)
    except KeyboardInterrupt:
        pass
    list_saved(args.output)


if __name__ == '__main__':
    main()
