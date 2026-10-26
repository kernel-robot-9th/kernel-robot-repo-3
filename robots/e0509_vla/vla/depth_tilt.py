#!/usr/bin/env python3
"""깊이 카메라로 눕힌 병(게토레이)의 기울기 재기 (2026-10-26 시험).
작업대 평면을 맞춘 뒤(작업대 픽셀이 대부분이라는 전제, RANSAC) 각 픽셀의 '작업대 위 높이'를 구하고,
작업대보다 1.5cm 이상 솟은 덩어리 중 병(가로로 긴 덩어리)의 왼쪽 끝·오른쪽 끝 근처 높이를 잰다.
  python3 depth_tilt.py [--save 그림]   -> JSON: left_h, right_h (mm), tilt_mm(= left - right), 끝 픽셀"""
import json, subprocess, sys, tempfile
import cv2, numpy as np

W, H = 848, 480
ROI = (310, 690, 60, 400)   # 깊이 영상에서 작업대가 보이는 범위 (x0, x1, y0, y1), 바구니·사람 쪽 제외 (눈대중)

def grab_depth(n=8):
    with tempfile.NamedTemporaryFile(suffix=".raw") as tf:
        subprocess.run(["v4l2-ctl", "-d", "/dev/video4", f"--set-fmt-video=width={W},height={H},pixelformat=0",
                        "--stream-mmap", f"--stream-count={n + 10}", f"--stream-to={tf.name}"], capture_output=True, timeout=20)
        a = np.fromfile(tf.name, dtype=np.uint16)
    fr = a[-n * W * H:].reshape(n, H, W).astype(np.float32); fr[fr == 0] = np.nan
    return np.nanmedian(fr, axis=0)   # 여러 장 중앙값 (구멍·잡음 줄이기)

def table_plane(d):
    x0, x1, y0, y1 = ROI
    ys, xs = np.mgrid[y0:y1:4, x0:x1:4]; zs = d[y0:y1:4, x0:x1:4]
    ok = np.isfinite(zs); P = np.c_[xs[ok], ys[ok], np.ones(ok.sum())]; Z = zs[ok]
    rng = np.random.default_rng(0); best = None
    for _ in range(200):
        i = rng.choice(len(Z), 3, replace=False)
        try: c = np.linalg.solve(P[i], Z[i])
        except np.linalg.LinAlgError: continue
        inl = np.abs(P @ c - Z) < 6.0
        if best is None or inl.sum() > best[1].sum(): best = (c, inl)
    c = np.linalg.lstsq(P[best[1]], Z[best[1]], rcond=None)[0]
    return c

def heights(d):
    c = table_plane(d); ys, xs = np.mgrid[0:H, 0:W]
    return (c[0] * xs + c[1] * ys + c[2]) - d     # 작업대보다 가까우면 +, mm (카메라가 거의 내려다본다는 근사)

def measure(d, hmin=15.0, hmax=250.0):
    h = heights(d); x0, x1, y0, y1 = ROI
    m = np.zeros((H, W), np.uint8); sub = h[y0:y1, x0:x1]
    m[y0:y1, x0:x1] = ((sub > hmin) & (sub < hmax)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(m)
    if n <= 1: return None, h
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    x, y, w, hh, a = st[i]
    ys, xs = np.nonzero(lab == i)
    L, R = xs.min(), xs.max(); band = max(6, int(0.08 * (R - L)))   # 양 끝에서 8% 안쪽 띠의 높이 중앙값
    hl = float(np.nanmedian(h[ys[xs <= L + band], xs[xs <= L + band]]))
    hr = float(np.nanmedian(h[ys[xs >= R - band], xs[xs >= R - band]]))
    return {"left_px": int(L), "right_px": int(R), "left_h": round(hl, 1), "right_h": round(hr, 1),
            "tilt_mm": round(hl - hr, 1), "len_px": int(R - L), "area": int(a)}, h

if __name__ == "__main__":
    d = grab_depth(); r, h = measure(d)
    print(json.dumps(r, ensure_ascii=False))
    if "--save" in sys.argv:
        vis = cv2.applyColorMap(np.clip(np.nan_to_num(h) * 2, 0, 255).astype(np.uint8), cv2.COLORMAP_JET)
        x0, x1, y0, y1 = ROI; cv2.rectangle(vis, (x0, y0), (x1, y1), (255, 255, 255), 1)
        if r: [cv2.line(vis, (p, 0), (p, H - 1), (255, 255, 255), 1) for p in (r["left_px"], r["right_px"])]
        cv2.imwrite(sys.argv[sys.argv.index("--save") + 1], vis)
