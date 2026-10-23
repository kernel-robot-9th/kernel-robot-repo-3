#!/usr/bin/env python3
"""위 카메라로 컵라면 찾기 (2026-10-21). 컵을 거꾸로 세우고 위로 온 밑면에 검은 테이프를 붙였다(약 32px 동그라미).
작업대 영역(choco_vision.ROI) 안에서 '어둡고(V<90) 동그란' 덩어리 중 가장 큰 것. 작업대 끝 띠(y>=355)·가장자리·그리퍼는 크기·모양으로 거른다.
  find_cup(bgr) -> (cx, cy, area) 픽셀, 못 찾으면 None"""
import cv2, numpy as np
from choco_vision import ROI

V_MAX, AREA_MIN, AREA_MAX, Y_MAX = 90, 500, 2500, 355   # 10-22: 350 -> 500 (작업대 검은 반원 표시 353px 를 컵으로 봄). 컵 테이프 660~830px
MARKS = [(215, 260, 300, 345)]   # 작업대에 붙은 검은 반원 표시 자리 (x0, x1, y0, y1) - 늘 가림
Y_TOP = 95   # 10-22: 로봇 쪽 줄 컵은 사진 y 110~140 (작업대 ROI 위 경계 135 보다 위). 작업대 끝(로봇 쪽) y 약 95

GRIP_BOX = (295, 380, 0, 150)   # 시작 자세(x430 y13 z427)에서 그리퍼가 보이는 자리 (x0, x1, y0, y1)

def dark_mask(bgr, start_pose=True):
    h = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = (h[:, :, 2] < V_MAX).astype(np.uint8)
    x0, x1, y0, y1 = ROI; r = np.zeros_like(m); r[Y_TOP:min(y1, Y_MAX), x0 + 8:x1 - 8] = 1   # 작업대 끝 띠·좌우 가장자리 뺌
    for mx0, mx1, my0, my1 in MARKS: r[my0:my1, mx0:mx1] = 0
    if start_pose:   # 시작 자세 사진이면 그리퍼(검정)를 가린다. 팔을 비킨 사진(start_pose=False)은 전체를 본다
        gx0, gx1, gy0, gy1 = GRIP_BOX; r[gy0:gy1, gx0:gx1] = 0
    return cv2.morphologyEx(m * r, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

def find_cup(bgr, start_pose=True):
    m = dark_mask(bgr, start_pose)
    n, lab, st, cen = cv2.connectedComponentsWithStats(m)
    best = None
    for i in range(1, n):
        x, y, w, hh, a = st[i]
        if not (AREA_MIN <= a <= AREA_MAX): continue
        if not (0.6 <= w / max(hh, 1) <= 1.6): continue          # 동그라미 (긴 띠 제외)
        if a / float(w * hh) < 0.55: continue                     # 속이 찬 모양 (원이면 약 0.78)
        if best is None or a > best[2]: best = (float(cen[i][0]), float(cen[i][1]), int(a))
    return best

if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]: print(f, find_cup(cv2.imread(f)))
