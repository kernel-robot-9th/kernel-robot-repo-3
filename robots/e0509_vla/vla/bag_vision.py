#!/usr/bin/env python3
"""위에서 보는 카메라로 새우깡 봉지(빨강/주황) 위치를 찾고, 원래 자리에 아직 있는지 본다."""
import cv2, numpy as np

# 물체별 HSV 범위 (OpenCV H 0~180). set_object() 로 고름
HSV = {"shrimp": [((0, 110, 70), (12, 255, 255)), ((165, 110, 70), (180, 255, 255))],
       "choco": None, "ramen": None}   # 컵라면: 검은 테이프로 찾음(ramen_vision.py). 여기 색 판정은 안 씀   # 초코송이: 위에서 보이는 노란 면이 200px 남짓이라 색 판정 불가(2026-10-19) -> 그리퍼 위치로만 판정
_ranges = HSV["shrimp"]

def set_object(name):
    global _ranges
    _ranges = HSV[name]   # None 이면 카메라 판정 끔 (bag_region 이 늘 None)

def red_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = np.zeros(hsv.shape[:2], np.uint8)
    for lo, hi in (_ranges or []): m |= cv2.inRange(hsv, lo, hi)
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

def bag_region(bgr, min_area=1500):
    """가장 큰 빨간 덩어리 = 봉지. (영역 마스크(조금 넓힘), 면적, 중심) 또는 None."""
    m = red_mask(bgr)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m)
    if n <= 1: return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    # 2026-10-21: 봉지가 눌려 흰 글자가 빨간 면을 둘로 가름(1213+1246px) -> 큰 덩어리 근처(90px 안, 300px 이상) 조각을 합친다
    keep = [j for j in range(1, n) if stats[j, cv2.CC_STAT_AREA] >= 300 and np.hypot(*(cent[j] - cent[i])) < 90.0]
    area = int(sum(stats[j, cv2.CC_STAT_AREA] for j in keep))
    if area < min_area: return None
    mask = np.isin(lab, keep)
    ys, xs = np.nonzero(mask); c = (float(xs.mean()), float(ys.mean()))
    region = cv2.dilate(mask.astype(np.uint8) * 255, np.ones((15, 15), np.uint8))
    return region, area, c

def remaining_fraction(region, area, bgr):
    """원래 봉지 자리에 빨간 픽셀이 얼마나 남았나 (1 이면 그대로, 0 이면 사라짐)."""
    return float(np.count_nonzero(red_mask(bgr) & region)) / max(area, 1)
