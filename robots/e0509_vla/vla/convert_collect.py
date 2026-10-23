#!/usr/bin/env python3
"""자동 수집 에피소드(collect/*/ep*) -> LeRobot 데이터셋 (지난 SmolVLA 학습 데이터와 같은 특징 형식).
    ~/venv/il/bin/python convert_collect.py --out datasets/shrimp_auto_v1 <에피소드 폴더들...>
    (폴더를 안 주면 collect/ 아래 success+in_basket 인 바구니 에피소드를 모두 사용)
상태 8 : 관절6(rad, 이미지 시점), 그리퍼 열림비율(위치/750), 그리퍼 정보 경과(s)
행동 11: 0.1s 뒤 TCP 위치(m)3 + 회전행렬 앞 두 열 6 + 그리퍼 명령(열림1/닫힘0) + 전류명령/661
"""
import argparse, json, sys
from pathlib import Path
import numpy as np, cv2
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fk import Chain
from lerobot.datasets.lerobot_dataset import LeRobotDataset

TASK = "새우깡을 지정된 위치로 옮겨 놓아."
# 물체별: 명령 문장, 녹화 폴더 (collect.py OBJECTS 의 out 과 같게)
OBJECTS = {"shrimp": ("새우깡을 지정된 위치로 옮겨 놓아.", "collect"),
           "choco": ("초코송이를 지정된 위치로 옮겨 놓아.", "collect_choco"),
           "ramen": ("컵라면을 지정된 위치로 옮겨 놓아.", "collect_ramen")}
OPEN_CMD_CURRENT = 200.0
# 학습에서 뺄 에피소드: 경유점 경로로 바구니 턱에 걸린 판(2026-10-16 23:29)
EXCLUDE = ("20261016_232943",)    # 열기 명령 전류 (gripper_cmd(750, 200))
FEATURES = {
    "observation.state": {"dtype": "float32", "shape": (8,), "names": [
        "joint_1_rad", "joint_2_rad", "joint_3_rad", "joint_4_rad", "joint_5_rad", "joint_6_rad",
        "gripper_open_fraction", "gripper_feedback_age_s"]},
    "action": {"dtype": "float32", "shape": (11,), "names": [
        "next_desired_tcp_x_m", "next_desired_tcp_y_m", "next_desired_tcp_z_m",
        "next_desired_rotation_col0_row0", "next_desired_rotation_col0_row1", "next_desired_rotation_col0_row2",
        "next_desired_rotation_col1_row0", "next_desired_rotation_col1_row1", "next_desired_rotation_col1_row2",
        "commanded_gripper_open_fraction", "commanded_current_limit_fraction_of_661mA"]},
    "observation.images.overhead": {"dtype": "image", "shape": (480, 640, 3), "names": ["height", "width", "channels"]},
}

def episode_rows(ep):
    rows = [json.loads(l) for l in (ep / "frames.jsonl").open()]
    out = []
    for r in rows:
        ja = r.get("joints_at_image") or {}
        q = ja.get("position") or r.get("joints")
        ga = r.get("gripper_at_image") or {}
        gpos = ga.get("position", r.get("gripper_pos"))
        if ga.get("received_mono") is not None and r.get("image_received_mono") is not None:
            gage = r["image_received_mono"] - ga["received_mono"]
        else:
            gage = r.get("gripper_age_s")
        if q is None or gpos is None or gage is None: continue
        out.append({"img": ep / r["image"], "q": np.array(q, float), "g": float(gpos), "gage": float(gage),
                    "cmd_open": float(r.get("cmd_gripper_open", 1.0) if r.get("cmd_gripper_open") is not None else 1.0),
                    "cmd_cur": float(r["cmd_current"]) if r.get("cmd_current") is not None else OPEN_CMD_CURRENT,
                    "phase": r.get("phase")})
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("episodes", nargs="*")
    ap.add_argument("--object", choices=sorted(OBJECTS), default="shrimp")
    a = ap.parse_args()
    eps = [Path(e) if Path(e).is_absolute() else (HERE / e) for e in a.episodes]
    if not eps:
        for m in sorted((HERE / OBJECTS[a.object][1]).glob("*/ep*/meta.json")):
            d = json.loads(m.read_text())
            if any(x in str(m) for x in EXCLUDE): continue
            if d.get("success") and d.get("in_basket") and (m.parent / "frames.jsonl").exists(): eps.append(m.parent)
    out = Path(a.out) if Path(a.out).is_absolute() else HERE / a.out
    if out.exists(): print("이미 있음:", out); return 1
    FK = Chain()
    ds = LeRobotDataset.create(repo_id="local/" + out.name, fps=10, features=FEATURES, root=out,
                               robot_type="doosan_e0509_rh-p12-rn", use_videos=False,
                               image_writer_threads=8)   # 프레임 PNG 저장 병렬화 (단일 스레드는 에피소드당 ~1분)
    report = []
    for ep in eps:
        rows = episode_rows(ep)
        if len(rows) < 20: print("건너뜀(프레임 부족):", ep); continue
        poses = [FK.fk(r["q"]) for r in rows]
        for i, r in enumerate(rows):
            pn, Rn = poses[min(i + 1, len(rows) - 1)]            # 0.1s 뒤 위치·자세 = 이번 프레임의 행동
            act = np.concatenate([pn / 1000.0, Rn[:, 0], Rn[:, 1], [r["cmd_open"], r["cmd_cur"] / 661.0]]).astype(np.float32)
            state = np.concatenate([r["q"], [r["g"] / 750.0, r["gage"]]]).astype(np.float32)
            img = cv2.cvtColor(cv2.imread(str(r["img"])), cv2.COLOR_BGR2RGB)
            ds.add_frame({"observation.state": state, "action": act, "observation.images.overhead": img, "task": OBJECTS[a.object][0]})
        ds.save_episode()
        moves = np.linalg.norm(np.diff(np.array([p[0] for p in poses]), axis=0), axis=1)
        report.append({"episode": str(ep.relative_to(HERE)), "frames": len(rows),
                       "step_mm_median": float(np.median(moves)), "idle_frac": float((moves < 0.5).mean())})
        print(f"추가: {ep.relative_to(HERE)}  프레임 {len(rows)}  0.1s 이동 중앙값 {np.median(moves):.2f}mm  정지비율 {(moves < 0.5).mean():.0%}", flush=True)
    ds.finalize()
    (out / "conversion_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("완료:", out, f"에피소드 {len(report)}개, 프레임 {sum(r['frames'] for r in report)}")

if __name__ == "__main__":
    sys.exit(main())
