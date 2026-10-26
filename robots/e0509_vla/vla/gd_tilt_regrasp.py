#!/usr/bin/env python3
"""게토레이 기울기 보고 다시 잡기 시험 (2026-10-26).
뚜껑이 -y 쪽(바구니 쪽)으로 눕힌 병. x 고정, y 를 바꿔 가며: 잡기 -> 30mm 들기 -> 깊이로 라벨(뚜껑 쪽 불투명) 높이 ->
수평이면 기준+30mm. 낮으면 뚜껑 쪽이 처짐 -> 잡는 자리를 뚜껑 쪽(-y)으로, 높으면 바닥 쪽(+y)으로 옮겨 다시 잡는다.
놓을 때는 원래 높이로 천천히 내려놓고 연다(쥔 상태). 빠짐(그리퍼 값 급감)이면 다시 내려가지 않고 멈춘다.
  python3 gd_tilt_regrasp.py <x> <y_start> [반복=3]"""
import sys, time, json
import numpy as np, rclpy
from std_srvs.srv import SetBool
from dsr_msgs2.srv import MoveLine
import depth_tilt as D

X, Y0 = float(sys.argv[1]), float(sys.argv[2]); N = int(sys.argv[3]) if len(sys.argv) > 3 else 3
ZG, LIFT, CUR, ORI = 145.0, 30.0, 200, [178.902, -180.0, 178.902]
rclpy.init(); node = rclpy.create_node("gd_tilt", namespace="dsr01")
import DR_init; DR_init.__dsr__id, DR_init.__dsr__model, DR_init.__dsr__node = "dsr01", "e0509", node
from dsr_gripper import gripper_api as G
S = "/dsr01/dsr_controller2"; mvl = node.create_client(MoveLine, S + "/motion/move_line")
def call(cli, req, t=90.0):
    cli.wait_for_service(timeout_sec=5.0); f = cli.call_async(req); rclpy.spin_until_future_complete(node, f, timeout_sec=t); return f.result()
def mv(x, y, z, v):
    r = MoveLine.Request(); r.pos = [x, y, z] + ORI; r.vel = [v, 30.0]; r.acc = [2 * v, 60.0]; r.ref = 0; r.mode = 0; r.sync_type = 0
    return call(mvl, r).success
def grip():
    st = G.gripper_state(timeout=2.0); return None if st is None else st["position"]
call(node.create_client(SetBool, "/dsr01/gripper/state_enable"), SetBool.Request(data=True)); time.sleep(1.0)

def label_window(h):
    """누운 병의 라벨(높이 60~150mm 덩어리) 중심 픽셀"""
    x0, x1, y0, y1 = D.ROI; m = np.zeros(h.shape, bool); sub = h[y0:y1, x0:x1]; m[y0:y1, x0:x1] = (sub > 60) & (sub < 150)
    ys, xs = np.nonzero(m); return int(np.median(xs)), int(np.median(ys))
def label_h(h, c, r=10):
    win = h[c[1] - r:c[1] + r, c[0] - r:c[0] + r]; v = win[np.isfinite(win)]
    return float(np.percentile(v, 70)) if v.size > 20 else float("nan")

# 기준: 누운 병 라벨 높이 (팔은 병 위 z260 에 있어 라벨을 안 가림)
mv(X, Y0, 260, 30); h = D.heights(D.grab_depth()); C = label_window(h); H0 = label_h(h, C)
print(f"기준 라벨 높이 {H0:.0f}mm @px{C}", flush=True)
y = Y0; log = []
for k in range(1, N + 1):
    mv(X, y, 220, 20); mv(X, y, ZG, 15)
    G.gripper_cmd(0, CUR); G.gripper_wait(timeout=12.0); time.sleep(1.2); g0 = grip()
    mv(X, y, ZG + LIFT, 10); time.sleep(2.0); g1 = grip()
    if g1 is None or g1 <= 60 or g1 < g0 - 60:
        print(f"[{k}] !! 빠짐/미끄러짐 (그리퍼 {g0}->{g1}) -> 위로만 빠지고 멈춤", flush=True); mv(X, y, 320, 20); break
    h = D.heights(D.grab_depth()); H1 = label_h(h, C); drop = (H0 + LIFT) - H1
    print(f"[{k}] y{y:.0f} 그리퍼 {g0:.0f}->{g1:.0f}  라벨 {H1:.0f}mm (수평이면 {H0 + LIFT:.0f}) -> 뚜껑 쪽 처짐 {drop:+.0f}mm", flush=True)
    log.append({"y": y, "drop": round(drop, 1), "g": [g0, g1]})
    if abs(drop) < 6.0: print(f"     수평에 가까움 -> 무게 중심 y{y:.0f}", flush=True); break
    # 처짐이 들어 올린 높이에 가까우면 끝이 바닥에 닿아 있어 더 처질 수 없음(포화) -> 크게, 아니면 조금씩
    mag = 15.0 if abs(drop) > 0.8 * LIFT else float(np.clip(0.25 * abs(drop), 3.0, 10.0))
    shift = mag * (-1 if drop > 0 else 1)   # 뚜껑이 -y 쪽
    mv(X, y, ZG + 1.0, 8); G.gripper_cmd(750, 200); G.gripper_wait(timeout=12.0); time.sleep(0.5)   # 내려놓고 열기
    mv(X, y, 220, 20); y += shift
    print(f"     잡는 자리 {shift:+.0f}mm 옮김 -> y{y:.0f}", flush=True)
print("기록", json.dumps(log), flush=True)
