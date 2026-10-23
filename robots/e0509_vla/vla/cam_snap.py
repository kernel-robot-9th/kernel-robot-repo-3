#!/usr/bin/env python3
"""위 카메라 한 장 찍기 + 지정 좌표(픽셀) 주변 HSV 통계.  python3 cam_snap.py [out.jpg] [x y]"""
import sys, cv2, numpy as np
out = sys.argv[1] if len(sys.argv) > 1 else "/home/omen/doosan_ws/vla_test/snap.jpg"
cap = cv2.VideoCapture("/dev/video8", cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
for _ in range(15): ok, f = cap.read()   # 노출 안정
cap.release()
if not ok: print("카메라 프레임 없음"); sys.exit(1)
cv2.imwrite(out, f); print("저장", out, f.shape)
if len(sys.argv) > 3:
    x, y = int(sys.argv[2]), int(sys.argv[3])
    hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)[y-8:y+8, x-8:x+8].reshape(-1, 3)
    print("HSV 중앙값", np.median(hsv, 0), "p10", np.percentile(hsv, 10, 0), "p90", np.percentile(hsv, 90, 0))
