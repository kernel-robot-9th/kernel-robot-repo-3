#!/usr/bin/env python3
"""게토레이 눕힌 병 가운데 집기 시험 (2026-10-26). 지금 x,y 에서 z_grasp 까지 천천히 내려가 닫고, 40mm 들어 버티는지 본다.
놓치면 다시 내려가지 않고 위로만 빠진다. 성공하면 든 채로 멈춤(사람이 확인).
  python3 gd_grasp_test.py <z_grasp> <current>"""
import sys, time
import rclpy
from std_srvs.srv import SetBool
from dsr_msgs2.srv import GetCurrentPosx, MoveLine
from dsr_gripper import gripper_api as G

Z, CUR = float(sys.argv[1]), int(sys.argv[2]); LIFT = float(sys.argv[3]) if len(sys.argv) > 3 else 40.0
S = "/dsr01/dsr_controller2"
rclpy.init(); node = rclpy.create_node("gd_grasp_test", namespace="dsr01")
import DR_init; DR_init.__dsr__id = "dsr01"; DR_init.__dsr__model = "e0509"; DR_init.__dsr__node = node
def call(cli, req, t=60.0):
    cli.wait_for_service(timeout_sec=5.0); f = cli.call_async(req); rclpy.spin_until_future_complete(node, f, timeout_sec=t); return f.result()
posx = node.create_client(GetCurrentPosx, S + "/aux_control/get_current_posx")
mvl = node.create_client(MoveLine, S + "/motion/move_line")
def pose(): return list(call(posx, GetCurrentPosx.Request(ref=0)).task_pos_info[0].data)
def move_z(z, v):
    p = pose(); r = MoveLine.Request(); r.pos = [p[0], p[1], z, p[3], p[4], p[5]]; r.vel = [v, 30.0]; r.acc = [2 * v, 60.0]; r.ref = 0; r.mode = 0; r.sync_type = 0
    return call(mvl, r).success
def grip():
    st = G.gripper_state(timeout=2.0); return None if st is None else st["position"]

call(node.create_client(SetBool, "/dsr01/gripper/state_enable"), SetBool.Request(data=True)); time.sleep(1.0)
print("시작 위치", [round(v) for v in pose()[:3]], "그리퍼", grip(), flush=True)
print("하강 z", Z, move_z(Z, 15.0), flush=True)
G.gripper_cmd(0, CUR); st = G.gripper_wait(timeout=12.0); time.sleep(1.5)
g0 = grip(); print("닫힘", g0, "(완료 판단", None if st is None else st["position"], ")", flush=True)
if g0 is None or g0 <= 40:
    print("빈손 -> 위로만", move_z(Z + 150.0, 30.0), flush=True); sys.exit(1)
print(f"{LIFT:.0f}mm 들기", move_z(Z + LIFT, 10.0), flush=True); time.sleep(3.0)
g1 = grip(); print("든 뒤 그리퍼", g1, flush=True)
if g1 is None or g1 < g0 - 60:
    print("!! 미끄러짐 의심 -> 위로만", move_z(Z + 150.0, 30.0), flush=True); sys.exit(2)
print("버팀: 든 채로 멈춤. 눈으로 확인", flush=True)
