"""텍스처(사진) 입힌 상자 .dae. 원점=중심, 단위 m.  면 -> atlas 사각형(픽셀) 매핑."""
from pathlib import Path
def textured_box(path, tex_name, size, atlas_wh, faces):
    """faces: [(코너 4개 [(x,y,z)...] 바깥에서 볼 때 반시계: 사진의 TL,TR,BR,BL 순), (atlas x0,y0,w,h)]"""
    W, H = atlas_wh; pos, nor, uv, p = [], [], [], []
    import numpy as np
    for k, (cs, (x0, y0, w, h)) in enumerate(faces):
        cs = [np.array(c, float) for c in cs]
        # 바깥 방향 = (오른쪽 x 위쪽): 사진이 거울상으로 안 보이게 코너를 넣었다는 전제. 삼각형 감는 방향은 그 법선에 맞춘다
        right, up = cs[1] - cs[0], cs[0] - cs[3]; n = np.cross(right, up); n = n / np.linalg.norm(n)
        tri = ((0, 3, 2), (0, 2, 1)) if np.dot(np.cross(cs[3] - cs[0], cs[2] - cs[0]), n) > 0 else ((0, 2, 3), (0, 1, 2))
        uvs = [(x0 / W, 1 - y0 / H), ((x0 + w) / W, 1 - y0 / H), ((x0 + w) / W, 1 - (y0 + h) / H), (x0 / W, 1 - (y0 + h) / H)]
        b = len(pos)
        for c, t in zip(cs, uvs): pos.append(c); uv.append(t)
        nor.append(n); ni = len(nor) - 1
        # TL,BL,BR  /  TL,BR,TR  (바깥 법선 방향으로 반시계)
        for a, bb, cc in tri:
            for v in (a, bb, cc): p += [b + v, ni, b + v]
    f = lambda xs: " ".join(f"{x:.5f}" for x in xs)
    P = [c for v in pos for c in v]; N = [c for v in nor for c in v]; T = [c for v in uv for c in v]
    ntri = len(faces) * 2
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">'
      '<asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset>'
      f'<library_images><image id="img"><init_from>{tex_name}</init_from></image></library_images>'
      '<library_effects><effect id="eff"><profile_COMMON>'
      '<newparam sid="surf"><surface type="2D"><init_from>img</init_from></surface></newparam>'
      '<newparam sid="samp"><sampler2D><source>surf</source></sampler2D></newparam>'
      '<technique sid="c"><lambert><diffuse><texture texture="samp" texcoord="UV0"/></diffuse></lambert></technique></profile_COMMON></effect></library_effects>'
      '<library_materials><material id="mat" name="tex"><instance_effect url="#eff"/></material></library_materials>'
      '<library_geometries><geometry id="g"><mesh>'
      f'<source id="gp"><float_array id="gpa" count="{len(P)}">{f(P)}</float_array><technique_common><accessor source="#gpa" count="{len(pos)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>'
      f'<source id="gn"><float_array id="gna" count="{len(N)}">{f(N)}</float_array><technique_common><accessor source="#gna" count="{len(nor)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>'
      f'<source id="gt"><float_array id="gta" count="{len(T)}">{f(T)}</float_array><technique_common><accessor source="#gta" count="{len(uv)}" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>'
      '<vertices id="gv"><input semantic="POSITION" source="#gp"/></vertices>'
      f'<triangles material="m" count="{ntri}"><input semantic="VERTEX" source="#gv" offset="0"/><input semantic="NORMAL" source="#gn" offset="1"/><input semantic="TEXCOORD" source="#gt" offset="2" set="0"/><p>{" ".join(map(str, p))}</p></triangles>'
      '</mesh></geometry></library_geometries>'
      '<library_visual_scenes><visual_scene id="s"><node id="n"><instance_geometry url="#g"><bind_material><technique_common>'
      '<instance_material symbol="m" target="#mat"><bind_vertex_input semantic="UV0" input_semantic="TEXCOORD" input_set="0"/></instance_material>'
      '</technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes>'
      '<scene><instance_visual_scene url="#s"/></scene></COLLADA>')
    Path(path).write_text(xml)

if __name__ == "__main__":
    import sys
    sx, sy, sz = 0.035, 0.12, 0.085; X, Y, Z = sx / 2, sy / 2, sz / 2
    # 세워 놓은 상자: x=3.5 폭, y=12 길이, z=8.5 높이.  사진 세로(12)=y(+Y 가 위쪽), 앞뒤 사진 가로(8.5)=z(+Z 가 왼쪽)
    faces = [
      ([(X, Y, Z), (X, Y, -Z), (X, -Y, -Z), (X, -Y, Z)], (0, 0, 850, 1200)),          # +x 앞면
      ([(-X, Y, -Z), (-X, Y, Z), (-X, -Y, Z), (-X, -Y, -Z)], (850, 0, 850, 1200)),    # -x 뒷면
      ([(-X, Y, Z), (X, Y, Z), (X, -Y, Z), (-X, -Y, Z)], (1700, 0, 350, 1200)),       # +z 윗면(로고, 위 카메라에 보임)
      ([(X, Y, -Z), (-X, Y, -Z), (-X, -Y, -Z), (X, -Y, -Z)], (1700, 0, 350, 1200)),   # -z 바닥 (윗면 사진 재사용)
      ([(-X, Y, Z), (-X, Y, -Z), (X, Y, -Z), (X, Y, Z)], (0, 1200, 850, 350)),       # +y 끝면(영양정보): 사진 가로(8.5)=z
      ([(X, -Y, Z), (X, -Y, -Z), (-X, -Y, -Z), (-X, -Y, Z)], (0, 1200, 850, 350)),   # -y 끝면
    ]
    textured_box(sys.argv[1], "choco_tex.jpg", (sx, sy, sz), (2050, 1550), faces)
    print("ok")
