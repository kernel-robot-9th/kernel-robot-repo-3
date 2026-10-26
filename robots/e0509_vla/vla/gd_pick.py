#!/usr/bin/env python3
"""게토레이(눕힌 병) 찾기 -> 무게 중심 맞춰 잡기 -> 높은 경로로 바구니에 넣기 (2026-10-26 시험).
병은 로봇 좌우(사진 가로) 방향으로 눕혀 놓는다. 위치·뚜껑 방향은 자유.
  python3 /home/omen/doosan_ws/vla_test/gd_pick.py [--dry]   (--dry: 계산만, 로봇 안 움직임)"""
import sys, time, json, math
from pathlib import Path
import cv2, numpy as np, rclpy
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import depth_tilt as D
from gatorade_vision import find_bottle, px_to_xy
import random_area_check as RA
from path_check import ik

DRY = "--dry" in sys.argv
L_BOTTLE, CAP_TIP = 320.0, 15.0           # 병 길이(뚜껑 포함), 뚜껑 중심 -> 뚜껑 끝
COM_GUESS = 160.0                         # 뚜껑 중심에서 무게 중심 첫 추정 (10-26 시험 144~181)
ZG, LIFT, CUR = 145.0, 20.0, 250   # 10-26: 200 -> 250 (운반 높이로 올리다 빠짐)
ORI = [178.902, -180.0, 178.902]
BASKET_Y = (-675.0, -325.0)               # 바구니 안쪽 y 범위 (90도 돌려 놓은 뒤, 긴 변 36cm, 여유 5mm)
MAN = 0.022

def snap():
    for _ in range(10):
        cap = cv2.VideoCapture("/dev/video8", cv2.CAP_V4L2); cap.set(3, 640); cap.set(4, 480)
        fr = [cap.read() for _ in range(26)]; cap.release(); ok, f = fr[-1]
        if ok and f is not None: return f
        time.sleep(1.5)
    raise SystemExit("카메라 실패")

def body_dir(img, cap_px):
    """뚜껑 양옆 띠에서 병 윤곽(가로 선) 많은 쪽 = 몸통. +1: 사진 오른쪽(+y), -1: 왼쪽(-y)"""
    e = cv2.Canny(cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0), 40, 120)
    from gatorade_vision import ROI as GR
    e[:, :GR[0] + 8] = 0; e[:, GR[1] - 8:] = 0   # 10-26: 작업대 밖(가방·의자·바구니) 윤곽이 섞여 방향을 거꾸로 봄 -> 작업대 안만
    cx, cy = int(cap_px[0]), int(cap_px[1]); band = e[max(0, cy - 30):cy + 30]
    l = int(np.count_nonzero(band[:, max(0, cx - 160):max(0, cx - 25)])); r = int(np.count_nonzero(band[:, cx + 25:cx + 160]))
    return (1 if r > l else -1), l, r

def axis_dir_ray(img, cap_px):
    """10-26: 각도·위치 상관없이 병 방향. 뚜껑에서 0~358도 모든 방향으로 길이 135px·폭 24px 띠를 그어
    빈 작업대(table_empty.jpg)와 달라진 픽셀이 가장 꽉 찬 방향 = 몸통. 옆 물건은 뚜껑에서 일직선으로 안 이어지면 점수가 낮음."""
    bg = cv2.imread(str(HERE / "table_empty.jpg"))
    if bg is None: return None
    diff = cv2.absdiff(cv2.GaussianBlur(img, (5, 5), 0), cv2.GaussianBlur(bg, (5, 5), 0)).max(axis=2)
    m = (diff > 22).astype(np.float32)
    cx, cy = cap_px
    # 10-26: 옆에 붙은 새우깡 봉지(불투명)가 투명한 병보다 점수가 높아 봉지를 집음 -> 다른 상품 자리를 먼저 지운다
    try:
        from bag_vision import bag_region, set_object
        set_object("shrimp"); f2 = img.copy()
        for _ in range(3):
            br = bag_region(f2)
            if br is None: break
            mk = cv2.dilate(br[0], np.ones((9, 9), np.uint8)) > 0
            if np.hypot(*(np.array(br[2]) - [cx, cy])) < 25: break      # 뚜껑 자체(빨강)는 지우지 않음
            m[mk] = 0; f2[mk] = 0
        from choco_vision import find_box
        bx = find_box(img)
        if bx is not None and np.hypot(bx[0] - cx, bx[1] - cy) > 60: cv2.circle(m, (int(bx[0]), int(bx[1])), 45, 0.0, -1)
        from ramen_vision import find_cup
        cu = find_cup(img, start_pose=False)
        if cu is not None and np.hypot(cu[0] - cx, cu[1] - cy) > 60: cv2.circle(m, (int(cu[0]), int(cu[1])), 60, 0.0, -1)
    except Exception as ex: print("     (다른 상품 지우기 실패)", ex, flush=True)
    H_, W_ = m.shape; best = None
    ts = np.arange(25, 160, 3.0); ws = np.arange(-12, 13, 3.0)
    for deg in range(0, 360, 2):
        th = math.radians(deg); ux, uy = math.cos(th), math.sin(th)
        X = (cx + ts[:, None] * ux - ws[None, :] * uy).round().astype(int); Y = (cy + ts[:, None] * uy + ws[None, :] * ux).round().astype(int)
        ok = (X >= 0) & (X < W_) & (Y >= 0) & (Y < H_)
        if ok.mean() < 0.8: continue
        sc = float(m[Y[ok], X[ok]].mean())
        if best is None or sc > best[0]: best = (sc, ux, uy)
    if best is None or best[0] < 0.35: print(f"     병 몸통 방향 못 찾음 (최고 점수 {0 if best is None else best[0]:.2f})", flush=True); return None
    sc, ux, uy = best
    # 병 폭(약 45px)이 띠보다 넓어 +-20도가 다 꽉 참 -> 그 방향 +-30도 부채꼴 안 병 픽셀의 평균 방향(병은 축 대칭) = 축
    ys_, xs_ = np.nonzero(m > 0); vx_, vy_ = xs_ - cx, ys_ - cy; r_ = np.hypot(vx_, vy_)
    sel = (r_ > 20) & (r_ < 170) & ((vx_ * ux + vy_ * uy) > np.cos(math.radians(30)) * r_)
    if sel.sum() > 200:
        mv_ = np.array([(vx_[sel] / r_[sel]).mean(), (vy_[sel] / r_[sel]).mean()]); mv_ /= np.linalg.norm(mv_); ux, uy = float(mv_[0]), float(mv_[1])
    # 10-26 추측 금지: 그 방향으로 병 픽셀이 이어지는 길이가 병(뚜껑에서 약 150px)과 맞아야 함
    run = 0
    for t_ in range(25, 260, 5):
        X_ = (cx + t_ * ux - np.arange(-12, 13, 3) * uy).round().astype(int); Y_ = (cy + t_ * uy + np.arange(-12, 13, 3) * ux).round().astype(int)
        ok_ = (X_ >= 0) & (X_ < W_) & (Y_ >= 0) & (Y_ < H_)
        if not ok_.any() or m[Y_[ok_], X_[ok_]].mean() < 0.3:
            run += 1
            if run >= 3: L_px = t_ - 10; break
        else: run = 0
    else: L_px = 260
    print(f"     뚜껑에서 몸통 방향 점수 {sc:.2f}, 이어진 길이 {L_px}px", flush=True)
    if sc < 0.6 or not (90 <= L_px <= 200): print("     병 모양과 안 맞음 -> 추측하지 않고 멈춤", flush=True); return None
    a = np.array(px_to_xy([cx, cy])); b = np.array(px_to_xy([cx + 60 * ux, cy + 60 * uy]))
    u = (b - a) / np.linalg.norm(b - a); d = 1 if u[1] > 0 else -1
    return u, d, math.degrees(math.atan2(u[0], abs(u[1])))

def axis_dir_bg(img, cap_px):
    """10-26: 빈 작업대 사진(table_empty.jpg, 팔은 시작 자세)과 비교해 병 영역을 찾고 주성분으로 병 축 방향(픽셀) -> (단위벡터 작업대 좌표, 몸통 방향 d, 각도)"""
    bg = cv2.imread(str(HERE / "table_empty.jpg"))
    if bg is None: return None
    diff = cv2.absdiff(cv2.GaussianBlur(img, (5, 5), 0), cv2.GaussianBlur(bg, (5, 5), 0)).max(axis=2)
    m = (diff > 28).astype(np.uint8)
    from gatorade_vision import ROI as GR
    roi = np.zeros_like(m); roi[max(GR[2], 140):GR[3], GR[0] + 6:GR[1] - 6] = 1; m &= roi   # 작업대 안, 시작 자세 그리퍼 아래만
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)); m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(m)
    if n <= 1: return None
    cx, cy = cap_px
    i = min(range(1, n), key=lambda j: np.hypot(*(cen[j] - [cx, cy])) if st[j, 4] > 800 else 1e9)
    if st[i, 4] < 800: return None
    ys, xs = np.nonzero(lab == i); P = np.c_[xs, ys].astype(np.float64); c = P.mean(0)
    w, v = np.linalg.eigh(np.cov((P - c).T)); ax = v[:, np.argmax(w)]        # 픽셀에서 긴 방향
    # 10-26: 사람 손·그림자가 섞이면 엉뚱한 방향(12도 병을 88도로) -> 병다운지 검사: 길이 110~210px, 길이/폭 2.2 이상
    proj = (P - c) @ ax; L_px = float(proj.max() - proj.min()); ratio = math.sqrt(max(w.max(), 1e-6) / max(w.min(), 1e-6))
    if not (110.0 <= L_px <= 210.0 and ratio >= 2.2):
        print(f"     빈 작업대 비교 결과가 병 같지 않음 (길이 {L_px:.0f}px, 길이/폭 {ratio:.1f}) -> 윤곽선 방향 사용", flush=True); return None
    if np.dot(c - [cx, cy], ax) < 0: ax = -ax                                  # 뚜껑 -> 몸통 방향
    a = np.array(px_to_xy([cx, cy])); b = np.array(px_to_xy([cx + 60 * ax[0], cy + 60 * ax[1]]))
    u = (b - a) / np.linalg.norm(b - a); d = 1 if u[1] > 0 else -1
    return u, d, math.degrees(math.atan2(u[0], abs(u[1])))

def axis_dir(img, cap_px, d):
    """병이 누운 방향(작업대 좌표 단위벡터, 몸통 쪽). 뚜껑에서 몸통 쪽 띠의 윤곽점을 작업대 좌표로 바꿔 직선 맞춤 (윤곽 위·아래 선의 가운데 = 병 축)"""
    e = cv2.Canny(cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0), 40, 120)
    from gatorade_vision import ROI as GR
    cx, cy = int(cap_px[0]), int(cap_px[1])
    xs = range(cx + 30, cx + 170) if d > 0 else range(cx - 170, cx - 30)
    pts = [(x, y) for x in xs if GR[0] + 8 <= x < GR[1] - 8 for y in range(max(GR[2], cy - 45), min(GR[3], cy + 45)) if e[y, x]]
    if len(pts) < 40: return np.array([0.0, float(d)]), 0.0
    P = np.array([px_to_xy(p) for p in pts], np.float32)
    vx, vy, _, _ = cv2.fitLine(P, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    u = np.array([vx, vy]); u = u if u[1] * d > 0 else -u
    return u / np.linalg.norm(u), math.degrees(math.atan2(u[0], abs(u[1])))   # 각도: 좌우(y)축에서 앞뒤(x)로 기운 정도

def route_ok(pts):
    q = RA.Q0.copy(); q, _ = ik(q, np.array(pts[0], float), RA.R); worst = 9.0
    for a, b in zip(pts, pts[1:]):
        q, w = RA.seg(q, a, b, 14)
        if w < 0: return w
        worst = min(worst, w)
    return worst

def plan(xg, yg, d):
    """잡은 자리(xg,yg)와 뚜껑 방향 d(-1: 뚜껑이 -y 쪽)로 놓을 자리·경로"""
    a = math.hypot(xg - cap_xy[0], yg - cap_xy[1]) + CAP_TIP; b = L_BOTTLE - a      # 잡은 자리에서 뚜껑 끝까지 a, 바닥 끝까지 b (병 축을 따라, 놓을 땐 손목을 돌려 좌우로 맞춤)
    lo, hi = (BASKET_Y[0] + a, BASKET_Y[1] - b) if d < 0 else (BASKET_Y[0] + b, BASKET_Y[1] - a)
    if lo > hi: return None, f"병이 바구니에 안 들어감 (뚜껑 쪽 {a:.0f} 바닥 쪽 {b:.0f}mm)"
    best = None
    for z in (505, 495, 485, 475, 465, 455, 445):
        for yr in sorted(np.arange(lo, hi + 1, 5.0), key=lambda v: abs(v + 500)):
            for xr in (290, 300, 310):
                head = [(xg, yg, ZG + LIFT), (xg, yg, 445)] if xg <= 600 else [(xg, yg, ZG + LIFT), (xg, yg, 300), (520, yg, 300), (520, yg, 445)]
                pts = head + [(420, -200, 545), (300, -405, 545), (xr, float(yr), z)]
                w = route_ok(pts)
                if w >= MAN: return pts, f"놓는 자리 x{xr} y{yr:.0f} z{z} (경로 여유 {w:.3f}, 뚜껑 쪽 {a:.0f} 바닥 쪽 {b:.0f}mm)"
    return None, "팔이 닿는 놓을 자리 없음"

# ---- 이벤트 (키오스크·트윈: /dsr01/pick/event, object "drink") ----
node = None
if not DRY:
    rclpy.init(); node = rclpy.create_node("gd_pick", namespace="dsr01")
    import DR_init; DR_init.__dsr__id, DR_init.__dsr__model, DR_init.__dsr__node = "dsr01", "e0509", node
    from std_msgs.msg import String as _Str
    _ev = node.create_publisher(_Str, "pick/event", 10); time.sleep(0.5)
def emit(event, **kw):
    if node is None: return
    m = _Str(); d = {"event": event, "object": "drink", "t": time.time()}
    d.update({k: ([round(float(x), 1) for x in v] if hasattr(v, "__len__") and not isinstance(v, str) else (v if isinstance(v, str) else round(float(v), 2))) for k, v in kw.items()})
    m.data = json.dumps(d, ensure_ascii=False); _ev.publish(m); rclpy.spin_once(node, timeout_sec=0.05)
def fail(reason):
    emit("loop_end", reason=reason); print("!!! 멈춤:", reason, flush=True); time.sleep(0.5); raise SystemExit(reason)
emit("retry", attempt=1, tries=1)

# ---- 1. 찾기 ----
img = snap(); r = find_bottle(img)
if r is None: emit("not_found"); fail("작업대에서 게토레이 뚜껑을 못 찾음")
# 10-26: 서 있는 병 -> 위에서 뚜껑이 크게(누우면 ~140px, 서면 ~380px) 보임 -> 밀어서 눕힌 뒤 처음부터 다시 (gd_tip.py)
if r["cap_area"] >= 260:
    if "--tipped" in sys.argv: fail("밀었는데도 병이 서 있음")
    print(f"서 있는 병 (뚜껑 {r['cap_area']}px) -> 밀어서 눕힘", flush=True); emit("tipping")
    import subprocess, os
    tip = [sys.executable, "-u", str(HERE / "gd_tip.py"), str(r["cap_px"][0]), str(r["cap_px"][1])] + (["--dry"] if DRY else [])
    rc = subprocess.run(tip).returncode
    if DRY: raise SystemExit(rc)
    if rc != 0: fail("서 있는 병을 작업대 안에 눕힐 방향이 없거나 밀기 실패")
    time.sleep(1.5); os.execv(sys.executable, [sys.executable, "-u", str(HERE / "gd_pick.py"), "--tipped"])
cap_xy = px_to_xy(r["cap_px"]); d, el, er = body_dir(img, r["cap_px"])   # d: 몸통 방향 (+1 = +y)
if abs(cap_xy[1] + d * COM_GUESS) > 200.0 and abs(cap_xy[1] - d * COM_GUESS) <= 200.0:
    print(f"     몸통 쪽으로 보면 잡을 자리가 작업대 밖 -> 반대쪽이 몸통", flush=True); d = -d   # 병 길이 32cm, 작업대 폭 40cm
cap_dir = -d                                                             # 뚜껑 방향
bgr = axis_dir_ray(img, r["cap_px"])   # 10-26: 띠 방식만. 못 믿으면 예비 방법(윤곽선)으로 추측하지 않고 멈춤 (추측으로 병을 누름)
if bgr is None: fail("병 방향을 확실히 못 잼. 병을 작업대에 다시 놓아 주세요")
U, d2, ang = bgr
d = d2; cap_dir = -d
U_dummy = 0   # 10-26: 병이 비스듬하면 뚜껑에서 좌우로만 16cm 가면 앞뒤로 어긋나 빈손(먼 쪽 구석) -> 병 축을 따라
print(f"병 방향: 좌우에서 {ang:+.0f}도", flush=True)
ALPHA = math.degrees(math.atan2(U[0], U[1])) if abs(U[1]) > 1e-6 else math.copysign(90.0, U[0])   # 병 축 기울기 (화면에서 시계 방향 +)
if ALPHA > 90.0: ALPHA -= 180.0     # 축은 방향이 없으니 -90~90 로
if ALPHA < -90.0: ALPHA += 180.0
if abs(ALPHA) > 95.0: fail(f"병 각도 계산 이상 ({ALPHA:+.0f}도)")
# 10-26: 손목 회전. rx 를 +θ 하면 위에서 볼 때 그리퍼가 반시계로 θ (시작 자세 20도 시험). 병이 시계 방향 α 면 손가락도 시계 방향 α -> rx - α
ORI_G = [ORI[0] - ALPHA, ORI[1], ORI[2]]
# 놓기 전 손목을 되돌리면(rx +ALPHA, 화면 반시계) 병이 좌우로 눕는다. 그때 뚜껑이 +y/-y 어느 쪽인지 (앞뒤로 놓인 병은 y 부호만으론 모름)
_a = math.radians(ALPHA); _v = -U   # 뚜껑 방향
CAPF = 1 if (_v[1] * math.cos(_a) + _v[0] * math.sin(_a)) > 0 else -1
print(f"손목 {-ALPHA:+.0f}도 돌려 병과 직각으로 잡음", flush=True)
yg = cap_xy[1] + U[1] * COM_GUESS; xg = cap_xy[0] + U[0] * COM_GUESS
if not (300 <= xg <= 700 and -220 <= yg <= 220): fail(f"계산한 잡을 자리 x{xg:.0f} y{yg:.0f} 가 작업대 밖 -> 병 방향 측정이 이상함. 병을 다시 놓아 주세요")
print(f"뚜껑 x{cap_xy[0]:.0f} y{cap_xy[1]:.0f}, 몸통은 {'+y(오른쪽)' if d > 0 else '-y(왼쪽)'} (윤곽 왼{el} 오{er}) -> 첫 잡기 x{xg:.0f} y{yg:.0f}", flush=True)
# 10-26: x640 고정 한계 대신 실제 다가가는 길(시작 자세 -> 병 위 -> 잡는 높이)을 계산해서 판단 (다른 상품처럼)
_appr = [(430, 13, 427), (430, yg, 427), (430, yg, 300), (xg, yg, 300), (xg, yg, ZG)] if xg > 600 else [(430, 13, 427), (xg, yg, 427), (xg, yg, ZG)]
_wa = route_ok(_appr) if (330 <= xg <= 700 and -200 <= yg <= 200) else -1.0
print(f"다가가는 길 여유 {_wa:.3f}", flush=True)
if _wa < MAN: fail(f"잡을 자리 x{xg:.0f} y{yg:.0f} 는 수집 범위 밖. 작업대 안쪽으로 옮겨 주세요")
pts, msg = plan(xg, yg, CAPF); print("계획:", msg, flush=True)
if pts is None: fail(msg)
emit("located", xy=[(cap_xy[0] + U[0] * 145.0), (cap_xy[1] + U[1] * 145.0)], angle=float(ALPHA), yaw=math.degrees(math.atan2(U[0], -U[1])))
if DRY: print("(--dry: 여기까지)"); raise SystemExit(0)

# ---- 로봇 ----
from dsr_gripper import gripper_api as G
from std_srvs.srv import SetBool
from dsr_msgs2.srv import MoveLine
mvl = node.create_client(MoveLine, "/dsr01/dsr_controller2/motion/move_line")
def call(cli, req, t=120.0):
    cli.wait_for_service(timeout_sec=5.0); f = cli.call_async(req); rclpy.spin_until_future_complete(node, f, timeout_sec=t); return f.result()
WORI = list(ORI)   # 지금 쓰는 손목 방향
def mv(x, y, z, v, rv=30.0):
    q = MoveLine.Request(); q.pos = [float(x), float(y), float(z)] + WORI; q.vel = [float(v), float(rv)]; q.acc = [2.0 * v, 60.0]; q.ref = 0; q.mode = 0; q.sync_type = 0
    if not call(mvl, q).success: fail(f"이동 실패 x{x:.0f} y{y:.0f} z{z:.0f} (로봇 상태 확인)")
def grip():
    st = G.gripper_state(timeout=2.0); return None if st is None else st["position"]
call(node.create_client(SetBool, "/dsr01/gripper/state_enable"), SetBool.Request(data=True)); time.sleep(1.0)
_g = grip()
if _g is None:   # 10-26: 안전정지 뒤 그리퍼 DRL 이 멈춰 상태 값이 없음 -> 닫히지도 않고 None 으로 오류 종료
    time.sleep(2.0); _g = grip()
    if _g is None: fail("그리퍼 상태를 못 읽음 (그리퍼 노드 재시작 필요)")
if _g < 700: G.gripper_cmd(750, 200); G.gripper_wait(timeout=12.0)

def label_window(h):
    """누운 병 라벨(높이 60~150mm 덩어리) 중심. 10-26: 컵라면(110)·초코송이(85)도 이 높이 -> 덩어리가 여럿이면 모름(None, 그리퍼 값으로만 판단)"""
    x0, x1, y0, y1 = D.ROI; m = np.zeros(h.shape, np.uint8); sub = h[y0:y1, x0:x1]; m[y0:y1, x0:x1] = ((sub > 60) & (sub < 150)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(m)
    big = [j for j in range(1, n) if st[j, 4] > 300]
    if len(big) != 1: print(f"     높이 60~150mm 덩어리 {len(big)}개 -> 라벨 기울기 대신 그리퍼 값으로 판단", flush=True); return None
    return int(cen[big[0]][0]), int(cen[big[0]][1])
def label_h(h, c, rr=10):
    if c is None: return float("nan")
    win = h[c[1] - rr:c[1] + rr, c[0] - rr:c[0] + rr]; v = win[np.isfinite(win)]
    return float(np.percentile(v, 70)) if v.size > 20 else float("nan")

# ---- 깊이로 손가락 자리 확인 (10-26: 병 방향을 잘못 재 손가락이 병 위로 내려가 누름 -> 내려가기 전에 막는다) ----
_KD = np.array([[432.6386, 0, 425.2579], [0, 432.6386, 241.8740], [0, 0, 1.0]])          # 깊이 848x480 (rs-enumerate-devices -c)
_RDC = np.array([[0.999997, 0.000521573, 0.00237656], [-0.000531042, 0.999992, 0.00398554], [-0.00237446, -0.00398679, 0.999989]])
_TDC = np.array([-58.9858, 0.2221, 0.2853])                                              # 깊이 -> 컬러 (mm)
_PC = json.loads((HERE / "cam_pose.json").read_text()); _RC, _ = cv2.Rodrigues(np.array(_PC["rvec"])); _TC = np.array(_PC["tvec"])
def depth_px(xw, yw, zw=0.0):
    pc = _RC @ np.array([xw, yw, zw]) + _TC; pd = _RDC.T @ (pc - _TDC); uv = _KD @ (pd / pd[2]); return int(round(uv[0])), int(round(uv[1]))
def h_at(Hm, xw, yw, r=9):
    u_, v_ = depth_px(xw, yw); win = Hm[max(0, v_ - r):v_ + r, max(0, u_ - r):u_ + r]; vv = win[np.isfinite(win)]
    return float(np.percentile(vv, 80)) if vv.size > 15 else float("nan")
def fingers_clear(xg_, yg_):
    """손가락 두 개가 내려갈 자리(병 축과 직각으로 +-55mm)는 비어 있고(< 40mm), 가운데에는 병이 있어야(> 40mm) 함"""
    n_ = np.array([-U[1], U[0]]); c_ = h_at(HMAP, xg_, yg_)
    f1 = h_at(HMAP, xg_ + n_[0] * 55, yg_ + n_[1] * 55); f2 = h_at(HMAP, xg_ - n_[0] * 55, yg_ - n_[1] * 55)
    print(f"     깊이 확인: 가운데 {c_:.0f}mm, 손가락 자리 {f1:.0f} / {f2:.0f}mm", flush=True)
    if not (np.isfinite(c_) and np.isfinite(f1) and np.isfinite(f2)): return False, "깊이를 못 읽음"
    if f1 > 40.0 or f2 > 40.0: return False, f"손가락 자리에 무언가 있음 ({f1:.0f}/{f2:.0f}mm) -> 병 위로 내려갈 수 있어 멈춤"
    # 10-26: 라벨 없는 투명 몸통(노란 음료)은 깊이가 20~30mm 로 낮게 읽힘 (라벨 쪽 90mm, 빈 작업대 0~6mm) -> 12mm 넘으면 병 있음
    if c_ < 12.0: return False, f"잡을 자리에 병이 없음 (높이 {c_:.0f}mm)"
    return True, ""

# ---- 2. 무게 중심 ----
mv(430, 13, 427, 40)   # 바구니 쪽에서 출발할 수 있으니 높이 유지한 채 시작 자세로 먼저 (바구니 보호)
mv(430, 250, 450, 40); time.sleep(0.5); HMAP = D.heights(D.grab_depth()); mv(430, 13, 427, 40)   # 팔을 작업대 밖(비킨 자리)으로 빼고 깊이 지도
_ok, _why = fingers_clear(xg, yg)
if not _ok: fail(_why)
h = D.heights(D.grab_depth()); C = label_window(h); H0 = label_h(h, C)   # 10-26: 기준 라벨 높이는 팔이 병 위에 없을 때 (그리퍼가 섞여 70mm 로 틀림)
print(f"라벨 기준 높이 {H0:.0f}mm (시작 자세에서)", flush=True)
WORI = list(ORI_G)   # 병 위로 가면서 손목을 병 각도로
mv(430, yg, 427, 40, 15) if xg > 600 else mv(xg, yg, 427, 40, 15)
if xg > 600: mv(430, yg, 300, 30); mv(xg, yg, 300, 30)   # 먼 곳은 z427 에서 수평으로 못 감
mv(xg, yg, 260, 30)
level = False
def bad_label(Hm, lift):
    """10-26: 뚜껑이 로봇 쪽이면 팔이 라벨을 가려 팔 높이(355mm)를 잼 -> 들어 올린 높이 + 4cm 넘거나 기준 - 4cm 밑이면 못 믿음"""
    return (not np.isfinite(Hm)) or Hm > H0 + lift + 40.0 or Hm < H0 - 40.0
blind = [10.0, -20.0, 30.0, -40.0]   # 라벨이 가려졌는데 버티지 못하면 병 축을 따라 번갈아 더듬기 (mm, 뚜껑 쪽 +)
for k in range(1, 7):
    if k > 1:
        _ok, _why = fingers_clear(xg, yg)
        if not _ok: mv(xg, yg, 320, 20); fail(_why)
    mv(xg, yg, 220, 20); mv(xg, yg, ZG, 15)
    G.gripper_cmd(0, CUR); G.gripper_wait(timeout=12.0); time.sleep(1.2); g0 = grip()
    mv(xg, yg, ZG + LIFT, 10); time.sleep(2.0); g1 = grip()
    if g0 is None or g1 is None: mv(xg, yg, 320, 20); fail("그리퍼 상태를 못 읽음 (그리퍼 노드 재시작 필요)")
    if g1 <= 60 or g1 < g0 - 60:
        print(f"[{k}] !! 빠짐 (그리퍼 {g0}->{g1}) -> 위로만", flush=True); emit("grasp_failed", xyz=[xg, yg, ZG], closed_pos=float(g1 or 0)); mv(xg, yg, 320, 20); fail("잡기 실패 (빈손)")
    H1 = label_h(D.heights(D.grab_depth()), C); occl = bad_label(H1, LIFT); drop = None if occl else (H0 + LIFT) - H1   # +: 라벨(뚜껑 쪽)이 처짐
    time.sleep(2.0); g2 = grip()   # 10-26 사용자: 완전 수평이 아니어도 그리퍼에 안정적으로 걸리면 됨 -> 2초 더 버티며 도는지 본다
    stable = g2 is not None and (g1 - g2) < 8.0
    lever = max(60.0, math.hypot(xg - cap_xy[0], yg - cap_xy[1]) - 45.0)   # 잡은 자리 -> 라벨 가운데 (뚜껑에서 약 6cm)
    tilt = None if drop is None else math.degrees(math.atan2(drop, lever))
    emit("tilt", deg=(tilt if tilt is not None else -999.0), grip=float(g2 or 0), occluded=("yes" if drop is None else "no"))
    print(f"[{k}] x{xg:.0f} y{yg:.0f} 그리퍼 {g0:.0f}->{g1:.0f}->{g2:.0f}({'안정' if stable else '도는 중'}) 라벨 {H1:.0f} "
          + ("(팔에 가려 못 믿음 -> 그리퍼 값으로 판단)" if occl else f"(수평 {H0 + LIFT:.0f}) 뚜껑 쪽 처짐 {drop:+.0f}mm"), flush=True)
    if stable and (occl or abs(drop) < 0.8 * LIFT):   # 10-26 사용자: 완전 수평 말고 그리퍼에 걸리면 됨 -> 끝이 바닥에 안 닿으면 바로 5cm 버티기
        mv(xg, yg, ZG + 50.0, 6); time.sleep(3.0); g3 = grip()   # 10-26: 2cm 는 버텼는데 30cm 올리다 빠짐 -> 5cm 에서 3초 더
        H5 = label_h(D.heights(D.grab_depth()), C); occl5 = bad_label(H5, 50.0); drop5 = None if occl5 else (H0 + 50.0) - H5
        hold = g3 is not None and (g2 - g3) < 8.0
        print(f"     5cm 3초: 그리퍼 {g2:.0f}->{g3:.0f} ({'버팀' if hold else '줄어듦'})" + ("" if occl5 else f", 뚜껑 쪽 처짐 {drop5:+.0f}mm"), flush=True)
        if hold and (occl5 or abs(drop5) < 0.8 * 50.0): level = True; break   # 5cm 에서도 끝이 바닥에 안 닿고 그리퍼가 버티면 통과
        if not occl5: drop = drop5
        mv(xg, yg, ZG + LIFT, 6)
    if drop is None:   # 가려져서 기울기를 모름 + 버티지 못함 -> 번갈아 더듬기
        if not blind: break
        step = blind.pop(0)                                                      # +: 뚜껑 쪽
    else:
        mag = 15.0 if abs(drop) > 0.8 * LIFT else float(np.clip(0.6 * abs(drop), 3.0, 15.0))
        step = mag if drop > 0 else -mag                                         # 뚜껑 쪽이 처지면 뚜껑 쪽으로
    mv(xg, yg, ZG + 1.0, 8); G.gripper_cmd(750, 200); G.gripper_wait(timeout=12.0); time.sleep(0.5); mv(xg, yg, 220, 20)
    xg -= step * U[0]; yg -= step * U[1]; shift = step   # 병 축을 따라 (U: 뚜껑 -> 몸통 단위벡터, 앞뒤로 놓인 병도 됨)
    print(f"     뚜껑 쪽으로 {shift:+.0f}mm 옮김 -> x{xg:.0f} y{yg:.0f}", flush=True)
if not level:
    print("수평 못 찾음 -> 내려놓고 끝", flush=True); mv(xg, yg, ZG + 1.0, 8); G.gripper_cmd(750, 200); G.gripper_wait(timeout=12.0); mv(xg, yg, 260, 20); fail("무게 중심을 못 찾음 (병이 손가락에서 돎)")

# ---- 3. 운반 ----
pts, msg = plan(xg, yg, CAPF); print("운반 계획:", msg, flush=True)
if pts is None:
    mv(xg, yg, ZG + 1.0, 8); G.gripper_cmd(750, 200); G.gripper_wait(timeout=12.0); mv(xg, yg, 260, 20); fail(msg)
ref = grip(); emit("grasped", xyz=[xg, yg, ZG], closed_pos=float(ref or 0))
last_tilt = tilt
for p in pts[1:]:
    if tuple(p) == (420, -200, 545) and WORI != ORI:
        # 10-26: 손목을 되돌리며 이동하다 병이 손가락에서 밀림(477 -> 457) -> 제자리에서 따로, 초당 5도로 천천히 되돌림
        cur_p = pts[pts.index(p) - 1]; WORI = list(ORI); mv(*cur_p, 5, 5); time.sleep(1.0)
        g = grip(); print(f"  손목 되돌림 그리퍼 {g:.0f}", flush=True)
        if g < ref - 15: time.sleep(2.0); g2 = grip(); print(f"     2초 뒤 {g2:.0f}", flush=True)
        if g < ref - 15 and g2 is not None and g2 >= g - 3 and g2 > 150: print(f"     자리 잡고 멈춤 -> 새 기준 {g2:.0f}", flush=True); ref = g2; g = g2
        if g < ref - 15: emit("tilt_warn", deg=(last_tilt if last_tilt is not None else -999.0), grip_from=float(ref), grip_to=float(g), where="손목 되돌리는 중"); fail(f"손목을 되돌리다 병이 돌기 시작 (그리퍼 {ref:.0f}->{g:.0f})")
    first = (p == pts[1])
    mv(*p, 8 if first else (10 if p[2] == 300 else (15 if p[2] != 545 else 20)), 10); time.sleep(1.2); g = grip(); print(f"  -> {tuple(round(v) for v in p)} 그리퍼 {g:.0f}", flush=True)
    if g < ref - 15:
        # 10-26: 들어 올리거나 손목을 돌릴 때 병이 손가락 사이에서 한 번 자리를 잡으며 20~30 줄고 그 뒤 안정(2번). 2초 더 안 줄면 새 기준으로 계속
        time.sleep(2.0); g2 = grip(); print(f"     줄어듦 {ref:.0f}->{g:.0f}, 2초 뒤 {g2:.0f}", flush=True)
        if g2 is not None and g2 >= g - 3 and g2 > 150:
            print(f"     자리 잡고 멈춤 -> 새 기준 {g2:.0f} 으로 계속", flush=True); ref = g2; continue
        print("!! 그리퍼 값 감소 -> 그 자리에서 멈춤", flush=True)
        emit("tilt_warn", deg=(last_tilt if last_tilt is not None else -999.0), grip_from=float(ref), grip_to=float(g), where=f"x{p[0]:.0f} y{p[1]:.0f} z{p[2]:.0f}")
        fail(f"운반 중 병이 손가락에서 돌기 시작 (그리퍼 {ref:.0f}->{g:.0f})")
cur = pts[-1]
G.gripper_cmd(750, 200); G.gripper_wait(timeout=12.0); time.sleep(1.0); emit("released", xyz=list(cur), yaw=(0.0 if CAPF > 0 else 180.0))   # 손목을 되돌려 병이 좌우로 누움
left = find_bottle(snap())
if left is not None:
    lxy = np.array(px_to_xy(left["cap_px"]))
    if float(np.hypot(*(lxy - np.array(cap_xy)))) > 60.0:
        # 10-26: 놓은 뒤 다른 상품의 빨간 부분(x492 y-54)을 뚜껑으로 봐 '적재 실패' -> 처음 뚜껑 자리 6cm 안만 본다
        print(f"     놓은 뒤 처음 뚜껑 자리(x{cap_xy[0]:.0f} y{cap_xy[1]:.0f})는 비었음. x{lxy[0]:.0f} y{lxy[1]:.0f} 의 빨강은 다른 물건으로 봄", flush=True)
        left = None
if left is None:
    print("놓음. 확인: 작업대에 병 없음", flush=True); emit("loaded"); emit("done", attempt=1)
else:
    print("놓음. 확인: !! 작업대에 아직 병이 보임", flush=True); emit("not_in_basket", xy=px_to_xy(left["cap_px"])); fail("놓은 뒤에도 작업대에 병이 보임")
