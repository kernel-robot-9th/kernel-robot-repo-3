#!/usr/bin/env python3
"""컵라면 카메라 위치 보정식 (2026-10-21): 수집 에피소드 첫 사진(팔이 시작 자세)에서 검은 테이프 중심 픽셀 -> 실제 놓은 자리(snack_xy).
초코송이와 같은 2차식 [px, py, px*py, px^2, py^2, 1] @ W(6x2). 한 편씩 빼고 맞춘 오차(LOO)도 출력. 결과 cam_ramen_pix2xy.json"""
import json, glob, cv2, numpy as np
from pathlib import Path
from ramen_vision import find_cup
HERE = Path(__file__).resolve().parent
P, Y, names = [], [], []
for m in sorted(glob.glob(str(HERE / "collect_ramen/2026*/ep*/meta.json"))):
    d = json.load(open(m))
    if not (d.get("success") and d.get("in_basket")): continue
    im = cv2.imread(str(Path(m).parent / "frames" / "00000.jpg"))
    c = find_cup(im) if im is not None else None
    if c is None: print("못 찾음", m); continue
    P.append([c[0], c[1]]); Y.append(d["snack_xy"]); names.append(m)
P, Y = np.array(P), np.array(Y)
# 로봇 쪽 칸(사진 위쪽 py<175)은 시작 자세 그리퍼와 겹쳐 테이프를 잘못 잡음 -> 뺀다. 그다음 30mm 넘게 틀린 것은 한 번 더 빼고 다시 맞춤
keep = P[:, 1] >= 175; print(f"그리퍼와 겹치는 사진 {int((~keep).sum())}편 뺌"); P, Y = P[keep], Y[keep]
F = lambda p: np.c_[p[:, 0], p[:, 1], p[:, 0] * p[:, 1], p[:, 0] ** 2, p[:, 1] ** 2, np.ones(len(p))]
W = np.linalg.lstsq(F(P), Y, rcond=None)[0]
r = np.linalg.norm(F(P) @ W - Y, axis=1); ok = r < 30.0
if (~ok).any(): print(f"30mm 넘게 틀린 {int((~ok).sum())}편 더 뺌"); P, Y = P[ok], Y[ok]; W = np.linalg.lstsq(F(P), Y, rcond=None)[0]
err = []
for i in range(len(P)):
    k = np.arange(len(P)) != i
    Wi = np.linalg.lstsq(F(P[k]), Y[k], rcond=None)[0]
    err.append(float(np.linalg.norm(F(P[i:i + 1]) @ Wi - Y[i])))
err = np.array(err)
Wc = np.array(json.load(open(HERE / "cam_choco_pix2xy.json")))
ec = np.linalg.norm(F(P) @ Wc - Y, axis=1)
print(f"편수 {len(P)}  컵 전용식 LOO 오차: 중앙값 {np.median(err):.1f}mm  90% {np.percentile(err, 90):.1f}  최대 {err.max():.1f}")
print(f"초코송이 식을 그대로 쓸 때 오차: 중앙값 {np.median(ec):.1f}mm  90% {np.percentile(ec, 90):.1f}  최대 {ec.max():.1f}  평균 치우침 dx{np.mean((F(P) @ Wc - Y)[:, 0]):+.1f} dy{np.mean((F(P) @ Wc - Y)[:, 1]):+.1f}")
(HERE / "cam_ramen_pix2xy.json").write_text(json.dumps(W.tolist()))
print("저장 cam_ramen_pix2xy.json")
