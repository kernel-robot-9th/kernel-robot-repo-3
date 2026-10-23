#!/usr/bin/env python3
"""물체별 그리퍼 힘(전류) 캘리브레이션 — 한 번 실행에 한 전류값으로 1회 시험.

준비: 물체를 작업대에 놓고, 핸드가이딩으로 그리퍼가 물체를 감싸는 자세를 티칭.
    python3 teach.py manual
    (직접교시로 옮긴 뒤)  python3 teach.py save grasp_bottle   # 또는 grasp_shrimp
    python3 teach.py auto

시험:
    python3 grip_calib.py bottle --current 200
    python3 grip_calib.py shrimp --current 80 --no-shake

순서: 현재 자리 수직 상승 -> 열기 -> 물체 위 -> 하강 -> 닫기 -> 들기(+흔들기)
      -> 원위치 하강 -> 놓기 -> 위로 빠지기.
그리퍼 위치로 '빈손(끝까지 닫힘)'과 '들다가 손가락 벌어짐'은 잡지만,
물체가 손가락 사이로 아래로 미끄러지는 건 위치로 안 보인다 -> 눈으로 판정.

전류는 낮게 시작해 올린다. 병(게토레이)은 미끄러지지 않는 최소값, 새우깡은 봉지가
안 찌그러지는 최대값 사이에서 고른다. 최종값은 미끄러짐 한계의 1.3배 정도.
"""
import argparse
import json
import os
import sys
import time

import rclpy

ROBOT_ID, ROBOT_MODEL = "dsr01", "e0509"
POINTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taught_points.json")
OBJ = {"bottle": "grasp_bottle", "shrimp": "grasp_shrimp"}   # bottle = 게토레이 병

APPROACH_Z = 100.0
VEL, ACC = [50.0, 30.0], [100.0, 60.0]       # 일반 이동
LIFT_VEL, LIFT_ACC = [40.0, 30.0], [80.0, 60.0]
SHAKE_MM = 20.0                                # 좌우 흔들기 폭
SHAKE_VEL, SHAKE_ACC = [120.0, 30.0], [400.0, 60.0]
EMPTY_POS = 60.0       # 닫은 뒤 위치가 이 이하면 빈손. 실측: 빈손으로 끝까지 닫으면 29 에서 멈춘다 (750=열림)
SLIP_POS = 8.0         # 들고 나서 위치가 이만큼 넘게 변하면 손가락이 밀린 것
ESCAPE_Z = 50.0        # 실패 시 지금 높이에서 추가로 올라갈 거리 mm

# 원칙: 놓쳤거나 미끄러진 게 보이면 절대 다시 내려가지 않는다. 위로만 빠지고 멈춘 뒤 사람에게 넘긴다.
# (2026-10-12 사고: 전류 100 에서 병이 빠졌는데 원래 높이로 내려가 손가락이 병을 눌러 축2 충돌 -> 비상정지)
MAX_CURRENT = 800      # 안전 상한. 하드웨어 상한을 확인하기 전까지 넘기지 않는다


def up(p, dz):
    return [p[0], p[1], p[2] + dz, p[3], p[4], p[5]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("obj", choices=OBJ.keys())
    ap.add_argument("--current", type=int, required=True)
    ap.add_argument("--lift", type=float, default=80.0, help="들어올릴 높이 mm")
    ap.add_argument("--hold", type=float, default=2.0, help="들고 버틸 시간 s")
    ap.add_argument("--no-shake", action="store_true")
    a = ap.parse_args()
    if not 0 < a.current <= MAX_CURRENT:
        print(f"current 는 1~{MAX_CURRENT}"); return 1

    pts = json.load(open(POINTS))
    key = OBJ[a.obj]
    if key not in pts:
        print(f"'{key}' 티칭이 없습니다. python3 teach.py save {key}"); return 1
    t = pts[key]["tcp"]
    # 핸드가이딩 자세는 수직에서 몇 도 기운다. 기울기만 없애고 손목 회전(yaw)은 살린다.
    # ry=180 근처 ZYZ 오일러: Rz(rx)·Ry(180)·Rz(rz) = Rz(rx - rz)·Ry(180) -> yaw = rx - rz.
    # 눕힌 병은 손가락이 병 길이 방향과 직각이어야 해서 yaw 를 0 으로 덮으면 안 된다.
    yaw = ((t[3] - t[5]) + 180.0) % 360.0 - 180.0
    grasp = [t[0], t[1], t[2], yaw, 180.0, 0.0]

    import DR_init
    DR_init.__dsr__id, DR_init.__dsr__model = ROBOT_ID, ROBOT_MODEL
    rclpy.init()
    node = rclpy.create_node("grip_calib", namespace=ROBOT_ID)
    DR_init.__dsr__node = node
    from DSR_ROBOT2 import movel, posx, get_current_posx, DR_BASE
    from dsr_msgs2.srv import GetRobotState
    from dsr_gripper import gripper_cmd, gripper_open, gripper_wait, gripper_state

    c = node.create_client(GetRobotState, f"/{ROBOT_ID}/dsr_controller2/system/get_robot_state")
    c.wait_for_service(timeout_sec=5.0)
    f = c.call_async(GetRobotState.Request()); rclpy.spin_until_future_complete(node, f, timeout_sec=10)
    if f.result() is None or f.result().robot_state != 1:
        print(f"STANDBY 아님 (state={getattr(f.result(), 'robot_state', None)}). recover.py 확인"); return 1
    if gripper_state(timeout=2.0) is None:
        print("그리퍼 상태 토픽이 없습니다. 새 gripper_service 가 떠 있는지 확인"); return 1

    def mv(p, v=VEL, ac=ACC):
        movel(posx(p), vel=v, acc=ac, ref=DR_BASE)

    print(f"[{a.obj}] 전류 {a.current}  파지점 x{grasp[0]:.1f} y{grasp[1]:.1f} z{grasp[2]:.1f} yaw{yaw:.1f}")
    cur = list(get_current_posx(DR_BASE)[0][:6])
    mv(up(cur, APPROACH_Z) if cur[2] < grasp[2] + APPROACH_Z else cur)
    gripper_open()
    mv(up(grasp, APPROACH_Z))
    mv(grasp)

    st_close = gripper_wait(timeout=12.0) if gripper_cmd(0, a.current) else None   # 전 구간 닫기 실측 7초
    if st_close is None:
        print("닫기 상태를 못 읽음 -> 중단, 그리퍼 열고 빠짐")
        gripper_open(); mv(up(grasp, APPROACH_Z)); return 1
    print(f"  닫은 뒤   위치 {st_close['position']:6.1f}  전류 {st_close['current']:6.0f}")
    if st_close["position"] <= EMPTY_POS:
        print("  => 빈손: 끝까지 닫혔습니다. 위로만 빠지고 멈춤. 파지점 티칭(높이/정렬)을 확인하세요.")
        mv(up(grasp, APPROACH_Z), LIFT_VEL, LIFT_ACC)     # 닫힌 손가락으로 옆으로 움직이지 않고 수직으로만
        return 2

    mv(up(grasp, a.lift), LIFT_VEL, LIFT_ACC)
    time.sleep(a.hold)
    if not a.no_shake:
        lifted = up(grasp, a.lift)
        for dy in (SHAKE_MM, -SHAKE_MM, SHAKE_MM, -SHAKE_MM, 0.0):
            mv([lifted[0], lifted[1] + dy] + lifted[2:], SHAKE_VEL, SHAKE_ACC)
    st_lift = gripper_state(timeout=2.0)
    if st_lift is None:
        print("  => 들고 나서 그리퍼 상태를 못 읽음. 안전하게 위로 빠지고 멈춤.")
        mv(up(grasp, a.lift + ESCAPE_Z), LIFT_VEL, LIFT_ACC)
        return 3
    d = st_lift["position"] - st_close["position"]
    print(f"  들고 나서 위치 {st_lift['position']:6.1f}  변화 {d:+5.1f}")

    if abs(d) > SLIP_POS or st_lift["position"] <= EMPTY_POS:
        # 병이 빠졌거나 돌아갔다. 내려가면 오므라든 손가락이 바닥의 병을 누른다.
        # 일부라도 물고 있을 수 있으니 열지도 않는다. 위로만 빠지고 멈춘다.
        print("  => 미끄러짐/놓침 감지: 내려가지 않고 위로 빠진 뒤 멈춤. 물체 상태를 눈으로 확인하세요.")
        mv(up(grasp, a.lift + ESCAPE_Z), LIFT_VEL, LIFT_ACC)
        return 4

    mv(up(grasp, 3.0), LIFT_VEL, LIFT_ACC)     # 3mm 위에서 놓아 바닥에 내리찍지 않게
    gripper_open()
    mv(up(grasp, APPROACH_Z))
    print("  => 그리퍼 기준 OK. 아래로 미끄러졌는지 / 봉지가 찌그러졌는지는 눈으로 판정하세요.")
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
