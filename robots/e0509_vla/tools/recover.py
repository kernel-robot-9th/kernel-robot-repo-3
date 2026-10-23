#!/usr/bin/env python3
"""안전정지(SAFE_STOP) 해제 / 서보 온(SAFE_OFF 복구).

STATE_SAFE_STOP : 충돌 감지 등으로 멈춘 상태 -> CONTROL_RESET_SAFET_STOP(2)
STATE_SAFE_OFF  : 서보가 꺼진 상태(무동작이 이어지면 자동으로 떨어진다)
                  -> CONTROL_RESET_SAFET_OFF(3) = 서보 온
둘 다 STANDBY 로 되돌려야 movel 이 먹는다.

해제 전에 팔에 사람/물체가 끼어있지 않은지 반드시 눈으로 확인할 것.

사용법: python3 recover.py [--force]
    --force 없이 실행하면 상태만 보고 끝난다.
"""
import sys

import rclpy
from rclpy.node import Node
from dsr_msgs2.srv import GetLastAlarm, GetRobotState, SetRobotControl

NS = "/dsr01/dsr_controller2"
STATE = {0: "INITIALIZING", 1: "STANDBY", 2: "MOVING", 3: "SAFE_OFF", 4: "TEACHING",
         5: "SAFE_STOP", 6: "EMERGENCY_STOP", 7: "HOMMING", 8: "RECOVERY",
         9: "SAFE_STOP2", 10: "SAFE_OFF2", 15: "NOT_READY"}
RESET_SAFE_STOP = 2    # CONTROL_RESET_SAFET_STOP : SAFE_STOP -> STANDBY
RESET_SAFE_OFF = 3     # CONTROL_RESET_SAFET_OFF  : SAFE_OFF  -> STANDBY (서보 온)
FIX = {5: (RESET_SAFE_STOP, "안전정지 해제"), 3: (RESET_SAFE_OFF, "서보 온")}


class Recover(Node):
    def __init__(self):
        super().__init__("recover")
        self.st = self.create_client(GetRobotState, f"{NS}/system/get_robot_state")
        self.al = self.create_client(GetLastAlarm, f"{NS}/system/get_last_alarm")
        self.ctl = self.create_client(SetRobotControl, f"{NS}/system/set_robot_control")

    def call(self, cli, req):
        if not cli.wait_for_service(timeout_sec=5.0):
            raise RuntimeError(f"서비스 없음: {cli.srv_name}")
        fut = cli.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=10.0)
        return fut.result()

    def state(self):
        return self.call(self.st, GetRobotState.Request()).robot_state


def main():
    rclpy.init()
    n = Recover()
    try:
        s = n.state()
        print(f"현재 상태: {s} ({STATE.get(s, '?')})")
        a = n.call(n.al, GetLastAlarm.Request()).log_alarm
        print(f"마지막 알람: level={a.level} group={a.group} index={a.index} param={list(a.param)}")

        if s == 1:
            print("이미 STANDBY 입니다. 할 일 없음."); return 0
        if s not in FIX:
            print(f"SAFE_STOP(5)/SAFE_OFF(3) 가 아니라 이 스크립트로는 못 풉니다. "
                  f"티치펜던트에서 확인하세요."); return 1
        ctl, what = FIX[s]
        if "--force" not in sys.argv:
            print(f"\n{what} 하려면 --force 를 붙여 다시 실행하세요.")
            print("그 전에 팔 주변에 끼인 것이 없는지 눈으로 확인할 것.")
            return 0

        ok = n.call(n.ctl, SetRobotControl.Request(robot_control=ctl)).success
        print(f"\n{what} 요청: {'성공' if ok else '실패'}")
        import time
        time.sleep(1.5)
        s2 = n.state()
        print(f"해제 후 상태: {s2} ({STATE.get(s2, '?')})")
        return 0 if s2 == 1 else 1
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    sys.exit(main())
