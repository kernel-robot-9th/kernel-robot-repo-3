#!/usr/bin/env python3
"""새우깡·컵라면 사진 텍스처 모델(.dae) 만들기 (2026-10-21). 사진 좌표는 눈대중(원본 2576px 기준).
  python3 tex_objects.py <사진 폴더> <출력 폴더>"""
import math, sys
from pathlib import Path
import cv2, numpy as np

def write_tex_dae(path, tex_name, tris):
    """tris: [((p, uv), (p, uv), (p, uv)), ...] 바깥에서 볼 때 반시계"""
    P, N, T, idx = [], [], [], []
    for k, tri in enumerate(tris):
        a, b, c = [np.array(v[0], float) for v in tri]
        n = np.cross(b - a, c - a); ln = np.linalg.norm(n); n = n / ln if ln > 1e-12 else np.array([0, 0, 1.0])
        N.extend(n)
        for j, (p, uv) in enumerate(tri):
            P.extend(p); T.extend(uv); vi = 3 * k + j; idx += [vi, k, vi]
    f = lambda xs: " ".join(f"{x:.5f}" for x in xs)
    nv = len(P) // 3
    Path(path).write_text('<?xml version="1.0" encoding="utf-8"?>\n<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">'
      '<asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>'
      f'<library_images><image id="img"><init_from>{tex_name}</init_from></image></library_images>'
      '<library_effects><effect id="eff"><profile_COMMON><newparam sid="surf"><surface type="2D"><init_from>img</init_from></surface></newparam>'
      '<newparam sid="samp"><sampler2D><source>surf</source></sampler2D></newparam>'
      '<technique sid="c"><lambert><diffuse><texture texture="samp" texcoord="UV0"/></diffuse></lambert></technique></profile_COMMON></effect></library_effects>'
      '<library_materials><material id="mat" name="tex"><instance_effect url="#eff"/></material></library_materials>'
      '<library_geometries><geometry id="g"><mesh>'
      f'<source id="gp"><float_array id="gpa" count="{len(P)}">{f(P)}</float_array><technique_common><accessor source="#gpa" count="{nv}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>'
      f'<source id="gn"><float_array id="gna" count="{len(N)}">{f(N)}</float_array><technique_common><accessor source="#gna" count="{len(N)//3}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>'
      f'<source id="gt"><float_array id="gta" count="{len(T)}">{f(T)}</float_array><technique_common><accessor source="#gta" count="{len(T)//2}" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>'
      '<vertices id="gv"><input semantic="POSITION" source="#gp"/></vertices>'
      f'<triangles material="m" count="{len(tris)}"><input semantic="VERTEX" source="#gv" offset="0"/><input semantic="NORMAL" source="#gn" offset="1"/><input semantic="TEXCOORD" source="#gt" offset="2" set="0"/><p>{" ".join(map(str, idx))}</p></triangles>'
      '</mesh></geometry></library_geometries>'
      '<library_visual_scenes><visual_scene id="s"><node id="n"><instance_geometry url="#g"><bind_material><technique_common>'
      '<instance_material symbol="m" target="#mat"><bind_vertex_input semantic="UV0" input_semantic="TEXCOORD" input_set="0"/></instance_material>'
      '</technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes>'
      '<scene><instance_visual_scene url="#s"/></scene></COLLADA>')

def warp(im, quad, w, h):
    return cv2.warpPerspective(im, cv2.getPerspectiveTransform(np.float32(quad), np.float32([(0, 0), (w, 0), (w, h), (0, h)])), (w, h))

def quad_tri(tris, p, uv):   # p, uv: 4개 (반시계)
    tris.append(((p[0], uv[0]), (p[1], uv[1]), (p[2], uv[2]))); tris.append(((p[0], uv[0]), (p[2], uv[2]), (p[3], uv[3])))

def shrimp(src, out):
    S = 2.576   # 눈금 사진(1000px) 좌표 -> 원본
    fr = cv2.imread(str(src / "3cb3f9bd-image.jpg")); bk = cv2.imread(str(src / "443aca71-image.jpg"))
    A = np.zeros((1000, 1400, 3), np.uint8)
    A[:, :700] = warp(fr, [(130 * S, 25 * S), (855 * S, 45 * S), (885 * S, 990 * S), (80 * S, 985 * S)], 700, 1000)
    A[:, 700:] = warp(bk, [(130 * S, 40 * S), (855 * S, 45 * S), (850 * S, 945 * S), (85 * S, 940 * S)], 700, 1000)
    cv2.imwrite(str(out / "shrimp_tex.jpg"), A, [cv2.IMWRITE_JPEG_QUALITY, 90])
    L, W, H, SEAL = 0.20, 0.14, 0.05, 0.015; nu, nv = 28, 40
    def h(u, v):
        yv = abs(v) * L / 2; body = L / 2 - SEAL
        if yv >= body: return 0.0012
        return max(0.0012, H / 2 * math.sqrt(max(0.0, 1 - abs(u) ** 6) * max(0.0, 1 - (yv / body) ** 4)))
    U = np.linspace(-1, 1, nu); V = np.linspace(-1, 1, nv); tris = []
    # 윗면 = 앞면 사진: 사진 위쪽(농심 로고) = +y, 사진 오른쪽 = +x  -> 위에서 볼 때 거울상 아님
    uv_top = lambda u, v: (((u + 1) / 2) * 0.5, 1 - (1 - v) / 2)
    # 아랫면 = 뒷면 사진: 사진 위쪽 = +y, 사진 오른쪽 = -x
    uv_bot = lambda u, v: (0.5 + ((1 - u) / 2) * 0.5, 1 - (1 - v) / 2)
    for i in range(nu - 1):
        for j in range(nv - 1):
            us = (U[i], U[i + 1], U[i + 1], U[i]); vs = (V[j], V[j], V[j + 1], V[j + 1])
            pt = [(u * W / 2, v * L / 2, h(u, v)) for u, v in zip(us, vs)]
            quad_tri(tris, pt, [uv_top(u, v) for u, v in zip(us, vs)])
            pb = [(u * W / 2, v * L / 2, -h(u, v)) for u, v in zip(us, vs)][::-1]
            quad_tri(tris, pb, [uv_bot(u, v) for u, v in zip(us, vs)][::-1])
    write_tex_dae(out / "shrimp.dae", "shrimp_tex.jpg", tris)

def ramen(src, out):
    Q = 2576 / 1932   # 채팅에 보인 사진(1932px) 좌표 -> 원본
    sides = [("9a16f1e6-image.jpg", (430, 60), (1400, 60), (1420, 1580), (400, 1580)),
             ("d584afcb-image.jpg", (470, 80), (1380, 80), (1385, 1580), (400, 1580)),
             ("c1a5e930-image.jpg", (540, 80), (1395, 80), (1420, 1570), (430, 1570)),
             ("bb837c73-image.jpg", (555, 170), (1365, 170), (1385, 1560), (470, 1560))]
    A = np.zeros((540, 2520, 3), np.uint8)
    for k, (f, tl, tr, br, bl) in enumerate(sides):   # 둥근 옆면은 가운데 70% 만 (가장자리는 비스듬해 늘어남)
        im = cv2.imread(str(src / f)); m = 0.15
        q = [(tl[0] + m * (tr[0] - tl[0]), tl[1]), (tr[0] - m * (tr[0] - tl[0]), tr[1]), (br[0] - m * (br[0] - bl[0]), br[1]), (bl[0] + m * (br[0] - bl[0]), bl[1])]
        A[:, 360 * k:360 * (k + 1)] = warp(im, [(x * Q, y * Q) for x, y in q], 360, 540)
    lid = cv2.imread(str(src / "7d313d42-image.jpg")); cx, cy, r = 1366, 1288, 712
    A[:, 1440:1980] = cv2.resize(lid[cy - r:cy + r, cx - r:cx + r], (540, 540))
    tp = cv2.imread(str(src / "bcccf8ea-image.jpg")); cx, cy, r = 1258, 1541, 660
    A[:, 1980:2520] = cv2.resize(tp[cy - r:cy + r, cx - r:cx + r], (540, 540))
    cv2.imwrite(str(out / "ramen_tex.jpg"), A, [cv2.IMWRITE_JPEG_QUALITY, 90])
    Hh, R0, R1, n = 0.11, 0.05, 0.03, 64; z0, z1 = -Hh / 2, Hh / 2; Wt = 2520.0; tris = []
    for k in range(n):
        t0, t1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        u0, u1 = (1440 * k / n) / Wt, (1440 * (k + 1) / n) / Wt
        p = [(R0 * math.cos(t0), R0 * math.sin(t0), z0), (R0 * math.cos(t1), R0 * math.sin(t1), z0), (R1 * math.cos(t1), R1 * math.sin(t1), z1), (R1 * math.cos(t0), R1 * math.sin(t0), z1)]
        quad_tri(tris, p, [(u0, 0.0), (u1, 0.0), (u1, 1.0), (u0, 1.0)])
        # 위(좁은 쪽 = 원래 밑면, 테이프) : 위에서 볼 때
        c = ((1980 + 270) / Wt, 0.5); s = 270 / Wt
        tris.append((((0, 0, z1), c), ((R1 * math.cos(t0), R1 * math.sin(t0), z1), (c[0] + s * math.cos(t0), 0.5 + 0.5 * math.sin(t0))),
                     ((R1 * math.cos(t1), R1 * math.sin(t1), z1), (c[0] + s * math.cos(t1), 0.5 + 0.5 * math.sin(t1)))))
        # 아래(넓은 쪽 = 뚜껑) : 아래에서 볼 때
        c = ((1440 + 270) / Wt, 0.5)
        tris.append((((0, 0, z0), c), ((R0 * math.cos(t1), R0 * math.sin(t1), z0), (c[0] + s * math.cos(t1), 0.5 - 0.5 * math.sin(t1))),
                     ((R0 * math.cos(t0), R0 * math.sin(t0), z0), (c[0] + s * math.cos(t0), 0.5 - 0.5 * math.sin(t0)))))
    write_tex_dae(out / "ramen.dae", "ramen_tex.jpg", tris)

if __name__ == "__main__":
    src, out = Path(sys.argv[1]), Path(sys.argv[2]); shrimp(src, out); ramen(src, out); print("ok")
