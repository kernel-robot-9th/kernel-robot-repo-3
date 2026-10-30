#!/usr/bin/env python3
"""게토레이(눕힌 병) 찾기 시험 (2026-10-26). 빨간 뚜껑(작은 둥근 빨강)을 찾고, 뚜껑 양옆 중 병 몸통(밝은 노랑)이 있는 쪽으로
GRIP_PX 만큼 들어간 병목 지점을 잡을 자리로 본다. 병은 로봇 좌우 방향(사진 가로)으로 눕혀 놓는다는 전제.
  python3 gatorade_vision.py <사진>   -> 픽셀·작업대 좌표 출력, /tmp/gd_dbg.jpg"""
import json, sys
from pathlib import Path
import cv2, numpy as np

HERE = Path(__file__).resolve().parent
ROI = (190, 470, 30, 370)          # 작업대 영역 (x0, x1, y0, y1). 10-26: 1번 칸에 세운 병 뚜껑이 y53 에 찍혀 위로 넓힘
CAP_AREA = (60, 900)               # 뚜껑 빨강 면적(px). 새우깡 봉지는 2000 이상. 10-26 18:45: 뽁뽁이가 뚜껑을 가려 74px -> 60 부터
GRIP_PX = 28                       # 뚜껑 중심에서 몸통 쪽으로 병목까지 (약 5cm)

def red_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (0, 110, 70), (12, 255, 255)) | cv2.inRange(hsv, (165, 110, 70), (180, 255, 255))
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

def liquid_mask(bgr):   # 노란 음료
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (18, 40, 120), (40, 255, 255))

def find_bottle(bgr):
    x0, x1, y0, y1 = ROI
    m = np.zeros(bgr.shape[:2], np.uint8); m[y0:y1, x0:x1] = red_mask(bgr)[y0:y1, x0:x1]
    n, lab, st, cen = cv2.connectedComponentsWithStats(m)
    caps = [i for i in range(1, n) if CAP_AREA[0] <= st[i, 4] <= CAP_AREA[1] and 0.5 <= st[i, 2] / max(st[i, 3], 1) <= 2.0]
    if not caps: return None
    def fill(j):   # 10-26: 다른 상품과 같이 놓을 때 새우깡 봉지의 빨간 조각과 구분 -> 외곽 상자를 꽉 채운 둥근 덩어리(뚜껑)
        return st[j, 4] / float(st[j, 2] * st[j, 3])
    caps = [j for j in caps if fill(j) >= 0.45]
    # 10-26: 새우깡 봉지 그림 속 작은 빨간 덩어리를 뚜껑으로 봄 -> 뚜껑 둘레(반지름 1.6~3배)에 빨강이 20% 넘으면 봉지 속으로 보고 뺀다
    red = red_mask(bgr) > 0; H_, W_ = red.shape; yy, xx = np.mgrid[0:H_, 0:W_]
    def ring_red(j):
        cx_, cy_ = cen[j]; r0 = max(st[j, 2], st[j, 3]) / 2.0
        d = np.hypot(xx - cx_, yy - cy_); ring = (d > 1.6 * r0) & (d < 3.0 * r0)
        return float(red[ring].mean()) if ring.any() else 1.0
    caps = [j for j in caps if ring_red(j) < 0.20]
    if not caps: return None
    i = max(caps, key=lambda j: fill(j) * min(1.0, st[j, 4] / 150.0)); cx, cy = cen[i]
    liq = liquid_mask(bgr); best = None
    for d in (-1, 1):   # 뚜껑 왼쪽/오른쪽 중 노란 음료가 많은 쪽 = 몸통
        xs = slice(int(max(0, cx + d * 20 if d > 0 else cx - 120)), int(min(640, cx + 120 if d > 0 else cx - 20)))
        cnt = int(np.count_nonzero(liq[int(cy) - 20:int(cy) + 20, xs]))
        if best is None or cnt > best[1]: best = (d, cnt)
    d = best[0]
    gx, gy = cx + d * GRIP_PX, cy
    return {"cap_px": [float(cx), float(cy)], "grip_px": [float(gx), float(gy)], "body_dir": d, "liquid_px": best[1], "cap_area": int(st[i, 4])}

def px_to_xy(p):
    W = np.array(json.loads((HERE / "cam_pix2xy.json").read_text()))   # 작업대 높이 보정식(새우깡). 눕힌 병은 높이 10cm 이하라 오차 작음
    return (np.r_[p, 1.0] @ W).tolist()

if __name__ == "__main__":
    im = cv2.imread(sys.argv[1]); r = find_bottle(im)
    if r is None: print("못 찾음"); sys.exit(1)
    r["grip_xy"] = [round(v, 1) for v in px_to_xy(r["grip_px"])]; r["cap_xy"] = [round(v, 1) for v in px_to_xy(r["cap_px"])]
    print(json.dumps(r, ensure_ascii=False))
    dbg = im.copy(); cv2.circle(dbg, tuple(int(v) for v in r["cap_px"]), 12, (0, 0, 255), 2)
    cv2.drawMarker(dbg, tuple(int(v) for v in r["grip_px"]), (0, 255, 0), cv2.MARKER_CROSS, 24, 2); cv2.imwrite("/tmp/gd_dbg.jpg", dbg)

def locate_bottle(bgr, bg_path=None):
    """10-26 트윈·키오스크용: 뚜껑 + 빈 작업대 비교로 누운 병의 가운데(작업대 좌표 mm)와 방향.
    반환 {"center": [x, y], "cap": [x, y], "u": [ux, uy](뚜껑->몸통), "yaw_deg": 모델 회전(축 +y = 바닥->뚜껑)} 또는 None"""
    import math
    r = find_bottle(bgr)
    if r is None: return None
    bg = cv2.imread(str(bg_path or (HERE / "table_empty.jpg")))
    cap = np.array(px_to_xy(r["cap_px"]))
    u = None
    if bg is not None:
        diff = cv2.absdiff(cv2.GaussianBlur(bgr, (5, 5), 0), cv2.GaussianBlur(bg, (5, 5), 0)).max(axis=2)
        m = (diff > 28).astype(np.uint8); roi = np.zeros_like(m); roi[max(ROI[2], 140):ROI[3], ROI[0] + 6:ROI[1] - 6] = 1; m &= roi
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)); m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        n, lab, st, cen = cv2.connectedComponentsWithStats(m)
        cx, cy = r["cap_px"]
        cand = [j for j in range(1, n) if st[j, 4] > 800]
        if cand:
            i = min(cand, key=lambda j: np.hypot(*(cen[j] - [cx, cy])))
            ys, xs = np.nonzero(lab == i); P = np.c_[xs, ys].astype(np.float64); c = P.mean(0)
            w, v = np.linalg.eigh(np.cov((P - c).T)); ax = v[:, np.argmax(w)]
            if np.dot(c - [cx, cy], ax) < 0: ax = -ax
            b = np.array(px_to_xy([cx + 60 * ax[0], cy + 60 * ax[1]])); u = (b - cap) / np.linalg.norm(b - cap)
    if u is None: u = np.array([0.0, -1.0 if r["body_dir"] < 0 else 1.0])
    center = cap + u * 145.0          # 뚜껑 중심에서 병 가운데까지 (길이 320 의 절반 - 뚜껑 15)
    capdir = -u
    return {"center": center.tolist(), "cap": cap.tolist(), "u": u.tolist(), "yaw_deg": math.degrees(math.atan2(-capdir[0], capdir[1]))}
