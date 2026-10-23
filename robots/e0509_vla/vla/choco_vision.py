#!/usr/bin/env python3
"""시작 자세 위 카메라 사진에서 초코송이(노란 상자) 찾기.  find_box(bgr) -> (cx, cy, area) 또는 None
작업대 영역만 본다(왼쪽 나무 책상·위쪽 로봇팔 제외)."""
import cv2, numpy as np
ROI = (205, 470, 135, 390)    # x0, x1, y0, y1 (픽셀)
def yellow_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (12, 70, 110), (38, 255, 255))
    roi = np.zeros_like(m); x0, x1, y0, y1 = ROI; roi[y0:y1, x0:x1] = 255
    m &= roi
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
def find_box(bgr, min_area=250):
    m = yellow_mask(bgr)
    n, lab, st, c = cv2.connectedComponentsWithStats(m)
    if n <= 1: return None
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    # 상자 가운데 글씨 때문에 노란 면이 두세 조각으로 갈라질 때가 있다(2026-10-20, 가장 큰 조각만 쓰면 3cm 틀어짐).
    # 가장 큰 조각에서 45px 안의 조각(40px² 이상)을 합쳐 전체 외곽 상자의 가운데를 쓴다.
    x0, y0, w0, h0 = st[i, :4]; cx0, cy0 = x0 + w0 / 2, y0 + h0 / 2
    xs, ys, a = [x0, x0 + w0], [y0, y0 + h0], 0
    for j in range(1, n):
        x, y, w, h, ar = st[j]
        if ar < 40: continue
        if j == i or (abs(x + w / 2 - cx0) < 45 + w0 / 2 and abs(y + h / 2 - cy0) < 45 + h0 / 2):
            xs += [x, x + w]; ys += [y, y + h]; a += int(ar)
    if a < min_area: return None
    return float((min(xs) + max(xs)) / 2), float((min(ys) + max(ys)) / 2), a
