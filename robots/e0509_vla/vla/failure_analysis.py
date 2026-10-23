#!/usr/bin/env python3
"""집기 시도 기록 -> 실패 원인 추정. vla_run.py 가 한 번의 시도 기록(dict)을 넘기면 원인 목록과 문구(영문 RViz용, 한글 관제용)를 돌려준다.

정상 범위는 자동수집 성공 에피소드(초코송이 120, 새우깡 58)의 그리퍼 값 분포로 정한다(base_stats.json 에 캐시).
'필요 최소 힘'은 힘 측정 시험 결과 force_table.json 이 있을 때만 쓴다(없으면 '미측정'이라고 밝힌다).
"""
import glob, json, math
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EMPTY = {"choco": 150.0, "shrimp": 42.0, "ramen": 150.0}   # vla_run 빈손 기준과 같게 (이하면 손가락 사이에 아무것도 없음)
NAMES = {"choco": ("CHOCO", "초코송이"), "shrimp": ("SHRIMP", "새우깡"), "ramen": ("RAMEN", "컵라면")}

def base_stats():
    f = HERE / "twin" / "base_stats.json"
    if f.exists(): return json.loads(f.read_text())
    out = {}
    for obj, d in [("choco", "collect_choco"), ("shrimp", "collect")]:
        cp, cr = [], []
        for m in glob.glob(str(HERE / d / "2026*" / "ep*" / "meta.json")):
            x = json.loads(Path(m).read_text())
            if x.get("success") and x.get("in_basket") and x.get("closed_pos") is not None:
                cp.append(x["closed_pos"]); cr.append(x.get("carry_pos", np.nan) if x.get("carry_pos") is not None else np.nan)
        cp, cr = np.array(cp, float), np.array(cr, float)
        out[obj] = {"n": int(len(cp)), "closed_p10": float(np.nanpercentile(cp, 10)), "closed_p90": float(np.nanpercentile(cp, 90)),
                    "slip_p90": float(np.nanpercentile(cp - cr, 90)), "slip_p50": float(np.nanpercentile(cp - cr, 50))}
    f.parent.mkdir(exist_ok=True); f.write_text(json.dumps(out, indent=1)); return out

def force_table():
    f = HERE / "twin" / "force_table.json"
    return json.loads(f.read_text()) if f.exists() else {}

def analyze(rec):
    """rec 키: object, outcome('dropped'|'grasp_failed'|'not_in_basket'|'loaded'), current, cam_xy, policy_close_xy, close_xy,
       closed_pos, grip_trace[[t,pos,z],...](쥔 뒤), drop{t_after_grasp, z, phase, speed}, release_xy"""
    obj = rec.get("object", "choco"); en, ko = NAMES.get(obj, (obj, obj))
    st = base_stats().get(obj, {}); ft = force_table().get(obj)
    causes = []          # (코드, 영문, 한글)
    cur = rec.get("current")
    # 1) 위치: 정책이 고른 곳과 카메라 위치 차이 (카메라로 보정했으면 그 사실도)
    if rec.get("cam_xy") is not None and rec.get("policy_close_xy") is not None:
        d = math.dist(rec["cam_xy"], rec["policy_close_xy"])
        if d > 20:
            causes.append(("policy_offset", f"policy aimed {d:.0f} mm off the object (camera-corrected)",
                           f"정책이 물건 중심에서 {d:.0f}mm 벗어난 곳을 골랐음 (카메라로 보정해 닫음)"))
    # 2) 쥔 폭: 정상 범위 밖이면 모서리/비스듬히 잡은 것
    cp = rec.get("closed_pos")
    empty = cp is not None and cp <= EMPTY.get(obj, 42.0)
    if empty:
        # 2026-10-21: 빈손(31)을 "모서리 잡음"으로 잘못 냄 -> 빈손이면 쥔 폭 판정 대신 "물건 없음"
        causes.append(("missed", f"gripper closed fully ({cp:.0f} <= empty {EMPTY.get(obj, 42.0):.0f}): nothing between the fingers (missed the spot, object moved, or too thin to hold)",
                       f"그리퍼가 끝까지 닫힘({cp:.0f}, 빈손 기준 {EMPTY.get(obj, 42.0):.0f} 이하): 손가락 사이에 물건 없음. 위치가 빗나갔거나, 물건이 밀렸거나, 너무 얇아 안 잡힘"))
    elif cp is not None and st and obj == "choco":
        if cp < st["closed_p10"] - 20:
            causes.append(("edge_grip", f"grip width {cp:.0f} below normal {st['closed_p10']:.0f}-{st['closed_p90']:.0f}: likely gripped an edge/corner",
                           f"쥔 폭 {cp:.0f} 이 정상({st['closed_p10']:.0f}~{st['closed_p90']:.0f})보다 작음: 모서리·끝을 잡은 것으로 추정"))
        elif cp > st["closed_p90"] + 30:
            causes.append(("tilted_grip", f"grip width {cp:.0f} above normal: object tilted or gripped diagonally",
                           f"쥔 폭 {cp:.0f} 이 정상보다 큼: 물건이 기울었거나 비스듬히 잡은 것으로 추정"))
    # 3) 미끄러짐: 쥔 뒤 그리퍼 위치가 정상보다 많이 줄었는가 (새우깡 봉지는 값이 들쭉날쭉해 제외)
    tr = rec.get("grip_trace") or []
    if cp is not None and tr and obj == "choco":
        valid = [p for _, p, _ in tr if 60 < p < 700]
        if valid:
            slip = cp - min(valid)
            if slip > max(st.get("slip_p90", 90), 60):
                causes.append(("slip", f"slipping: gripper {cp:.0f} -> {min(valid):.0f} while holding (normal drop <= {st.get('slip_p90', 90):.0f})",
                               f"미끄러짐: 쥔 뒤 그리퍼가 {cp:.0f} -> {min(valid):.0f} 로 줄어듦 (정상 감소폭 {st.get('slip_p90', 90):.0f} 이하)"))
    # 4) 힘: 측정된 최소 힘이 있으면 비교
    if cur is not None:
        if ft and ft.get("min_current"):
            need = ft["min_current"]
            if cur < need:
                causes.append(("weak_force", f"gripped with current {cur:.0f}, but needs at least {need:.0f}",
                               f"전류 {need:.0f} 이상으로 잡아야 하는데 {cur:.0f} 로 잡았음"))
            elif rec.get("outcome") == "dropped" or any(c[0] == "slip" for c in causes):
                causes.append(("force_ok", f"grip current {cur:.0f} >= required {need:.0f}: force was enough, look at grip position",
                               f"전류 {cur:.0f} 는 필요 최소 {need:.0f} 이상: 힘은 충분했음, 잡은 위치를 확인"))
        elif any(c[0] == "slip" for c in causes) or rec.get("outcome") == "dropped":
            causes.append(("force_unknown", f"grip current {cur:.0f} (required minimum not measured yet)",
                           f"이번 전류 {cur:.0f} (이 물건의 필요 최소 힘은 아직 측정 전)"))
    # 5) 떨어진 시점
    dr = rec.get("drop")
    if dr:
        ph = dr.get("phase", "?")
        txt = {"lift": ("while lifting", "들어 올리는 중"), "carry": ("while carrying", "운반 중"), "basket": ("near the basket", "바구니 근처")}.get(ph, (ph, ph))
        causes.append(("drop_phase", f"dropped {txt[0]} ({dr.get('t_after_grasp', 0):.1f} s after grasp, z {dr.get('z', 0):.0f})",
                       f"{txt[1]} 떨어짐 (쥔 뒤 {dr.get('t_after_grasp', 0):.1f}초, 높이 z{dr.get('z', 0):.0f})"))
    if rec.get("outcome") == "grasp_failed" and not any(c[0] in ("missed", "edge_grip", "tilted_grip") for c in causes):
        causes.append(("missed", "closed on nothing: object not between the fingers", "손가락 사이에 물건이 없었음(위치 빗나감 또는 물건이 밀림)"))
    if rec.get("outcome") == "not_in_basket" and rec.get("release_xy") is not None:
        causes.append(("release_pos", f"released at x{rec['release_xy'][0]:.0f} y{rec['release_xy'][1]:.0f}", f"x{rec['release_xy'][0]:.0f} y{rec['release_xy'][1]:.0f} 에서 놓음"))
    if rec.get("outcome") == "timeout":
        causes.append(("timeout", "policy did not finish within max cycles (hovered without grasping or releasing)",
                       "정책이 정해진 횟수 안에 끝내지 못함 (잡거나 놓지 않고 맴돎)"))
    if not causes and rec.get("outcome") not in ("loaded",):
        causes.append(("unknown", "cause not identified from logged signals", "기록된 신호로는 원인을 특정하지 못함"))
    return {"object": obj, "outcome": rec.get("outcome"), "causes": [c[0] for c in causes],
            "en": [c[1] for c in causes], "ko": [c[2] for c in causes]}

if __name__ == "__main__":
    print(json.dumps(base_stats(), indent=1))
    print(json.dumps(analyze({"object": "choco", "outcome": "dropped", "current": 130, "cam_xy": [500, 0], "policy_close_xy": [560, 20],
                   "closed_pos": 180, "grip_trace": [[0.5, 170, 160], [1.5, 90, 230], [2.5, 40, 300]],
                   "drop": {"t_after_grasp": 2.5, "z": 300, "phase": "lift"}}), ensure_ascii=False, indent=1))
