#!/usr/bin/env python3
"""디지털 트윈용 물건 3D 모델(.dae, 색 포함) 만들기 (2026-10-21). 단위 m, 원점 = 물건 중심, z 위.
  초코송이 35x120x85 세운 상자, 새우깡 140x200x50 눕힌 베개 봉지, 컵라면 거꾸로 놓은 원뿔대(아래 지름 100, 위 60, 높이 110)
  python3 gen_meshes.py <출력 폴더>"""
import math, sys
from pathlib import Path
import numpy as np

class Mesh:
    def __init__(self): self.parts = {}          # 재질 이름 -> (색, [삼각형 (v0,v1,v2)])
    def mat(self, name, rgb): self.parts.setdefault(name, (rgb, []))
    def tri(self, name, a, b, c): self.parts[name][1].append((np.asarray(a, float), np.asarray(b, float), np.asarray(c, float)))
    def quad(self, name, a, b, c, d): self.tri(name, a, b, c); self.tri(name, a, c, d)
    def write_dae(self, path):
        eff, mats, geos, binds = [], [], [], []
        for i, (name, (rgb, tris)) in enumerate(self.parts.items()):
            if not tris: continue
            r, g, b = rgb
            eff.append(f'<effect id="e{i}"><profile_COMMON><technique sid="c"><phong><diffuse><color>{r:.3f} {g:.3f} {b:.3f} 1</color></diffuse>'
                       f'<specular><color>0.15 0.15 0.15 1</color></specular><shininess><float>20</float></shininess></phong></technique></profile_COMMON></effect>')
            mats.append(f'<material id="m{i}" name="{name}"><instance_effect url="#e{i}"/></material>')
            pos, nor, idx = [], [], []
            for k, (a, b2, c) in enumerate(tris):
                n = np.cross(b2 - a, c - a); ln = np.linalg.norm(n); n = n / ln if ln > 0 else np.array([0, 0, 1.0])
                for v in (a, b2, c): pos.extend(v); nor.extend(n)
                idx.extend([3 * k, 3 * k, 3 * k + 1, 3 * k + 1, 3 * k + 2, 3 * k + 2])
            nv = len(pos) // 3
            f = lambda xs: " ".join(f"{x:.5f}" for x in xs)
            geos.append(f'<geometry id="g{i}"><mesh>'
                        f'<source id="g{i}p"><float_array id="g{i}pa" count="{len(pos)}">{f(pos)}</float_array><technique_common><accessor source="#g{i}pa" count="{nv}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>'
                        f'<source id="g{i}n"><float_array id="g{i}na" count="{len(nor)}">{f(nor)}</float_array><technique_common><accessor source="#g{i}na" count="{nv}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>'
                        f'<vertices id="g{i}v"><input semantic="POSITION" source="#g{i}p"/></vertices>'
                        f'<triangles material="mat" count="{len(tris)}"><input semantic="VERTEX" source="#g{i}v" offset="0"/><input semantic="NORMAL" source="#g{i}n" offset="1"/><p>{" ".join(map(str, idx))}</p></triangles>'
                        f'</mesh></geometry>')
            binds.append(f'<node id="n{i}"><instance_geometry url="#g{i}"><bind_material><technique_common><instance_material symbol="mat" target="#m{i}"/></technique_common></bind_material></instance_geometry></node>')
        Path(path).write_text('<?xml version="1.0" encoding="utf-8"?>\n<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">'
            '<asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>'
            f'<library_effects>{"".join(eff)}</library_effects><library_materials>{"".join(mats)}</library_materials>'
            f'<library_geometries>{"".join(geos)}</library_geometries>'
            f'<library_visual_scenes><visual_scene id="s">{"".join(binds)}</visual_scene></library_visual_scenes>'
            '<scene><instance_visual_scene url="#s"/></scene></COLLADA>')

def box_faces(m, name, c, s):
    """중심 c, 크기 s 인 상자 6면 (바깥 법선)."""
    x0, y0, z0 = np.array(c) - np.array(s) / 2; x1, y1, z1 = np.array(c) + np.array(s) / 2
    P = lambda x, y, z: (x, y, z)
    m.quad(name, P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1))   # 위
    m.quad(name, P(x0, y0, z0), P(x0, y1, z0), P(x1, y1, z0), P(x1, y0, z0))   # 아래
    m.quad(name, P(x1, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1))   # +x
    m.quad(name, P(x0, y0, z0), P(x0, y0, z1), P(x0, y1, z1), P(x0, y1, z0))   # -x
    m.quad(name, P(x0, y1, z0), P(x0, y1, z1), P(x1, y1, z1), P(x1, y1, z0))   # +y
    m.quad(name, P(x0, y0, z0), P(x1, y0, z0), P(x1, y0, z1), P(x0, y0, z1))   # -y

def choco():
    """초코송이: 노란 종이상자. 넓은 면(±x)에 빨간 로고 띠, 갈색 초코 버섯 그림 자리, 아래쪽 갈색 띠."""
    m = Mesh(); m.mat("yellow", (0.97, 0.80, 0.18)); m.mat("brown", (0.36, 0.22, 0.14)); m.mat("red", (0.82, 0.12, 0.10)); m.mat("cream", (0.98, 0.92, 0.72))
    sx, sy, sz = 0.035, 0.12, 0.085; e = 0.0006
    box_faces(m, "yellow", (0, 0, 0), (sx, sy, sz))
    for sgn in (1, -1):    # 넓은 두 면에 그림(상자 면보다 0.6mm 바깥 얇은 판)
        x = sgn * (sx / 2 + e)
        def rect(name, y0, y1, z0, z1):
            a, b, c, d = (x, y0, z0), (x, y1, z0), (x, y1, z1), (x, y0, z1)
            (m.quad(name, a, b, c, d) if sgn > 0 else m.quad(name, a, d, c, b))
        rect("red", -0.05, 0.05, 0.018, 0.034)          # 로고 띠
        rect("brown", -0.06, 0.06, -0.0425, -0.030)      # 아래 갈색 띠
        rect("cream", -0.045, 0.045, -0.026, 0.012)       # 그림 바탕
        for yc in (-0.022, 0.014):                        # 버섯 두 개(갈색 갓 + 크림 기둥)
            rect("brown", yc - 0.014, yc + 0.014, -0.004, 0.010)
            rect("yellow", yc - 0.004, yc + 0.004, -0.022, -0.004)
    return m

def shrimp():
    """새우깡: 눕힌 베개 봉지. 가운데 볼록, y 양끝 15mm 는 납작한 이음매. 위면 가운데 크림색 라벨, 과자 무늬(주황 점)."""
    m = Mesh(); m.mat("red", (0.86, 0.16, 0.12)); m.mat("seal", (0.62, 0.10, 0.09)); m.mat("label", (0.99, 0.93, 0.76)); m.mat("snack", (0.93, 0.62, 0.25))
    L, W, H, S = 0.20, 0.14, 0.05, 0.015            # 길이(y), 폭(x), 두께, 이음매
    nu, nv = 28, 40
    def h(u, v):     # u,v in [-1,1] -> 반두께
        yv = abs(v) * (L / 2); body = L / 2 - S
        if yv >= body: return 0.0012
        a = max(0.0, 1 - abs(u) ** 6); b = max(0.0, 1 - (yv / body) ** 4)
        return max(0.0012, H / 2 * math.sqrt(a * b))
    U = np.linspace(-1, 1, nu); V = np.linspace(-1, 1, nv)
    def P(u, v, s): return (u * W / 2, v * L / 2, s * h(u, v))
    for i in range(nu - 1):
        for j in range(nv - 1):
            u0, u1, v0, v1 = U[i], U[i + 1], V[j], V[j + 1]; uc, vc = (u0 + u1) / 2, (v0 + v1) / 2
            seal = abs(vc) * L / 2 > L / 2 - S
            name_top = "seal" if seal else ("label" if (abs(uc) < 0.62 and abs(vc) < 0.28) else ("snack" if ((i * 7 + j * 3) % 11 == 0 and abs(vc) < 0.7) else "red"))
            m.quad(name_top, P(u0, v0, 1), P(u1, v0, 1), P(u1, v1, 1), P(u0, v1, 1))
            m.quad("seal" if seal else "red", P(u0, v0, -1), P(u0, v1, -1), P(u1, v1, -1), P(u1, v0, -1))
    for j in range(nv - 1):   # 옆 가장자리(u=±1) 위아래 이어 붙임
        for uu in (-1.0, 1.0):
            a, b, c, d = P(uu, V[j], -1), P(uu, V[j + 1], -1), P(uu, V[j + 1], 1), P(uu, V[j], 1)
            (m.quad("red", a, b, c, d) if uu > 0 else m.quad("red", a, d, c, b))
    return m

def ramen():
    """컵라면: 거꾸로 놓은 원뿔대(아래=입구 지름 100, 위=밑면 지름 60, 높이 110). 옆면 위·아래 흰 띠, 가운데 빨강, 위 밑면에 검은 테이프."""
    m = Mesh(); m.mat("red", (0.80, 0.16, 0.14)); m.mat("white", (0.96, 0.95, 0.92)); m.mat("tape", (0.06, 0.06, 0.06)); m.mat("rim", (0.85, 0.83, 0.78)); m.mat("lid", (0.88, 0.88, 0.86))
    Hh, R0, R1, n = 0.11, 0.05, 0.03, 48
    z0, z1 = -Hh / 2, Hh / 2
    r = lambda z: R0 + (R1 - R0) * (z - z0) / Hh
    bands = [(z0, z0 + 0.006, "rim"), (z0 + 0.006, z0 + 0.03, "white"), (z0 + 0.03, z1 - 0.025, "red"), (z1 - 0.025, z1 - 0.004, "white"), (z1 - 0.004, z1, "rim")]
    for k in range(n):
        t0, t1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        for za, zb, name in bands:
            a = (r(za) * math.cos(t0), r(za) * math.sin(t0), za); b = (r(za) * math.cos(t1), r(za) * math.sin(t1), za)
            c = (r(zb) * math.cos(t1), r(zb) * math.sin(t1), zb); d = (r(zb) * math.cos(t0), r(zb) * math.sin(t0), zb)
            m.quad(name, a, b, c, d)
        # 위(밑면): 검은 테이프 원 + 바깥 테두리
        m.tri("tape", (0, 0, z1 + 0.0005), (0.026 * math.cos(t0), 0.026 * math.sin(t0), z1 + 0.0005), (0.026 * math.cos(t1), 0.026 * math.sin(t1), z1 + 0.0005))
        m.quad("rim", (0.026 * math.cos(t0), 0.026 * math.sin(t0), z1 + 0.0004), (R1 * math.cos(t0), R1 * math.sin(t0), z1), (R1 * math.cos(t1), R1 * math.sin(t1), z1), (0.026 * math.cos(t1), 0.026 * math.sin(t1), z1 + 0.0004))
        # 아래(입구, 뚜껑): 바닥 쪽을 보는 면
        m.tri("lid", (0, 0, z0), (R0 * math.cos(t1), R0 * math.sin(t1), z0), (R0 * math.cos(t0), R0 * math.sin(t0), z0))
    return m

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "meshes"); out.mkdir(parents=True, exist_ok=True)
    for name, f in (("choco", choco), ("shrimp", shrimp), ("ramen", ramen)):
        m = f(); m.write_dae(out / f"{name}.dae"); print(name, sum(len(t) for _, t in m.parts.values()), "삼각형")
