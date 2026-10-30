#!/usr/bin/env python3
"""서 있는 게토레이를 밀어서 눕히기 (2026-10-26). gd_pick.py 가 '서 있음'으로 보면 부른다.
뚜껑 픽셀 + 높이(315mm) -> 카메라 자세(cam_pose.json)로 병 자리 -> 8방향 중 작업대 안에 눕고 팔이 닿는 방향 ->
그리퍼 닫고 병 윗부분 옆에서 밀기 -> 시작 자세로.
  python3 gd_tip.py <뚜껑 px> <뚜껑 py> [--dry]"""
import sys, time, json, math
from pathlib import Path
import cv2, numpy as np
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import random_area_check as RA
from path_check import ik

DRY = "--dry" in sys.argv
CAP_H = 315.0                       # 서 있는 병 뚜껑 윗면 높이 (병 320)
Z = 385.0                           # 밀 때 TCP 높이: 손끝이 병 꼭대기보다 약 7cm 아래 (10-26 실기)
OFF, PUSH = 87.0, 120.0             # 병 중심에서 시작점까지(반지름 47 + 틈 40), 병 중심 너머로 밀기
TABLE = (285.0, 700.0, -235.0, 235.0)
START = (430.0, 13.0, 427.0); LOOK = (430.0, 250.0, 450.0); ORI = [178.902, -180.0, 178.902]; MAN = 0.022

P = json.loads((HERE / "cam_pose.json").read_text()); K = np.array(P["K"]); dist = np.array(P["dist"])
R, _ = cv2.Rodrigues(np.array(P["rvec"])); cam = (-R.T @ np.array(P["tvec"]))
def px_h_to_xy(px, h):
    u = cv2.undistortPoints(np.array([[px]], np.float64), K, dist).ravel(); d = R.T @ np.array([u[0], u[1], 1.0])
    s = (h - cam[2]) / d[2]; return (cam + s * d)[:2]

def route_ok(pts):
    q = RA.Q0.copy(); q, _ = ik(q, np.array(pts[0], float), RA.R); worst = 9.0
    for a, b in zip(pts, pts[1:]):
        q, w = RA.seg(q, a, b, 14)
        if w < 0: return w
        worst = min(worst, w)
    return worst

def snap():
    for _ in range(10):
        c = cv2.VideoCapture("/dev/video8", cv2.CAP_V4L2); c.set(3, 640); c.set(4, 480)
        fr = [c.read() for _ in range(26)]; c.release(); ok, f = fr[-1]
        if ok and f is not None: return f
        time.sleep(1.5)
    return None
BG = cv2.imread(str(HERE / "table_empty.jpg")); OCC = None
def set_image(img):
    """빈 작업대 사진과 다른 픽셀(물건 있음) 지도. 10-26: layout_check.py 가 불러 쓰도록 함수로"""
    global OCC
    OCC = None if img is None or BG is None else (cv2.absdiff(cv2.GaussianBlur(img, (5, 5), 0), cv2.GaussianBlur(BG, (5, 5), 0)).max(axis=2) > 28).astype(np.uint8)
rv, tv = np.array(P["rvec"]), np.array(P["tvec"])
def strip_busy(B, d):
    """10-26: 넘어질 자리(병 바닥에서 9~33cm, 폭 12cm, 높이 0~9cm)에 다른 물건이 있나 -> 빈 작업대 사진과 다른 픽셀 비율"""
    if OCC is None: return 0.0
    occ = OCC.copy()
    # 10-26: 서 있는 병 자신(키 33cm)이 카메라에서 로봇 쪽으로 기울어 보여 띠에 12% 걸림 -> 병 원기둥(반지름 6cm)이 찍히는 자리를 뺀다
    cyl = [[B[0] + 60 * math.cos(a_), B[1] + 60 * math.sin(a_), z_] for a_ in np.linspace(0, 2 * math.pi, 16, endpoint=False) for z_ in (0.0, 335.0)]
    cp, _ = cv2.projectPoints(np.array(cyl, np.float64), rv, tv, K, dist); cv2.fillConvexPoly(occ, cv2.convexHull(cp[:, 0].astype(np.int32)), 0)
    n = np.array([-d[1], d[0]]); poly = []
    for t_, s_ in ((90, -60), (330, -60), (330, 60), (90, 60)):
        for z_ in (0.0, 90.0): poly.append([*(B + d * t_ + n * s_), z_])
    pp, _ = cv2.projectPoints(np.array(poly, np.float64), rv, tv, K, dist); pp = pp[:, 0].astype(np.int32)
    m = np.zeros_like(OCC); cv2.fillConvexPoly(m, cv2.convexHull(pp), 1)
    return float(occ[m > 0].mean()) if m.any() else 1.0

def plan(B):
    best = None
    for deg in range(0, 360, 45):
        d = np.array([math.cos(math.radians(deg)), math.sin(math.radians(deg))])
        land = B + d * 320.0; S = B - d * OFF; E = B + d * PUSH
        margin = min(land[0] - TABLE[0], TABLE[1] - land[0], land[1] - TABLE[2], TABLE[3] - land[1])
        com = B + d * 150.0   # 10-26: 넘어진 병의 무게 중심 자리 (바닥에서 약 15cm)
        mc = min(com[0] - TABLE[0], TABLE[1] - com[0], com[1] - TABLE[2], TABLE[3] - com[1])
        if margin < -40.0 or mc < 40.0:   # 뚜껑 끝은 4cm 까지 밖으로 나가도 됨, 무게 중심은 안쪽 4cm 이상 (x509 에서 4mm 차이로 빠진 방향이 실제로는 잘 누웠음)
            print(f"     {deg}도: 작업대 밖으로 나감 (뚜껑 끝 {margin:+.0f}mm, 무게 중심 {mc:+.0f}mm)", flush=True); continue
        if com[0] < 400.0:   # 10-26: 1번 칸에서 270도(로봇 쪽)로 밀었더니 굴러서 x287(작업대 끝, 로봇 몸통 앞)에 누워 못 잡음
            print(f"     {deg}도: 무게 중심이 로봇 몸통 쪽(x{com[0]:.0f})에 떨어져 잡기 어려움", flush=True); continue
        busy = strip_busy(B, d)
        if busy > 0.08: print(f"     {deg}도: 넘어질 자리에 물건 있음 ({busy:.0%})", flush=True); continue
        pts = [START, (S[0], S[1], Z + 100), (S[0], S[1], Z), (E[0], E[1], Z), (E[0], E[1], Z + 100)]
        w = route_ok(pts)
        if w < MAN: print(f"     {deg}도: 팔이 닿지 않음 (경로 {w:.3f})", flush=True); continue
        if best is None or margin > best[0]: best = (margin, deg, S, E, w)
    return best


def _main():
    global node
    set_image(snap())
    import rclpy
    if not DRY:
        rclpy.init(); node = rclpy.create_node("gd_tip", namespace="dsr01")
        from std_msgs.msg import String as _Str
        _ev = node.create_publisher(_Str, "pick/event", 10); time.sleep(0.5)
    def emit(event, **kw):   # 10-26 트윈: 서 있음 / 넘어지는 동작
        if node is None: return
        m = _Str(); d = {"event": event, "object": "drink", "t": time.time()}
        d.update({k: ([round(float(x), 1) for x in v] if hasattr(v, "__len__") else round(float(v), 2)) for k, v in kw.items()})
        m.data = json.dumps(d); _ev.publish(m); rclpy.spin_once(node, timeout_sec=0.05)
    cap_px = [float(sys.argv[1]), float(sys.argv[2])]
    B = px_h_to_xy(cap_px, CAP_H)
    print(f"서 있는 병 자리 x{B[0]:.0f} y{B[1]:.0f}", flush=True); emit("standing", xy=B)
    pl = plan(B)
    if pl is None: print("!! 작업대 안에 눕힐 수 있는 방향이 없음", flush=True); sys.exit(2)
    margin, deg, S, E, w = pl
    print(f"밀기 방향 {deg}도 (작업대 끝까지 여유 {margin:.0f}mm, 경로 {w:.3f}): 시작 x{S[0]:.0f} y{S[1]:.0f} -> x{E[0]:.0f} y{E[1]:.0f}", flush=True)
    if DRY: sys.exit(0)

    import DR_init; DR_init.__dsr__id, DR_init.__dsr__model, DR_init.__dsr__node = "dsr01", "e0509", node
    from dsr_gripper import gripper_api as G
    from dsr_msgs2.srv import MoveLine
    mvl = node.create_client(MoveLine, "/dsr01/dsr_controller2/motion/move_line")
    def mv(x, y, z, v):
        q = MoveLine.Request(); q.pos = [float(x), float(y), float(z)] + ORI; q.vel = [float(v), 30.0]; q.acc = [2.0 * v, 60.0]; q.ref = 0; q.mode = 0; q.sync_type = 0
        mvl.wait_for_service(timeout_sec=5.0); f = mvl.call_async(q); rclpy.spin_until_future_complete(node, f, timeout_sec=90.0)
        if not (f.result() and f.result().success): print(f"!! 이동 실패 x{x:.0f} y{y:.0f} z{z:.0f}", flush=True); sys.exit(3)
    G.gripper_cmd(0, 200); G.gripper_wait(timeout=12.0); time.sleep(0.5)       # 손가락을 모아 막대처럼
    mv(*START, 40); mv(S[0], S[1], Z + 100, 30); mv(S[0], S[1], Z, 20)
    emit("tip_push", xy=B, deg=float(deg))
    mv(E[0], E[1], Z, 30)                                                      # 천천히 밀어 넘어뜨림
    mv(E[0], E[1], Z + 100, 30); mv(LOOK[0], LOOK[1], Z + 100, 40); mv(*LOOK, 20)   # 10-26: 누운 병이 시작 자세 그리퍼 밑(로봇 쪽)에 깔려 가려짐 -> 비킨 자리에서 끝내고 gd_pick 이 거기서 찍음
    G.gripper_cmd(750, 200); G.gripper_wait(timeout=12.0)
    print("밀기 끝", flush=True)

node = None
if __name__ == "__main__":
    _main()
