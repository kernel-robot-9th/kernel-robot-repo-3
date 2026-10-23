#!/usr/bin/env python3
"""실기 E0509 직접 티칭 도우미.

핸드가이딩으로 팔을 원하는 자리에 옮긴 뒤 좌표를 읽어 저장한다.

사용법 (ROS_DOMAIN_ID=77 필요):
    python3 teach.py manual          # 핸드가이딩 모드로 전환
    python3 teach.py read            # 현재 TCP/관절각 출력만
    python3 teach.py save <이름>     # 현재 자세를 taught_points.json 에 저장
    python3 teach.py auto            # 자동 모드 복귀 (움직이기 전 필수)
    python3 teach.py list            # 저장된 지점 보기
"""
import json
import os
import sys

import rclpy
from rclpy.node import Node
from dsr_msgs2.srv import GetCurrentPosx, GetRobotMode, SetRobotMode
from sensor_msgs.msg import JointState

NS = "/dsr01/dsr_controller2"
POINTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taught_points.json")
MODE_NAME = {0: "MANUAL(핸드가이딩)", 1: "AUTONOMOUS(자동)", 2: "MEASURE"}


class Teach(Node):
    def __init__(self):
        super().__init__("teach_helper")
        self.posx = self.create_client(GetCurrentPosx, f"{NS}/aux_control/get_current_posx")
        self.getm = self.create_client(GetRobotMode, f"{NS}/system/get_robot_mode")
        self.setm = self.create_client(SetRobotMode, f"{NS}/system/set_robot_mode")
        self.q = None
        self.create_subscription(JointState, "/dsr01/joint_states", self._js, 10)

    def _js(self, m):
        d = dict(zip(m.name, m.position))
        if "joint_1" in d:
            self.q = [d[f"joint_{i}"] for i in range(1, 7)]

    def call(self, cli, req, timeout=10.0):
        if not cli.wait_for_service(timeout_sec=5.0):
            raise RuntimeError(f"서비스 없음: {cli.srv_name}")
        fut = cli.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=timeout)
        return fut.result()

    def mode(self):
        return self.call(self.getm, GetRobotMode.Request()).robot_mode

    def set_mode(self, m):
        return self.call(self.setm, SetRobotMode.Request(robot_mode=m)).success

    def tcp(self):
        """base 기준 TCP [x,y,z,rx,ry,rz] (mm, deg)."""
        r = self.call(self.posx, GetCurrentPosx.Request(ref=0))
        return list(r.task_pos_info[0].data[:6])

    def joints(self):
        """관절각 (deg)."""
        import math
        for _ in range(40):
            if self.q is not None:
                return [math.degrees(v) for v in self.q]
            rclpy.spin_once(self, timeout_sec=0.1)
        return None


def load():
    if os.path.exists(POINTS):
        with open(POINTS) as f:
            return json.load(f)
    return {}


def show(n):
    p, j = n.tcp(), n.joints()
    print(f"  TCP   x{p[0]:8.2f} y{p[1]:8.2f} z{p[2]:8.2f}  rx{p[3]:8.2f} ry{p[4]:8.2f} rz{p[5]:8.2f}")
    if j:
        print("  관절  " + "  ".join(f"{v:7.2f}" for v in j))
    return p, j


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "read"
    rclpy.init()
    n = Teach()
    try:
        if cmd == "manual":
            ok = n.set_mode(0)
            print(f"MANUAL 전환: {'성공' if ok else '실패'} -> 현재 {MODE_NAME.get(n.mode())}")
            print("티치펜던트의 직접교시 버튼을 누른 채 팔을 원하는 자리로 옮기세요.")
        elif cmd == "auto":
            ok = n.set_mode(1)
            print(f"AUTONOMOUS 전환: {'성공' if ok else '실패'} -> 현재 {MODE_NAME.get(n.mode())}")
        elif cmd == "read":
            print(f"모드: {MODE_NAME.get(n.mode())}")
            show(n)
        elif cmd == "list":
            pts = load()
            if not pts:
                print("저장된 지점 없음")
            for k, v in pts.items():
                p = v["tcp"]
                print(f"  {k:12s} x{p[0]:8.2f} y{p[1]:8.2f} z{p[2]:8.2f}  "
                      f"rx{p[3]:7.2f} ry{p[4]:8.2f} rz{p[5]:7.2f}")
        elif cmd == "save":
            if len(sys.argv) < 3:
                print("이름을 주세요: python3 teach.py save <이름>"); return
            name = sys.argv[2]
            p, j = show(n)
            pts = load()
            pts[name] = {"tcp": p, "joints": j}
            with open(POINTS, "w") as f:
                json.dump(pts, f, indent=2, ensure_ascii=False)
            print(f"'{name}' 저장됨 -> {POINTS}")
        else:
            print(__doc__)
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()
