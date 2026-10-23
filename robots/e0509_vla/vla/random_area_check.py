#!/usr/bin/env python3
"""무작위 위치 수집용: 작업대 격자점마다 수집 한 판의 핵심 구간을 로봇 없이 IK 로 따라가 본다.
조작성 최소값이 0.03 이상이고 관절 범위가 안전한 점만 '가능'. 결과 random_area.json"""
import json, math, sys
import numpy as np
sys.path.insert(0, "/home/omen/doosan_ws/vla_test")
from path_check import ik, jac
from fk import Chain, zyz_to_matrix
HERE = "/home/omen/doosan_ws/vla_test"
R = zyz_to_matrix(0, 180, 0); CH3 = Chain(tip="link_3"); CH = Chain()
cells = json.load(open(f"{HERE}/shrimp_cells.json")); P = np.array([v[:2] for v in cells.values()]); Z = np.array([v[2] for v in cells.values()])
def gz(x, y):
    d = np.linalg.norm(P - [x, y], axis=1)
    if d.min() < 1e-6: return float(Z[d.argmin()]) + 5
    w = 1 / d ** 2; return float((w * Z).sum() / w.sum()) + 5
# 시드 관절: 오늘 초코송이 5번 칸 실제 녹화 첫 프레임
import glob
fr = sorted(glob.glob(f"{HERE}/collect_choco/*/ep001/frames.jsonl"))[0]
Q0 = np.array(json.loads(open(fr).readline())["joints"], float)
if np.abs(Q0).max() > 2 * math.pi: Q0 = np.radians(Q0)
def seg(q, a, b, n=10):
    worst = 9.0
    for t in np.linspace(0, 1, n):
        p = np.array(a) + (np.array(b) - np.array(a)) * t
        q, err = ik(q, p, R, it=40)
        if err > 2: return q, -1.0
        J = jac(q); worst = min(worst, math.sqrt(max(np.linalg.det(J @ J.T), 0)))
        jd = np.degrees(q)
        if not (-15 <= jd[1] <= 60) or jd[2] > 125 or CH3.fk(q)[0][0] < -60: return q, -2.0   # collect.py J2_RANGE, J3_MAX, ELBOW_X_MIN 과 같게
    return q, worst
def route(x, y):
    g = gz(x, y); start = (430, 13, 427)
    legs = [start, (x, y, 445) if x <= 600 else (520, y, 320), (x, y, 320), (x, y, 260), (x, y, g), (x, y, g + 30)]
    if x > 600: legs += [(x, y, 300), (520, y, 300), (520, y, 445)]
    else: legs += [(x, y, 445)]
    q = Q0.copy(); q, _ = ik(q, np.array(start, float), R); worst = 9.0
    for a, b in zip(legs, legs[1:]):
        q, w = seg(q, a, b)
        if w < 0: return w
        worst = min(worst, w)
    return worst
def main():
  res = {}
  xs = np.arange(320, 701, 20); ys = np.arange(-200, 201, 20)
  print("      " + "".join(f"{y:5.0f}" for y in ys))
  for x in xs:
      row = []
      for y in ys:
          w = route(float(x), float(y)); res[f"{x},{y}"] = w
          row.append(" ---" if w < 0 else (f" {w:.2f}"[1:] if w < 0.03 else "  ok"))
      print(f"x{x:4.0f} " + "".join(f"{c:>5s}" for c in row))
  json.dump(res, open(f"{HERE}/random_area.json", "w"))

if __name__ == "__main__":
    main()
