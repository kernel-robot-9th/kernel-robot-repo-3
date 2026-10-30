#!/usr/bin/env python3
"""주문 배치 검사·다음 상품 고르기 (2026-10-26). 키오스크가 주문 시작 전과 상품마다 부른다. 로봇은 움직이지 않는다.
카메라 사진 한 장으로
  - 상품마다 위치·팔이 닿는지(vla_run 과 같은 검사)·서 있는 게토레이와 팔 몸체 거리
  - 서 있는 게토레이를 눕힐 방향이 있는지(gd_tip.plan, 다른 상품을 집어 치운 뒤까지 흉내)
를 보고, 끝까지 막히는 상품이 있으면 시작 전에 알려 주고, 없으면 지금 집을 상품을 고른다.
  python3 layout_check.py shrimp choco ramen drink
마지막 줄: LAYOUT_JSON {"next": "drink"|..|null, "order": [...], "problems": ["..."]}"""
import sys, json, math, time, contextlib
from pathlib import Path
import cv2, numpy as np
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))

NAMES = {"shrimp": "새우깡", "choco": "초코송이", "ramen": "컵라면", "drink": "게토레이"}
CLEAR_MM = 200.0     # 팔 몸체 ~ 서 있는 병 최소 거리 (vla_run 과 같게. 10-26 145mm 에서 충돌)
units = [u for u in sys.argv[1:] if not u.startswith("--")]

with contextlib.redirect_stdout(sys.stderr):   # 불러오는 모듈들이 찍는 글은 stderr 로
    _argv = sys.argv; sys.argv = [sys.argv[0]]
    import vla_run as V
    import gd_tip as T
    sys.argv = _argv
    from gatorade_vision import find_bottle
    from fk import Chain, zyz_to_matrix
    from path_check import ik
    import random_area_check as RA

def out(nxt, order, problems):
    print("LAYOUT_JSON " + json.dumps({"next": nxt, "order": order, "problems": problems}, ensure_ascii=False), flush=True); sys.exit(0)

img = T.snap()
if img is None: out(None, [], ["카메라 사진을 못 찍었어요"])

# ---- 서 있는 게토레이 ----
B = None; lying = False
r = find_bottle(img)
if r is not None:
    if r["cap_area"] >= 260: B = T.px_h_to_xy(r["cap_px"], T.CAP_H)
    else: lying = True

# ---- 상품 위치 (같은 상품 여러 개면 모두) ----
CH = [Chain(tip=f"link_{i}") for i in range(2, 7)]; R0 = zyz_to_matrix(0, 180, 0)
def arm_clear(x, y, Bxy):
    """물건 위 z260/200/130 자세의 팔 관절 사이 선분과 서 있는 병 사이 수평 거리 (vla_run 과 같은 계산)"""
    q = RA.Q0.copy(); m = 1e9
    for z in (260.0, 200.0, 130.0):
        q, _ = ik(q, np.array([x, y, z]), R0); P = [c.fk(q)[0] for c in CH]
        for p0, p1 in zip(P, P[1:]):
            for t in np.linspace(0, 1, 30):
                p = p0 + (p1 - p0) * t
                if p[2] <= 380.0: m = min(m, float(math.hypot(p[0] - Bxy[0], p[1] - Bxy[1])))
    return m
def reach_ok(x, y):
    grid = json.loads((HERE / "random_area.json").read_text())
    gx0, gy0 = math.floor(x / 20) * 20, math.floor(y / 20) * 20
    ok = all(grid.get(f"{gx},{gy}", -1) >= 0.02 for gx in (gx0, gx0 + 20) for gy in (gy0, gy0 + 20))
    if not ok:
        with contextlib.redirect_stdout(sys.stderr): ok = RA.route(x, y) >= 0.02
    return ok and V.BOUNDS_X[0] <= x <= V.BOUNDS_X[1] and V.BOUNDS_Y[0] <= y <= V.BOUNDS_Y[1]

items = []   # {"u", "xy", "px", "reach", "clr"}
for u in sorted(set(units) - {"drink"}):
    f2 = img.copy()
    for _ in range(units.count(u) + 1):
        p = []; xy = V.cam_locate(u, f2, occl=True, px_out=p)
        if xy is None or not p: break
        items.append({"u": u, "xy": [float(xy[0]), float(xy[1])], "px": [float(p[0]), float(p[1])], "reach": reach_ok(float(xy[0]), float(xy[1]))})
        cv2.circle(f2, (int(p[0]), int(p[1])), V._ERASE_PX.get(u, 60), (255, 255, 255), -1)
for it in items: it["clr"] = arm_clear(*it["xy"], B) if B is not None else 1e9
print("서 있는 게토레이:", None if B is None else [round(float(v)) for v in B], " 누운 게토레이:", lying, file=sys.stderr)
for it in items: print(f"  {it['u']} x{it['xy'][0]:.0f} y{it['xy'][1]:.0f} 닿음={it['reach']} 팔몸체={it['clr']:.0f}", file=sys.stderr)

problems = []
# 끝까지 안 되는 것: 팔이 안 닿는 자리
for it in items:
    if not it["reach"]:
        problems.append(f"{NAMES[it['u']]}(x{it['xy'][0]:.0f} y{it['xy'][1]:.0f})가 로봇이 닿기 어려운 곳이에요. 작업대 가운데 쪽으로 옮겨 주세요")

# ---- 순서 흉내: 게토레이를 눕힐 수 있으면 먼저(장애물 없앰), 아니면 팔에 안 걸리는 상품부터 집어 치우며 다시 본다 ----
T.set_image(img); occ0 = None if T.OCC is None else T.OCC.copy()
def tip_ok(picked):
    if T.OCC is None: return True
    T.OCC = occ0.copy()
    for it in picked: cv2.circle(T.OCC, (int(it["px"][0]), int(it["px"][1])), V._ERASE_PX.get(it["u"], 60) + 25, 0, -1)   # 집어 간 상품 자리는 빈 것으로
    with contextlib.redirect_stdout(sys.stderr): return T.plan(B) is not None
need = list(units); left = [it for it in items if it["reach"]]; picked = []; order = []; Bnow = B
while need:
    if "drink" in need and (Bnow is None or tip_ok(picked)):
        order.append("drink"); need.remove("drink"); Bnow = None; continue
    cand = [it for it in left if it["u"] in need and (Bnow is None or it["clr"] >= CLEAR_MM)]
    if cand:
        it = cand[0]; order.append(it["u"]); need.remove(it["u"]); left.remove(it); picked.append(it); continue
    unseen = [u for u in need if u != "drink" and not any(it["u"] == u for it in items)]
    if unseen:   # 카메라에 안 보인 상품(시작 자세 그리퍼에 가림 등)은 pick_loop 가 비켜 찍어 찾고, 서 있는 병과의 팔 몸체 거리는 vla_run 이 다시 검사
        order.append(unseen[0]); need.remove(unseen[0]); continue
    break
if need:
    for it in left:
        if it["u"] in need and Bnow is not None and it["clr"] < CLEAR_MM:
            problems.append(f"{NAMES[it['u']]}(x{it['xy'][0]:.0f} y{it['xy'][1]:.0f})가 서 있는 게토레이와 너무 가까워 팔이 병에 걸려요. 게토레이에서 먼 칸(7·8번)으로 옮겨 주세요")
    if "drink" in need and Bnow is not None:
        problems.append("게토레이를 눕힐 자리가 없어요. 게토레이가 넘어질 쪽(로봇 왼쪽, 5·8번 칸 방향)을 비워 주세요")
    if not problems:
        problems.append("담을 순서를 정하지 못했어요: " + ", ".join(NAMES[u] for u in need))
if problems: out(None, order, problems)
out(order[0] if order else None, order, [])
