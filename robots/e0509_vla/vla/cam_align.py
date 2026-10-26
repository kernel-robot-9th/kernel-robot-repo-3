#!/usr/bin/env python3
"""카메라 다시 달 때 원래 자리 맞추기 (2026-10-26).
떨어뜨리기 전 사진(초록 선)과 지금 영상을 겹쳐 보여 주고, 어긋난 정도를 숫자로 띄운다.  q 또는 Esc 로 끝.
  python3 cam_align.py [기준 사진]"""
import sys, time
import cv2, numpy as np

REF = sys.argv[1] if len(sys.argv) > 1 else "/home/omen/doosan_ws/vla_test/runs/vla_20261023_100356/c00_start.jpg"
ref = cv2.imread(REF)
g_ref = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
edge_ref = cv2.Canny(cv2.GaussianBlur(g_ref, (5, 5), 0), 60, 150)
orb = cv2.ORB_create(3000)
k1, d1 = orb.detectAndCompute(g_ref, None)
# 작업대 네 모서리(기준 사진 픽셀, 눈대중) -> 지금 영상에서 어디로 갔는지 화살표로 보여 줌
CORNERS = np.float32([[205, 20], [450, 20], [480, 380], [190, 380]])

cap = cv2.VideoCapture("/dev/video8", cv2.CAP_V4L2); cap.set(3, 640); cap.set(4, 480)
cv2.namedWindow("camera align", cv2.WINDOW_NORMAL); cv2.resizeWindow("camera align", 1280, 960)
t_est, msg, H = 0.0, "", None
while True:
    ok, f = cap.read()
    if not ok: time.sleep(0.1); continue
    view = cv2.addWeighted(f, 0.6, ref, 0.4, 0)
    view[edge_ref > 0] = (0, 255, 0)
    if time.time() - t_est > 0.5:
        t_est = time.time()
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY); k2, d2 = orb.detectAndCompute(g, None)
        msg, H = "match fail", None
        if d2 is not None and len(k2) > 50:
            m = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2), key=lambda x: x.distance)[:500]
            if len(m) > 30:
                A = np.float32([k1[x.queryIdx].pt for x in m]); B = np.float32([k2[x.trainIdx].pt for x in m])
                Hm, inl = cv2.findHomography(A, B, cv2.RANSAC, 3.0)
                if Hm is not None and inl.sum() > 25:
                    H = Hm; c2 = cv2.perspectiveTransform(CORNERS[None], H)[0]
                    err = np.linalg.norm(c2 - CORNERS, axis=1)
                    d = (c2 - CORNERS).mean(0)
                    msg = f"corner err mean {err.mean():.0f}px max {err.max():.0f}px | move dx {d[0]:+.0f} dy {d[1]:+.0f} | inliers {int(inl.sum())}"
                    msg += "  OK" if err.max() < 6 else ""
    if H is not None:
        c2 = cv2.perspectiveTransform(CORNERS[None], H)[0]
        for a, b in zip(CORNERS, c2):
            cv2.circle(view, tuple(int(v) for v in a), 6, (0, 255, 0), 2)
            cv2.arrowedLine(view, tuple(int(v) for v in a), tuple(int(v) for v in b), (0, 0, 255), 2, tipLength=0.3)
    cv2.rectangle(view, (0, 0), (640, 26), (0, 0, 0), -1)
    cv2.putText(view, msg, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.imshow("camera align", view)
    if cv2.waitKey(30) & 0xFF in (27, ord("q")): break
cap.release(); cv2.destroyAllWindows()
