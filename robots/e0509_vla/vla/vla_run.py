#!/usr/bin/env python3
"""SmolVLA(새우깡) 실기 실행기 — 잡음 0 추론 + 그리퍼 히스테리시스 + 감시 이동.

매 사이클(약 1초): 카메라·관절·그리퍼 -> 5초 계획(잡음 0) -> 계획의 K번째(기본 10 = 1초 뒤) 지점으로 감시 이동.
그리퍼: 열림 상태에서 계획이 확실히 닫기(<0.3) -> 닫기 시작 지점으로 간 뒤 멈춰서 닫고, 손가락이 멈출 때까지 대기.
        닫힘 상태에서 계획이 확실히 열기(>0.7) -> 바구니 위 영역에서만 연다. 다른 곳에서는 무시.
안전: 이동마다 경로 사전검사 + 이탈 15mm 즉시정지 + 도착 확인. z<250 은 그리퍼 '열림'이 읽혀야 내려감.
      베이스 근처(x<420)는 낮게(z<250) 가지 않음. 문제가 생기면 위로만 빠지고 멈춤. 공중에서 열지 않음.

    python3 vla_run.py --point 514 25     # 그 칸 위(z300)를 가리키고 끝 (새우깡 놓기용)
    python3 vla_run.py                    # 시작 자세 -> 정책 실행
"""
import argparse, os, json, math, subprocess, sys, threading, time
from pathlib import Path

import cv2, numpy as np, rclpy
from sensor_msgs.msg import JointState

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fk import Chain, zyz_to_matrix
from path_check import ik as _ik, jac as _jac

VENV_PY = "/home/omen/venv/il/bin/python"
CAMERA = "/dev/video8"; ROBOT_IP = "110.120.1.59"
ORI = [0.0, 180.0, 0.0]
START = (430.0, 13.0, 427.0)
HARD_FLOOR, LOW_Z = 115.0, 250.0
NEAR_BASE_X = 330.0   # 2026-10-20: 수집이 x330 까지 넓어져(1·4·7번 칸 포함) 420 -> 330. 관절·특이점은 경로 사전검사가 막음
BOUNDS_X, BOUNDS_Y, BOUNDS_Z = (330.0, 700.0), (-520.0, 200.0), (115.0, 470.0)
RELEASE_ZONE = dict(y_max=-420.0, z_min=380.0)          # 바구니(350,-500,~430) 위
K = 10                                                   # 계획 중 1초 뒤 지점까지 실행
MAX_STEP_MM, V_MAX, V_MIN = 80.0, 60.0, 5.0
CLOSE_TH, OPEN_TH = 0.3, 0.7
# 물체별 기본값 (--object). 빈손 기준: 새우깡 42(봉지 끝을 얇게 물면 60쯤), 초코송이 150(쥐면 250~410, 빈손 29)
OBJECTS = {"shrimp": dict(ckpt="/home/omen/doosan_ws/vla_test/train/20261019_1401_shrimp_auto_v2/smolvla/checkpoints/015000/pretrained_model",
                          task="새우깡을 지정된 위치로 옮겨 놓아.", empty=42.0, z_offset=0.0),
           "choco": dict(ckpt="/home/omen/doosan_ws/vla_test/train/20261020_1226_choco_auto_v2/smolvla/checkpoints/015000/pretrained_model",   # 120편(10-20). 60편 모델: train/20261019_1847_choco_auto_v1/...
                         task="초코송이를 지정된 위치로 옮겨 놓아.", empty=150.0, z_offset=15.0, current=80),
           # 2026-10-21 컵라면: 거꾸로 세우고(입구가 바닥) 위로 온 밑면에 검은 테이프. 손끝이 윗면 25mm 아래(z186 @ x534 y-49, 실기 확인)
           # = 칸 높이+5 위로 +53mm. 학습 모델은 아직 없음(ckpt None: 힘 시험·--home 만 가능)
           "ramen": dict(ckpt="/home/omen/doosan_ws/vla_test/train/20261021_1749_ramen_auto_v1/smolvla/checkpoints/015000/pretrained_model", task="컵라면을 지정된 위치로 옮겨 놓아.", empty=150.0, z_offset=53.0, current=80)}   # current: 종이컵이라 130 대신 80 (힘 시험 40 도 버팀)   # z_offset: collect.py 와 같게
GRIP_CURRENT, GRIP_OPEN_OK, GRIP_EMPTY = 130, 700.0, 42.0   # 빈손 기준 42: 수집과 같음(봉지 끝을 얇게 물면 60 정도로 읽힘, 18:27 실측)
SETTLE_S, SETTLE_MAX_S = 1.5, 15.0   # 10-21 2.5 -> 1.5 (키오스크 1개 2분 걸림)
DEV_MAX_MM, MANIP_MIN, J2_RANGE, J3_MAX, ELBOW_X_MIN = 15.0, 0.020, (-15.0, 60.0), 125.0, -60.0
MAX_CYCLES = 60
AIR_FLOOR = 260.0     # 공중 시험 최저 높이 (수집 때 가리키기 높이와 같음)
# 실제 잡기 최저 높이: 수집 때와 똑같이 9칸 교시 높이 IDW + 5mm. 정책이 이보다 낮게 가려 하면 이 높이로 깎는다
# (2026-10-19 5번 칸 공중 시험에서 정책 계획 최저점 z108 = 수집 잡는 높이 z135 보다 27mm 낮음)
_CELLS = json.loads((HERE / "shrimp_cells.json").read_text())
_CP = np.array([v[:2] for v in _CELLS.values()]); _CZ = np.array([v[2] for v in _CELLS.values()])
def near_gripper(obj, frame):
    """찾은 물건(픽셀)이 시작 자세 그리퍼 자리(사진 위쪽 가운데)에 닿거나 걸치는가. 걸치면 보이는 부분만으로 중심을 잡아 비켜 계산됨"""
    try:
        if obj == "ramen":
            from ramen_vision import find_cup
            c = find_cup(frame); return c is not None and c[1] < 190 and abs(c[0] - 335) < 110
        if obj == "shrimp":
            from bag_vision import bag_region, set_object
            set_object("shrimp"); br = bag_region(frame)
            if br is None: return False
            ys, xs = np.nonzero(br[0]); return bool(((ys < 150) & (np.abs(xs - 335) < 50)).any())
        if obj == "choco":
            from choco_vision import find_box
            b = find_box(frame); return b is not None and b[1] < 175 and abs(b[0] - 335) < 90
    except Exception: return False
    return False
LOOK = (430.0, 250.0, 450.0)   # 10-22 오후: 바구니 쪽(x400 y-350)으로 왔다 가는 게 헛걸음처럼 보임(사용자) -> 작업대 오른쪽 바깥. 경로 조작성 0.051 이상(random_area_check 로 계산)
_LOOK_OLD = (400.0, -350.0, 450.0)   # 10-22: 팔을 비켜 작업대 전체를 보는 자세(수집 때 매번 오가던 바구니 쪽 대기 자세). 그리퍼가 작업대 밖
def cam_locate(obj, frame, occl=True, px_out=None):
    """시작 자세 위 카메라 사진에서 물체 위치(책상 좌표 mm). 못 찾으면 None.
    초코송이: 노란 상자 + 초코송이 120편으로 맞춘 2차식 / 새우깡: 빨간 봉지 + 새우깡 56편으로 맞춘 1차식(오차 중앙값 12mm)"""
    if obj == "choco":
        from choco_vision import find_box
        # 2026-10-21: 새우깡 봉지가 같이 있으면 봉지의 주황·노란 과자 그림을 초코송이로 봄(바구니에 넣었는데 '적재 실패') -> 봉지 영역은 가리고 찾는다
        # 컵(검은 테이프)은 봉지를 검게 칠하기 전 원본에서 찾는다 (10-22 15:23: 칠한 봉지 자리가 테이프와 이어져 컵을 못 찾음 -> 또 컵라면을 초코송이로 보고 내려가 충돌)
        from ramen_vision import find_cup
        cup = find_cup(frame, start_pose=occl)
        from bag_vision import bag_region, set_object
        set_object("shrimp"); frame = frame.copy()
        for _ in range(3):   # 10-23: 새우깡 봉지가 2개 이상이면 모두 가린다
            bag = bag_region(frame)
            if bag is None: break
            frame[cv2.dilate(bag[0], np.ones((31, 31), np.uint8)) > 0] = 0
        # 10-22: 거꾸로 세운 컵라면의 노란 몸통을 초코송이로 봄(바구니에 넣었는데 적재 실패 -> 컵라면 위로 내려가다 축2 충돌). 컵 둘레도 가린다
        if cup is not None:
            frame = frame.copy(); cv2.circle(frame, (int(cup[0]), int(cup[1])), 60, (0, 0, 0), -1)
        br = find_box(frame)
        if br is None: return None
        W = np.array(json.loads((HERE / "cam_choco_pix2xy.json").read_text())); px, py = br[0], br[1]
        if px_out is not None: px_out[:] = [px, py]
        return np.r_[px, py, px * py, px ** 2, py ** 2, 1.0] @ W
    if obj == "ramen":
        # 검은 테이프 동그라미 -> 컵라면 수집 29편으로 맞춘 2차식(cam_ramen_fit.py, 한 편 빼고 오차 중앙값 6mm)
        # 사진 위쪽(py<175 = 로봇 쪽 1·4·7번 칸 근처)은 시작 자세 그리퍼와 겹쳐 테이프를 잘못 잡음 -> 못 찾은 것으로
        from ramen_vision import find_cup
        c = find_cup(frame, start_pose=occl)   # 시작 자세 사진이면 그리퍼 자리를 가리고 찾음
        # 10-22: 위쪽 전체(py<175)를 막으니 그리퍼와 안 겹친 1번 칸 컵도 버림 -> 그리퍼 바로 아래(위쪽 가운데)만 막음
        if c is None or (occl and c[1] < 175 and abs(c[0] - 335) < 75): return None   # occl: 팔이 시작 자세일 때만
        W = np.array(json.loads((HERE / "cam_ramen_pix2xy.json").read_text())); px, py = c[0], c[1]
        if px_out is not None: px_out[:] = [px, py]
        return np.r_[px, py, px * py, px ** 2, py ** 2, 1.0] @ W
    from bag_vision import bag_region, set_object
    from choco_vision import ROI
    f2 = np.zeros_like(frame); x0, x1, y0, y1 = ROI; f2[y0:y1, x0:x1] = frame[y0:y1, x0:x1]   # 작업대 영역만
    set_object("shrimp"); br = bag_region(f2)
    if br is None: return None
    W = np.array(json.loads((HERE / "cam_pix2xy.json").read_text()))
    if px_out is not None: px_out[:] = [br[2][0], br[2][1]]
    return np.r_[br[2], 1.0] @ W

_ERASE_PX = {"shrimp": 80, "choco": 55, "ramen": 60}
def cam_locate_all(obj, frame, occl=True, n=3):
    """10-23: 같은 상품이 여러 개일 때 모두 찾기(트윈 표시용). 찾은 자리를 흰색(작업대 색)으로 지우고 다시 찾는다."""
    f2 = frame.copy(); out = []
    for _ in range(n):
        p = []; xy = cam_locate(obj, f2, occl=occl, px_out=p)
        if xy is None or not p: break
        out.append(xy); cv2.circle(f2, (int(p[0]), int(p[1])), _ERASE_PX.get(obj, 60), (255, 255, 255), -1)
    return out

OBJ_Z = 0.0   # 물체별 잡는 높이 추가분 (--object 로 정해짐, collect.py OBJECTS 와 같게)
def grasp_floor(x, y):
    d = np.linalg.norm(_CP - [x, y], axis=1)
    if d.min() < 1e-6: return float(_CZ[d.argmin()]) + 5.0 + OBJ_Z
    w = 1.0 / d ** 2; return float((w * _CZ).sum() / w.sum()) + 5.0 + OBJ_Z
GRIP_FRESH_S = 5.0


class Stop(Exception):
    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--point", type=float, nargs=2)
    ap.add_argument("--ckpt", default=None,
                    help="모델 체크포인트(pretrained_model). 'codex' 면 10-16 모델")
    ap.add_argument("--task", default=None)
    ap.add_argument("--holding", action="store_true", help="지금 그리퍼가 봉지를 물고 있음(사람이 확인): 시작 자세로 안 가고 그 자리에서 정책 이어서(들기->바구니)")
    ap.add_argument("--air", action="store_true", help=f"공중 시험: z{AIR_FLOOR:.0f} 아래로 안 내려가고, 정책이 닫으려 하면 그 지점을 알려주고 멈춤")
    ap.add_argument("--cycles", type=int, default=MAX_CYCLES)
    ap.add_argument("--object", choices=sorted(OBJECTS), default="shrimp", help="모델·명령 문장·빈손 기준 묶음")
    ap.add_argument("--start-offset", type=float, nargs=2, default=[0.0, 0.0], metavar=("DX", "DY"),
                    help="시작 자세를 한 번만 옮겨 두고(높은 곳) 정책은 보정 없이 실행(mm). 정책이 지금 위치 기준으로 계획해서 그만큼 옮겨진 곳으로 내려옴")
    ap.add_argument("--cam-assist", action="store_true",
                    help="초코송이: 첫 사진에서 노란 상자 위치를 재서, 닫는 위치를 카메라 위치로 맞춤(정책 지점과 20mm 넘게 다르면). 못 찾으면 --close-offset 으로")
    ap.add_argument("--cam-start", action="store_true",
                    help="초코송이(방법 B): 시작 자세에서 카메라로 상자를 찾아 그 바로 위(z260)로 먼저 옮긴 뒤 정책 시작. 닫을 때 --cam-assist 처럼 한 번 더 맞춤")
    ap.add_argument("--far-x-offset", type=float, default=0.0,
                    help="정책 닫기 지점 x 가 600 을 넘으면 x 에 더할 값(mm). 2026-10-20 먼 쪽에서 2.5~7cm 덜 감")
    ap.add_argument("--close-offset", type=float, nargs=2, default=[0.0, 0.0], metavar=("DX", "DY"),
                    help="정책이 닫기로 정한 지점을 한 번만 옮겨서 닫음(mm). z260 으로 올라가 옆으로 옮긴 뒤 수직 하강. 매 사이클 누적하지 않음")
    ap.add_argument("--cam-grasp", action="store_true", help="(--cam-start 와 같이) 잡기는 카메라 위치에서 직접 수직 하강해 닫고, 들기·운반·놓기만 정책")
    ap.add_argument("--home", action="store_true", help="실패 뒤 정리(재시도용): 그리퍼 열고 위로 먼저 올린 뒤 시작 자세로. 내려가지 않음")
    ap.add_argument("--force-test", type=float, default=None, metavar="CURRENT",
                    help="힘 측정 시험(--cam-start 와 같이): 정책 없이 카메라 위치에서 이 전류로 쥐고 5cm 들어 3초 버틴 뒤 좌우로 흔들어 봄. 결과는 twin/force_trials.jsonl")
    a = ap.parse_args()
    global GRIP_EMPTY, OBJ_Z, GRIP_CURRENT
    if a.force_test is not None:
        if not a.cam_start: print("--force-test 는 --cam-start 와 같이 써야 함"); return 1
        if not 30.0 <= a.force_test <= 400.0: print("전류는 30~400 사이로"); return 1
        GRIP_CURRENT = a.force_test
    o = OBJECTS[a.object]; GRIP_EMPTY = o["empty"]; OBJ_Z = o["z_offset"]
    if a.force_test is None and o.get("current"): GRIP_CURRENT = o["current"]   # 물체별 파지 전류 (없으면 130)
    if a.ckpt is None: a.ckpt = o["ckpt"]
    if a.task is None: a.task = o["task"]
    print(f"물체 {a.object}: 빈손 기준 {GRIP_EMPTY:.0f}, 잡는 높이 +{OBJ_Z:.0f}mm", flush=True)

    import DR_init
    DR_init.__dsr__id, DR_init.__dsr__model = "dsr01", "e0509"
    rclpy.init(); node = rclpy.create_node("vla_run", namespace="dsr01"); DR_init.__dsr__node = node
    from std_msgs.msg import String as _Str
    ev_pub = node.create_publisher(_Str, "pick/event", 10)   # 디지털 트윈(twin/twin_node.py)·관제로 보내는 이벤트
    def emit(event, **kw):
        m = _Str(); d = {"event": event, "object": a.object, "t": time.time()}
        d.update({k: (np.asarray(v, float).round(1).tolist() if hasattr(v, "__len__") else float(v)) for k, v in kw.items()})
        m.data = json.dumps(d); ev_pub.publish(m)
        # 실패 원인 분석용 시도 기록 (failure_analysis.py). 끝 이벤트가 오면 분석해서 "analysis" 이벤트와 twin/attempts.jsonl 로 남긴다.
        if event == "located": rec["cam_xy"] = d["xy"][:2]
        elif event in ("grasped", "grasp_failed"):
            rec["close_xy"] = d["xyz"][:2]; rec["closed_pos"] = d["closed_pos"]; rec["t_grasp"] = time.time()
        elif event == "dropped":
            z, y = d["xyz"][2], d["xyz"][1]
            rec["drop"] = {"z": z, "phase": "lift" if z < 440.0 else ("basket" if y < -380.0 else "carry"),
                           "t_after_grasp": time.time() - rec.get("t_grasp", time.time())}
        elif event == "released": rec["release_xy"] = d["xyz"][:2]
        if event in ("grasp_failed", "dropped", "not_in_basket", "loaded", "timeout") and "outcome" not in rec: finish(event)
    rec = {"object": a.object, "current": float(GRIP_CURRENT), "force_test": a.force_test is not None, "t_start": time.time(), "grip_trace": []}
    def finish(outcome):
        rec["outcome"] = outcome
        rec["t_end"] = time.time()   # 10-22 성공률·소요 시간 측정(measure_report.py)
        try:
            import failure_analysis as FA; res = FA.analyze(rec)
        except Exception as e:
            res = {"causes": ["analysis_error"], "en": [f"analysis error: {e}"], "ko": [f"분석 오류: {e}"]}
        rec["analysis"] = res
        try:
            with (HERE / "twin" / "attempts.jsonl").open("a") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e: print("     (시도 기록 저장 실패)", e, flush=True)
        m = _Str(); m.data = json.dumps({"event": "analysis", "object": a.object, "t": time.time(), "outcome": outcome,
                                          "causes": res["causes"], "en": res["en"], "ko": res["ko"]}, ensure_ascii=False); ev_pub.publish(m)
        if res["ko"]: print("     [원인 분석] " + " / ".join(res["ko"]), flush=True)
    from DSR_ROBOT2 import amovel, posx, get_current_posx, DR_BASE
    from dsr_msgs2.srv import GetRobotMode, GetRobotState, MoveStop
    from dsr_gripper import gripper_cmd, gripper_wait

    sh = {}
    def on_js(m):
        d = dict(zip(m.name, m.position))
        if "joint_1" in d:
            sh["q"] = [d[f"joint_{i}"] for i in range(1, 7)]; sh["q_t"] = time.monotonic()
            dv = dict(zip(m.name, m.velocity)) if len(m.velocity) == len(m.name) else {}
            sh["qd"] = [dv.get(f"joint_{i}", 0.0) for i in range(1, 7)]
    def on_g(m):
        sh["g"] = m.position[0]; sh["g_t"] = time.monotonic()
    node.create_subscription(JointState, "/dsr01/joint_states", on_js, 10)
    node.create_subscription(JointState, "/dsr01/gripper/state", on_g, 10)
    stop_cli = node.create_client(MoveStop, "/dsr01/dsr_controller2/motion/move_stop")
    FKC, FK3 = Chain(), Chain(tip="link_3"); R_ORI = zyz_to_matrix(*ORI)

    def spin_for(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end: rclpy.spin_once(node, timeout_sec=0.02)

    def stop_now():
        stop_cli.wait_for_service(timeout_sec=1.0)
        f = stop_cli.call_async(MoveStop.Request(stop_mode=1)); rclpy.spin_until_future_complete(node, f, timeout_sec=2.0)

    def fresh_q():
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.01)
            if "q_t" in sh and time.monotonic() - sh["q_t"] < 0.3: return np.array(sh["q"])
        raise Stop("관절 상태가 안 들어옴")

    def grip():
        spin_for(0.05)
        t_w = time.monotonic()   # 시작 직후 첫 그리퍼 상태(약 1.5Hz)가 오기 전이면 최대 8초 기다림
        while "g_t" not in sh and time.monotonic() - t_w < 8.0: spin_for(0.1)
        if "g_t" not in sh or time.monotonic() - sh["g_t"] > GRIP_FRESH_S: raise Stop("그리퍼 상태를 믿을 수 없음")
        return sh["g"]

    def check_robot():
        for srv, name, attr in ((GetRobotMode, "get_robot_mode", "robot_mode"), (GetRobotState, "get_robot_state", "robot_state")):
            c = node.create_client(srv, f"/dsr01/dsr_controller2/system/{name}")
            if not c.wait_for_service(timeout_sec=3.0): raise Stop(f"{name} 서비스 없음")
            f = c.call_async(srv.Request()); rclpy.spin_until_future_complete(node, f, timeout_sec=5.0)
            if getattr(f.result(), attr, None) != 1: raise Stop(f"{name}={getattr(f.result(), attr, None)} (AUTONOMOUS+STANDBY 아님)")
        # 한 번씩 튀는 ping(16~87ms) 때문에 멈추지 않게 7개 중앙값 (collect.py 와 같음)
        out = subprocess.run(["ping", "-c", "7", "-i", "0.2", "-W", "1", ROBOT_IP], capture_output=True, text=True).stdout
        t_ = sorted(float(l.split("time=")[1].split()[0]) for l in out.splitlines() if "time=" in l)
        med = t_[len(t_) // 2] if len(t_) >= 5 else None
        if med is None or med > 10.0: raise Stop(f"로봇 응답 느림 (ping 중앙값 {med})")
        if (HERE / "STOP").exists(): raise Stop("STOP 파일")

    def check_path(q0, p0, target):
        q = np.array(q0, float); worst = 9.0; mans = []
        for t in np.linspace(0.0, 1.0, 8):
            pt = p0 + (target - p0) * t
            q, err = _ik(q, pt, R_ORI, it=40)
            if err > 2.0: raise Stop(f"경로 사전검사: 도달 불가 @ {pt.round(0)}")
            J = _jac(q); m_ = math.sqrt(max(np.linalg.det(J @ J.T), 0.0)); mans.append(m_); worst = min(worst, m_)
            jd = np.degrees(q)
            if not (J2_RANGE[0] <= jd[1] <= J2_RANGE[1]) or jd[2] > J3_MAX:
                raise Stop(f"경로 사전검사: 관절 범위 밖 (j2 {jd[1]:.0f}, j3 {jd[2]:.0f}) @ {pt.round(0)}")
            if FK3.fk(q)[0][0] < ELBOW_X_MIN: raise Stop(f"경로 사전검사: 팔꿈치가 베이스 뒤로 @ {pt.round(0)}")
        if mans[0] < MANIP_MIN:   # 출발점이 특이점 근처: 단조롭게 좋아지고 끝이 기준 이상이면 통과
            if min(mans[1:]) < mans[0] - 1e-4 or mans[-1] < MANIP_MIN:
                raise Stop(f"경로 사전검사: 특이점 근처에서 더 나빠지는 길 ({mans[0]:.3f} -> 최저 {min(mans):.3f}, 끝 {mans[-1]:.3f})")
            worst = MANIP_MIN
        if worst < MANIP_MIN: raise Stop(f"경로 사전검사: 특이점 근접 ({worst:.3f})")

    def safe_target(p):
        """정책 목표를 그대로 쓰되, 위험하면 거부(대체 목표를 만들지 않음)."""
        x, y, z = p
        if a.air and z < AIR_FLOOR: p[2] = z = AIR_FLOOR     # 공중 시험: 높이만 깎는다(수평 위치는 정책 그대로)
        if z < grasp_floor(x, y): p[2] = z = grasp_floor(x, y)   # 수집 때 잡는 높이보다 낮게는 안 감
        if not (BOUNDS_X[0] <= x <= BOUNDS_X[1] and BOUNDS_Y[0] <= y <= BOUNDS_Y[1] and BOUNDS_Z[0] <= z <= BOUNDS_Z[1]):
            raise Stop(f"작업영역 밖 목표 {np.round(p, 0)}")
        if z < LOW_Z and x < NEAR_BASE_X: raise Stop(f"베이스 근처 낮은 목표 거부 {np.round(p, 0)}")
        if z < LOW_Z and z < FKC.fk(fresh_q())[0][2] - 1.0:   # 내려가는 목표만 (10-21: 새우깡 들어 올리는 중 그리퍼 값이 낮게 읽혀 멈추지 않게)
            g = grip()
            if g < GRIP_OPEN_OK and not (GRIP_EMPTY < g):     # 닫혀 있고 빈손이면 낮게 가지 않는다
                raise Stop(f"그리퍼가 닫힌 빈손(위치 {g:.0f})인데 낮은 곳으로 가려 함 -> 거부")

    def go(p, v, name):
        target = np.array(p, float)
        q0 = fresh_q(); p0 = FKC.fk(q0)[0]
        if np.linalg.norm(target - p0) < 0.5: return
        # 10-22: 바구니 보호 구역 (바구니 X350·Y-500, 36x26cm, 높이 30cm + 여유). 경로가 이 위를 z430 아래로 지나면 거부
        for t_ in np.linspace(0.0, 1.0, 12):
            pt_ = p0 + (target - p0) * t_
            if pt_[2] < 430.0 and 150.0 <= pt_[0] <= 560.0 and -680.0 <= pt_[1] <= -330.0:
                raise Stop(f"{name}: 경로가 바구니 위를 낮게 지남 (x{pt_[0]:.0f} y{pt_[1]:.0f} z{pt_[2]:.0f}) -> 거부")
        check_path(q0, p0, target)
        seg = target - p0; L = float(np.linalg.norm(seg)); t0 = time.monotonic(); maxdev = 0.0
        amovel(posx(list(target) + ORI), vel=[v, 30.0], acc=[2 * v, 60.0], ref=DR_BASE)
        while True:
            q = fresh_q(); pf = FKC.fk(q)[0]
            s_ = float(np.clip(np.dot(pf - p0, seg) / (L * L), 0.0, 1.0))
            dev = float(np.linalg.norm(pf - (p0 + s_ * seg))); maxdev = max(maxdev, dev)
            if dev > DEV_MAX_MM: stop_now(); raise Stop(f"{name}: 경로 이탈 {dev:.0f}mm -> 즉시 정지")
            if np.linalg.norm(pf - target) < 1.0 and max(abs(x) for x in sh.get("qd", [0] * 6)) < 0.005: break
            if time.monotonic() - t0 > L / v * 1.6 + 5.0:
                # 10-22: 바구니 위 특이점 구역에서 목표 1.7mm 앞에 멈춘 채(1mm 기준 못 채움) 시간 초과 -> 컵라면 문 채 주문 실패. 5mm 안이면 도착으로 봄
                if np.linalg.norm(pf - target) < 5.0: stop_now(); print(f"     ({name}: 목표 {np.linalg.norm(pf - target):.1f}mm 앞에서 멈춤 -> 도착으로 봄)", flush=True); break
                stop_now(); raise Stop(f"{name}: 시간 초과")
        log({"move": name, "from": p0.tolist(), "to": target.tolist(), "max_dev": maxdev})

    def close_gripper():
        gripper_cmd(0, GRIP_CURRENT)
        # 2026-10-20 17:24: 상태 갱신이 느려(0.8Hz) 닫기 시작 전의 750 을 '멈춤'으로 보고 750 을 돌려줌 -> 열린 채 운반.
        # 위치가 실제로 줄어들기 시작할 때까지(700 미만) 최대 8초 기다린다. 안 줄면 멈춤.
        t_s = time.monotonic()
        while grip() >= GRIP_OPEN_OK and time.monotonic() - t_s < 8.0: spin_for(0.1)
        if grip() >= GRIP_OPEN_OK: raise Stop("닫기 명령 뒤 8초가 지나도 그리퍼가 닫히기 시작하지 않음 -> 멈춤")
        st = gripper_wait(timeout=12.0)
        if st is None: raise Stop("닫은 뒤 그리퍼 상태 못 읽음")
        last, t0 = st["position"], time.monotonic(); tc = t0
        while time.monotonic() - tc < SETTLE_S and time.monotonic() - t0 < SETTLE_MAX_S:
            p = grip()
            if abs(p - last) > 3.0: last, tc = p, time.monotonic()
        return last

    run = HERE / "runs" / ("vla_" + time.strftime("%Y%m%d_%H%M%S")); run.mkdir(parents=True)
    lf = (run / "log.jsonl").open("w")
    def log(d): d["t"] = time.time(); lf.write(json.dumps(d) + "\n"); lf.flush()

    # 10-21: 그리퍼 상태 읽기는 컨트롤러 부하라 평소엔 꺼 두고(gripper_service state_on_start:=false), 이 실행 동안만 켠다
    from std_srvs.srv import SetBool
    st_cli = node.create_client(SetBool, "/dsr01/gripper/state_enable")
    def grip_state(on):
        if not st_cli.wait_for_service(timeout_sec=2.0): return False
        f = st_cli.call_async(SetBool.Request(data=on)); rclpy.spin_until_future_complete(node, f, timeout_sec=3.0)
        return f.done() and f.result() is not None and f.result().success
    rc = 0
    try:
        if not grip_state(True): print("     (그리퍼 상태 켜기 서비스 없음: 예전 노드면 늘 켜져 있음)", flush=True)
        check_robot()
        if a.home:
            # 재시도 흐름(pick_loop.py)용 정리. 실패 뒤 팔은 이미 위로 빠져 있음 -> 그 자리에서 열고, 위로 올린 뒤 시작 자세로. 아래로는 절대 안 감
            if grip() < GRIP_OPEN_OK:
                print(f"     그리퍼 엶 (지금 {grip():.0f})", flush=True); gripper_cmd(750, 200); gripper_wait(timeout=12.0); spin_for(1.0)
            cur = FKC.fk(fresh_q())[0]
            if cur[2] < START[2] and cur[0] > 600.0:   # 먼 곳은 z427 로 바로 못 올라감(특이점) -> 수집 때 길: z300 -> X520
                if cur[2] < 300.0: go([cur[0], cur[1], 300.0], 30.0, "정리상승")
                go([520.0, cur[1], max(cur[2], 300.0)], 30.0, "정리당기기"); cur = FKC.fk(fresh_q())[0]
            if cur[2] < START[2]: go([cur[0], cur[1], START[2]], 30.0, "정리상승")
            go(list(START), 40.0, "시작자세로")
            print("정리 끝: 시작 자세", flush=True); return 0
        if a.point:
            cur = FKC.fk(fresh_q())[0]
            if cur[2] < 300: go([cur[0], cur[1], 300.0], 20.0, "수직상승")
            go([a.point[0], a.point[1], 300.0], 50.0, "가리키기")
            go([a.point[0], a.point[1], 260.0], 20.0, "가리키기하강")   # 수집 때와 같은 높이(z260): 손끝이 가까워 놓기 쉬움
            print(f"x{a.point[0]:.0f} y{a.point[1]:.0f} 위 z260 에서 멈춤. 손가락 두 개 정가운데 바로 아래에 봉지 가운데를 놓으세요."); return 0
        if a.holding:
            g0 = grip()
            if not (GRIP_EMPTY < g0 < GRIP_OPEN_OK): raise Stop(f"--holding 인데 그리퍼 위치 {g0:.0f} (물고 있는 범위 아님)")
            print(f"물고 있음(위치 {g0:.0f}) -> 이 자리에서 정책 이어서 실행 (z300 까지는 수직 상승만)", flush=True)
        else:
            if grip() < GRIP_OPEN_OK: raise Stop("시작 시 그리퍼가 열려 있지 않음")
            cur = FKC.fk(fresh_q())[0]
            # 10-22: 앞 물건을 바구니에 놓은 자리(작업대를 안 가림)면 시작 자세로 돌아가지 않고 여기서 바로 찍고 집으러 감
            clear_view = bool(a.cam_start and cur[1] < -300.0 and cur[2] > 400.0)
            if clear_view:
                print(f"     팔이 작업대를 안 가리는 자리(x{cur[0]:.0f} y{cur[1]:.0f}) -> 시작 자세로 안 가고 여기서 바로 찍음", flush=True)
            else:
                if cur[2] < 300: go([cur[0], cur[1], 300.0], 40.0, "상승")
                go(list(START), 50.0, "시작자세")
            if a.start_offset[0] or a.start_offset[1]:
                so = [START[0] + a.start_offset[0], START[1] + a.start_offset[1], START[2]]
                print(f"시작 자세를 한 번 옮김 dx{a.start_offset[0]:+.0f} dy{a.start_offset[1]:+.0f} -> x{so[0]:.0f} y{so[1]:.0f} z{so[2]:.0f}", flush=True)
                go(so, 40.0, "시작보정")

        if a.ckpt is None and a.force_test is None:
            raise Stop(f"{a.object} 는 아직 학습 모델이 없음 (힘 시험 --force-test 나 --home 만 가능)")
        worker = None
        if a.force_test is None:
          print("모델 로드 중...", flush=True)
          wargs = [VENV_PY, str(HERE / "infer_worker.py"), "--zero-noise", "--task", a.task] + ([] if a.ckpt == "codex" else ["--ckpt", a.ckpt])
          print(f"모델: {a.ckpt}  {'(공중 시험: z%.0f 아래로 안 내려감, 닫지 않음)' % AIR_FLOOR if a.air else ''}", flush=True)
          if a.ckpt != "codex":
              # 10-21 속도: 상주 추론 서버(infer_server.py, 127.0.0.1:8766)가 떠 있으면 모델을 다시 올리지 않고 그걸 쓴다(주문마다 15초 절약)
              import socket
              try:
                  so = socket.create_connection(("127.0.0.1", 8766), timeout=2.0); so.settimeout(60.0)
                  fw = so.makefile("rw", buffering=1, encoding="utf-8")
                  class _W: pass
                  worker = _W(); worker.stdin = fw; worker.stdout = fw; worker.terminate = so.close
                  fw.write(json.dumps({"ckpt": a.ckpt, "task": a.task}) + "\n"); fw.flush()
                  print("     상주 추론 서버 사용", flush=True)
              except OSError:
                  worker = None
          if worker is None:
              worker = subprocess.Popen(wargs, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=(run / "worker.err").open("w"), text=True, bufsize=1)
          if not json.loads(worker.stdout.readline()).get("ready"): raise Stop("워커 시작 실패")
        cap = cv2.VideoCapture(CAMERA, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480); cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        for _ in range(25): cap.read()

        def verify_release():
            """놓은 뒤 1초 기다렸다가 위 카메라로 작업대를 본다. 물건이 작업대 위에 보이면 바구니에 안 들어간 것."""
            spin_for(1.0)
            for _ in range(4): cap.grab()
            okv, fv = cap.read()
            if not okv: return
            cv2.imwrite(str(run / "c99_after_release.jpg"), fv)
            xy = cam_locate(a.object, fv, occl=False)   # 팔이 바구니 위라 작업대를 안 가림
            if xy is not None and cam_xy is not None and float(np.hypot(*(np.asarray(xy) - np.asarray(cam_xy)))) > 60.0:
                # 10-23: 새우깡 2개 놓고 1개 주문 -> 집어 담은 뒤 '다른' 봉지를 보고 적재 실패로 판단해 두 번째 봉지까지 집으러 감.
                # 집은 자리(카메라로 처음 본 위치)에서 6cm 넘게 떨어진 같은 상품은 다른 재고로 본다
                print(f"     놓은 뒤 처음 집은 자리(x{cam_xy[0]:.0f} y{cam_xy[1]:.0f})는 비었음. x{xy[0]:.0f} y{xy[1]:.0f} 의 {a.object} 는 다른 재고 -> 적재 완료로 봄", flush=True)
                emit("loaded"); return
            if xy is not None:
                print(f"     !! 놓은 뒤 작업대 위 x{xy[0]:.0f} y{xy[1]:.0f} 에 {a.object} 가 보임 -> 적재 실패", flush=True)
                log({"not_in_basket": xy.tolist()}); emit("not_in_basket", xy=xy)
            else:
                print("     놓은 뒤 작업대 위에 물건 없음 -> 적재 완료로 봄", flush=True); emit("loaded")
        closed = bool(a.holding); cam_xy = None
        clear_view = locals().get("clear_view", False)
        if a.cam_start and not a.holding:
            for _ in range(4): cap.grab()
            ok0, f0 = cap.read()
            cam_xy = cam_locate(a.object, f0, occl=not clear_view) if ok0 else None
            if cam_xy is not None and ok0 and not clear_view and near_gripper(a.object, f0):
                # 10-22: 새우깡이 시작 자세 그리퍼에 반쯤 가려져 중심이 비켜 계산됨(빈손 1회) -> 그리퍼 근처에 걸치면 비켜 다시 찍는다
                print(f"     {a.object} 가 시작 자세 그리퍼 근처에 걸침 -> 팔을 비켜 다시 찍어 위치를 정함", flush=True); cam_xy = None
            if cam_xy is None and ok0:
                # 10-22: 시작 자세 그리퍼가 로봇 쪽 가운데 물건을 가림 -> 팔을 바구니 쪽 대기 자세로 비켜서 한 번 더 찍음
                cv2.imwrite(str(run / "c00_start_hidden.jpg"), f0)
                print(f"     시작 자세에서 {a.object} 안 보임 -> 팔을 비켜(x{LOOK[0]:.0f} y{LOOK[1]:.0f} z{LOOK[2]:.0f}) 다시 찍음", flush=True)
                cur0 = FKC.fk(fresh_q())[0]
                if cur0[1] < -300.0:
                    # 10-22 저녁: 비킨 자리를 작업대 오른쪽(y250)으로 옮긴 뒤 바구니 위(x350 y-500)에서 바로 가려다 경로 검사 특이점(0.020)에 걸림.
                    # 바구니 쪽이면 높이 유지한 채 시작 자세로 먼저 (시작 자세 -> 비킨 자리는 조작성 0.058)
                    go(list(START), 50.0, "바구니에서빠지기")
                    cur0 = FKC.fk(fresh_q())[0]
                if cur0[2] < LOOK[2] - 1.0: go([cur0[0], cur0[1], LOOK[2]], 40.0, "비켜보기상승")
                go(list(LOOK), 50.0, "비켜서보기"); spin_for(0.5)
                for _ in range(6): cap.grab()
                ok0, f0 = cap.read()
                cam_xy = cam_locate(a.object, f0, occl=False) if ok0 else None
            if cam_xy is None:
                # 2026-10-21: 작업대가 비어 있는데도 정책이 내려가 빈손으로 닫음 -> 카메라가 못 찾으면 출발하지 않는다
                if ok0: cv2.imwrite(str(run / "c00_notfound.jpg"), f0)   # 10-22 못 찾은 사진도 남김
                emit("not_found"); raise Stop(f"작업대에서 {a.object} 를 못 찾음 (작업대 위에 세워 놓았는지 확인)")
            else:
                cv2.imwrite(str(run / "c00_start.jpg"), f0); log({"cam_xy": cam_xy.tolist()}); emit("located", xy=cam_xy)
                hover = [float(cam_xy[0]), float(cam_xy[1]), AIR_FLOOR]
                print(f"     카메라로 본 {a.object} x{cam_xy[0]:.0f} y{cam_xy[1]:.0f} -> 그 위 z{AIR_FLOOR:.0f} 로 먼저 이동한 뒤 정책 시작", flush=True)
                # 수집 때 안전하다고 계산한 영역(random_area.json, 20mm 격자) 밖이면 집으러 가지 않는다
                grid = json.loads((HERE / "random_area.json").read_text())
                gx0, gy0 = math.floor(hover[0] / 20) * 20, math.floor(hover[1] / 20) * 20
                okg = all(grid.get(f"{gx},{gy}", -1) >= 0.02 for gx in (gx0, gx0 + 20) for gy in (gy0, gy0 + 20))
                if not okg:   # 10-22: 칸 4개 검사는 가장자리에서 너무 깐깐함(x660 y-48 은 한 칸만 막혀 거부, 실제 경로 여유 0.045). 실제 집기·운반 경로로 다시 판정
                    from random_area_check import route
                    okg = route(hover[0], hover[1]) >= 0.02
                # 10-22: 경로 검사는 통과했지만 작업영역(y<=200) 밖이라 봉지 위까지 간 뒤 잡기 직전에 멈춤(x541 y229, 봉지가 작업대 오른쪽 끝에 걸침) -> 출발 전에 같이 검사
                okg = okg and BOUNDS_X[0] <= hover[0] <= BOUNDS_X[1] and BOUNDS_Y[0] <= hover[1] <= BOUNDS_Y[1]
                if not okg:
                    raise Stop(f"상자 위치 x{hover[0]:.0f} y{hover[1]:.0f} 는 팔이 안전하게 집고 바구니까지 갈 수 없는 곳(수집 범위 밖). 작업대 안쪽으로 옮겨 주세요")
                if clear_view or FKC.fk(fresh_q())[0][1] < -300.0:
                    # 10-22 사고: 바구니 위에서 찍고 먼 물건(x669)으로 가려고 그 자리에서 z300 으로 내려가 손가락이 바구니 안에 들어가 바구니를 끌고 감(비상정지).
                    # 바구니 쪽이면 높이를 유지한 채 시작 자세로 먼저 빠져나온다
                    go(list(START), 50.0, "바구니에서빠지기")
                cur0 = FKC.fk(fresh_q())[0]
                tz = 300.0 if hover[0] > 600.0 else cur0[2]     # 먼 곳은 z427 에서 수평으로 못 감 -> z300 높이로 이동
                if cur0[2] > tz: go([cur0[0], cur0[1], tz], 40.0, "이동높이로")
                go([hover[0], hover[1], tz], 50.0, "상자위로"); go(hover, 50.0, "상자위하강")
                if a.cam_grasp and a.force_test is None:
                    # 2026-10-21 키오스크: 새우깡 정책이 z210 근처에서 60사이클 맴돌며 안 내려옴 -> 잡기는 카메라 위치에서 직접
                    # (힘 시험과 같은 방식, 3/3 물었음). 그다음은 쥔 상태(closed)로 정책 루프에 넘겨 들기·운반·놓기
                    gz = grasp_floor(hover[0], hover[1]); tgt = np.array([hover[0], hover[1], gz])
                    print(f"     카메라 위치 x{tgt[0]:.0f} y{tgt[1]:.0f} 에서 바로 잡기 (z{gz:.0f})", flush=True)
                    safe_target(tgt); go(tgt, V_MIN + 20.0, "카메라잡기하강")
                    pos = close_gripper(); closed = True
                    if False and a.object == "shrimp" and pos > 250.0:   # 10-23 오후 끔: 새(빵빵한) 봉지는 잘 잡아도 300~430 -> 잘 잡은 걸 열었다 다시 쥠(사용자). 빠짐은 아래 천천히 들기로만 판정
                        # 10-23: 봉지 볼록한 가운데에 막혀 350~423 에서 멈춘 걸 '다 닫힘'으로 보고 들어 올림 -> 올라가며 봉지가 빠지고 손가락이 그제야 끝까지 닫힘(2번).
                        # 같은 높이에서 한 번 열었다가 다시 쥔다 (아래로는 안 감)
                        print(f"     봉지 가운데에 막혀 덜 닫힘({pos:.0f}) -> 같은 자리에서 열었다가 다시 쥠", flush=True)
                        log({"regrip_from": pos}); gripper_cmd(750, 200); gripper_wait(timeout=12.0); spin_for(0.5)
                        pos = close_gripper()
                    print(f"     닫힘 위치 {pos:.0f}", flush=True); log({"close_at": tgt.tolist(), "closed_pos": pos, "cam_grasp": True})
                    if pos >= GRIP_OPEN_OK or (pos <= GRIP_EMPTY and a.object != "shrimp"):
                        emit("grasp_failed", xyz=tgt, closed_pos=pos)
                        go([tgt[0], tgt[1], max(tgt[2] + 150.0, 300.0)], 30.0, "빈손상승"); raise Stop("빈손으로 닫힘 -> 위로 빠지고 멈춤 (그리퍼 안 엶)")
                    if pos <= GRIP_EMPTY:   # 10-22: 납작한 봉지는 물고 있어도 11~20 -> 빈손 판정 안 하고 운반, 놓은 뒤 카메라로 확인
                        print(f"     새우깡 봉지가 얇아 그리퍼 값({pos:.0f})으로는 빈손인지 모름 -> 운반 후 카메라로 확인", flush=True)
                    emit("grasped", xyz=tgt, closed_pos=pos)
                    if a.object == "shrimp":
                        # 10-23: 처음 4cm 는 천천히 들고 그리퍼를 본다. 그사이 끝까지 닫혀 버렸으면 봉지가 빠진 것 -> 위로만 빠지고 다시 시도
                        g0 = grip(); go([tgt[0], tgt[1], tgt[2] + 40.0], 15.0, "천천히들기"); spin_for(0.6); g1 = grip()
                        print(f"     4cm 든 뒤 그리퍼 {g0:.0f} -> {g1:.0f}", flush=True); log({"slow_lift_grip": [g0, g1]})
                        if g0 > 150.0 and g1 <= GRIP_EMPTY + 15.0:
                            cur_s = FKC.fk(fresh_q())[0]
                            print("     !! 드는 사이 봉지가 빠지며 손가락이 끝까지 닫힘 -> 위로 빠지고 다시 시도", flush=True)
                            emit("grasp_failed", xyz=cur_s, closed_pos=g1)
                            go([cur_s[0], cur_s[1], 300.0 if cur_s[0] > 600.0 else max(cur_s[2] + 150.0, 300.0)], 30.0, "빠짐상승"); raise Stop("들어 올리는 중 봉지가 빠짐 -> 위로 빠지고 멈춤")
                if a.force_test is not None:
                    # 힘 측정 시험 (2026-10-21): 카메라 위치에서 수직으로 내려가 쥐고, 5cm 들어 3초 버틴 뒤 좌우 +-25mm 두 번 흔든다.
                    # 빠지거나 미끄러지면 위로만 빠지고 멈춤(다시 내려가지 않음, 그리퍼 안 엶). 버티면 제자리에 내려놓고 엶.
                    gz = grasp_floor(hover[0], hover[1]); hx, hy = hover[0], hover[1]
                    res = {"t": time.time(), "object": a.object, "current": a.force_test, "xy": [hx, hy], "grasp_z": gz, "trace": [], "verdict": None}
                    tgt = [hx, hy, gz]; safe_target(tgt); go(tgt, V_MIN + 20.0, "시험하강")
                    pos = close_gripper(); res["closed_pos"] = pos
                    print(f"     전류 {a.force_test:.0f} 로 닫음 -> 그리퍼 {pos:.0f}", flush=True)
                    def judge(tag, sec):
                        end = time.monotonic() + sec
                        while time.monotonic() < end:
                            g_ = grip(); res["trace"].append([tag, float(g_)])
                            if a.object == "shrimp": spin_for(0.3); continue   # 봉지는 그리퍼 값이 들쭉날쭉(쥔 값 26~429, 빈손 29) -> 사람 눈으로 판정
                            if g_ <= GRIP_EMPTY: return "dropped"
                            if pos - g_ > 60.0: return "slipped"
                            spin_for(0.3)
                        return None
                    if pos >= GRIP_OPEN_OK or (a.object != "shrimp" and pos <= GRIP_EMPTY):
                        res["verdict"] = "not_gripped"; emit("grasp_failed", xyz=tgt, closed_pos=pos)
                    else:
                        emit("grasped", xyz=tgt, closed_pos=pos)
                        up = gz + (150.0 if a.object == "shrimp" else 50.0)   # 봉지는 15cm (10-21 사용자: 5cm 는 바닥에서 거의 안 뜸)
                        for tag, p_, v_, hold in [("lift", [hx, hy, up], 20.0, 3.0), ("shake", [hx, hy + 25.0, up], 100.0, 1.0),
                                                  ("shake", [hx, hy - 25.0, up], 100.0, 1.0), ("shake", [hx, hy + 25.0, up], 100.0, 1.0),
                                                  ("shake", [hx, hy - 25.0, up], 100.0, 1.0), ("center", [hx, hy, up], 50.0, 1.5)]:
                            safe_target(p_); go(p_, v_, "시험" + tag)
                            res["verdict"] = judge(tag, hold)
                            if res["verdict"]: res["phase"] = tag; break
                        if res["verdict"] is None: res["verdict"] = "held"
                        if a.object == "shrimp" and res["verdict"] == "held":
                            # 그리퍼 값으로 빠졌는지 알 수 없으니 들고 있는 높이에서 멈춘다(빠졌는데 내려가 바닥을 누르지 않게). 사람이 보고 판정
                            res["verdict"] = "observe"
                            with (HERE / "twin" / "force_trials.jsonl").open("a") as f_: f_.write(json.dumps(res, ensure_ascii=False) + "\n")
                            print(f"     흔들기 끝, z{up:.0f} 에서 쥔 채 멈춤 (그리퍼 {pos:.0f} -> {res['trace'][-1][1]:.0f}). 봉지가 버텼는지 눈으로 확인", flush=True)
                            print(f"힘 시험 결과: 전류 {a.force_test:.0f} -> 사람 확인 필요", flush=True)
                            return 0
                    cur = FKC.fk(fresh_q())[0]
                    if res["verdict"] == "held":
                        print(f"     버팀 (전류 {a.force_test:.0f}, 그리퍼 {pos:.0f} -> 최저 {min(v for _, v in res['trace']):.0f}) -> 제자리에 내려놓고 엶", flush=True)
                        go([hx, hy, gz + 3.0], V_MIN + 15.0, "내려놓기"); gripper_cmd(750, 200); gripper_wait(timeout=12.0); spin_for(1.0)
                        go([hx, hy, AIR_FLOOR], 30.0, "엶뒤상승")
                    else:
                        if res["verdict"] == "dropped":
                            emit("dropped", xyz=cur, grip=res["trace"][-1][1])
                        print(f"     !! {res['verdict']} ({res.get('phase', 'close')}) -> 위로만 빠지고 멈춤 (그리퍼 안 엶)", flush=True)
                        go([cur[0], cur[1], max(cur[2] + 100.0, 300.0)], 30.0, "시험실패상승")
                    with (HERE / "twin" / "force_trials.jsonl").open("a") as f_: f_.write(json.dumps(res, ensure_ascii=False) + "\n")
                    print(f"힘 시험 결과: 전류 {a.force_test:.0f} -> {res['verdict']}", flush=True)
                    return 0
        lift_checked = False; stuck_floor = 0; demo_done = False
        for i in range(1, a.cycles + 1):
            check_robot()
            for _ in range(4): cap.grab()
            ok, frame = cap.read()
            if not ok: raise Stop("카메라 실패")
            img = run / f"c{i:02d}.jpg"; cv2.imwrite(str(img), frame)
            if closed and a.object == "shrimp" and cam_xy is not None and not lift_checked and FKC.fk(fresh_q())[0][2] >= 440.0:
                # 10-22: 납작해진 봉지는 손가락이 미끄러져 빈손으로 올라오는데 그리퍼 값(375~393)은 쥔 것과 같음 -> 바구니까지 헛걸음 3번.
                # 들어 올린 직후 사진에 봉지가 원래 자리(40mm 안)에 그대로 보이면 빈손 (지난 기록: 실패 1~22mm, 성공은 안 보임)
                lift_checked = True
                xy_l = cam_locate("shrimp", frame, occl=False)
                if xy_l is not None and float(np.hypot(*(xy_l - cam_xy))) < 40.0:
                    cur_l = FKC.fk(fresh_q())[0]
                    print(f"     !! 들어 올렸는데 봉지가 작업대 x{xy_l[0]:.0f} y{xy_l[1]:.0f} 에 그대로 있음 -> 빈손 (손가락이 미끄러짐)", flush=True)
                    log({"lift_empty": xy_l.tolist(), "cur": cur_l.tolist()})
                    emit("located", xy=xy_l); emit("grasp_failed", xyz=cur_l, closed_pos=float(grip()), xy=xy_l)
                    raise Stop("들어 올렸는데 봉지가 작업대에 그대로 있음 -> 빈손, 그 높이에서 멈춤 (다시 내려가지 않음)")
            if i == 1 and a.cam_assist and cam_xy is None:
                cam_xy = cam_locate(a.object, frame)
                print(f"     카메라로 본 {a.object} 위치: " + (f"x{cam_xy[0]:.0f} y{cam_xy[1]:.0f}" if cam_xy is not None else "못 찾음"), flush=True)
                if cam_xy is not None: emit("located", xy=cam_xy)
            if False:
                # 2026-10-20: 초코송이 120편 첫 사진으로 맞춘 픽셀->책상 2차식(안 본 24편 검증 오차 중앙값 17mm, 사람이 놓은 오차 포함)
                from choco_vision import find_box
                Wch = np.array(json.loads((HERE / "cam_choco_pix2xy.json").read_text())); br = find_box(frame)
                if br is not None:
                    px, py = br[0], br[1]; cam_xy = np.r_[px, py, px * py, px ** 2, py ** 2, 1.0] @ Wch
                    print(f"     카메라로 본 초코송이 위치: x{cam_xy[0]:.0f} y{cam_xy[1]:.0f} (픽셀 {px:.0f},{py:.0f})", flush=True); log({"choco_cam_xy": cam_xy.tolist()})
                else:
                    print("     카메라로 초코송이를 못 찾음 -> 닫기 위치는 정책(+보정)대로", flush=True)
            if i == 1 and a.object == "shrimp":   # 카메라로 본 봉지 위치(수집 56편으로 맞춘 픽셀->책상 좌표, 오차 중앙값 12mm)
                try:
                    from bag_vision import bag_region
                    Wc = np.array(json.loads((HERE / "cam_pix2xy.json").read_text())); br = bag_region(frame)
                    if br is not None:
                        bx, by = np.r_[br[2], 1.0] @ Wc
                        print(f"     카메라로 본 봉지 위치: x{bx:.0f} y{by:.0f}", flush=True); log({"bag_cam_xy": [bx, by]})
                except Exception as e: print("     (봉지 위치 추정 실패)", e)
            q = fresh_q(); g = grip(); gage = time.monotonic() - sh["g_t"]
            worker.stdin.write(json.dumps({"image": str(img), "state": list(q) + [g / 750.0, gage]}) + "\n"); worker.stdin.flush()
            ch = np.array(json.loads(worker.stdout.readline())["chunk"]); xyz = ch[:, :3] * 1000.0; gc = ch[:, 9]
            # 새우깡 봉지는 쥔 채로도 그리퍼 값이 42 아래로 자주 내려감(수집 성공 운반 중 1까지, 힘 시험 45~54) -> 그리퍼로 낙하 판정 안 함(놓은 뒤 카메라 확인만)
            if closed and g <= GRIP_EMPTY and a.object != "shrimp":
                # 2026-10-20: 옮기는 중 상자가 빠졌는데(285 -> 42) 빈손으로 계속 운반함. 쥔 뒤 빈손이 읽히면 그 자리에서 멈춤(내려가지 않음).
                log({"dropped_at": FKC.fk(q)[0].tolist(), "grip": g}); emit("dropped", xyz=FKC.fk(q)[0], grip=g)
                raise Stop(f"쥐고 있던 물건이 빠짐(그리퍼 위치 {g:.0f} <= {GRIP_EMPTY:.0f}) -> 그 자리에서 멈춤. 물건이 어디 떨어졌는지 확인")
            cur = FKC.fk(q)[0]
            if closed: rec["grip_trace"].append([round(time.time() - rec.get("t_grasp", time.time()), 2), float(g), float(cur[2])])
            log({"cycle": i, "cur": cur.tolist(), "chunk_xyz": xyz.tolist(), "chunk_grip": gc.tolist(), "grip": g, "closed": closed})
            # 공중 시험: 바닥 높이(z260)에 붙어 있는데 계획이 잡는 높이(z<170)까지 내려가려 하면, 그 최저점을 '정책이 잡으려는 곳'으로 보고 멈춤
            # (z 를 깎으니 정책이 닫기 높이에 못 가서 닫기 신호가 안 나옴. 2026-10-19 18:05 43사이클 맴돎)
            if a.air and cur[2] < AIR_FLOOR + 3 and xyz[:, 2].min() < 170.0:
                air_hits = locals().get("air_hits", 0) + 1
                if air_hits >= 3:
                    g_pt = xyz[int(np.argmin(xyz[:, 2]))]
                    print(f"[{i:2d}] 정책이 잡으려는 곳: x{g_pt[0]:.0f} y{g_pt[1]:.0f} z{g_pt[2]:.0f} -> 공중 시험 끝", flush=True)
                    log({"air_grasp_at": g_pt.tolist(), "cur": cur.tolist()}); return 0
            # 그리퍼 히스테리시스
            # 10-22: 초코송이 정책이 잡는 높이(z149)까지 와서 닫기를 안 내고 40번 넘게 맴돎 -> 3번 연속이면 카메라 위치에서 대신 닫음
            stuck_floor = stuck_floor + 1 if (not closed and a.cam_start and cam_xy is not None and not a.air
                                              and cur[2] < grasp_floor(cur[0], cur[1]) + 3.0) else 0
            if not closed and (gc[:K].min() < CLOSE_TH or stuck_floor >= 2):
                if gc[:K].min() < CLOSE_TH:
                    j = int(np.argmax(gc[:K] < 0.5)); tgt = xyz[j]
                else:
                    tgt = np.array(cur, float); print(f"[{i:2d}] 정책이 잡는 높이에서 닫지 않고 맴돎(3번) -> 카메라 위치에서 대신 닫음", flush=True)
                if a.air:
                    print(f"[{i:2d}] 정책이 여기서 닫으려 함: x{tgt[0]:.0f} y{tgt[1]:.0f} z{tgt[2]:.0f} (지금 x{cur[0]:.0f} y{cur[1]:.0f} z{cur[2]:.0f})"
                          " -> 공중 시험이라 닫지 않고 멈춤", flush=True)
                    log({"air_close_at": tgt.tolist(), "cur": cur.tolist()}); return 0
                print(f"[{i:2d}] 정책이 닫기 -> 닫기 지점 x{tgt[0]:.0f} y{tgt[1]:.0f} z{tgt[2]:.0f} 으로 이동 후 닫음", flush=True)
                # 수집 시연은 늘 '잡는 높이'(칸 높이 보간+5mm)까지 내려가서 닫았다. 정책 닫기 지점이 그보다 높으면
                # (18:25 z149 = 14mm 높음 -> 봉지 끝만 물고 들다가 빠짐) 그 높이까지 내려가서 닫는다. 그보다 낮게는 안 감.
                tgt = np.array(tgt, float)
                rec["policy_close_xy"] = [float(tgt[0]), float(tgt[1])]
                if a.cam_start and cam_xy is not None:
                    tgt[0], tgt[1] = float(cam_xy[0]), float(cam_xy[1])   # 10-22: 닫는 자리도 카메라 위치 (정책 지점은 원인 분석용으로만 기록)
                if cam_xy is not None:
                    dcam = float(np.hypot(*(cam_xy - tgt[:2])))
                    if dcam > 20.0:
                        print(f"     정책 닫기 지점 x{tgt[0]:.0f} y{tgt[1]:.0f} 과 카메라 위치가 {dcam:.0f}mm 다름 -> 카메라 위치 x{cam_xy[0]:.0f} y{cam_xy[1]:.0f} 에서 닫음"
                              " (상자 꼭대기 위로 올라가 옆으로 옮긴 뒤 수직 하강)", flush=True)
                        tgt[0], tgt[1] = cam_xy
                        hz = max(cur[2], grasp_floor(tgt[0], tgt[1]) + 65.0)
                        go([cur[0], cur[1], hz], 30.0, "보정전상승"); go([tgt[0], tgt[1], hz], 30.0, "보정이동")
                    else:
                        print(f"     정책 닫기 지점이 카메라 위치와 {dcam:.0f}mm 차이 -> 그대로", flush=True)
                    log({"cam_vs_policy_mm": dcam})
                far = tgt[0] > 600.0 and cam_xy is None
                if a.far_x_offset and far:
                    print(f"     먼 쪽(x{tgt[0]:.0f} > 600) 보정 dx{a.far_x_offset:+.0f}, 좌우 보정은 안 함(먼 쪽 y 오차는 +35/-30 으로 평균 0)", flush=True)
                    tgt[0] += a.far_x_offset
                    if True:
                        hz = max(cur[2], grasp_floor(tgt[0], tgt[1]) + 65.0)   # 손끝이 상자 꼭대기(8.5cm)를 2cm 넘는 높이만 (예전 z260)
                        go([cur[0], cur[1], hz], 30.0, "보정전상승"); go([tgt[0], tgt[1], hz], 30.0, "보정이동")
                if (a.close_offset[0] or a.close_offset[1]) and not (a.far_x_offset and far) and cam_xy is None:
                    # 2026-10-20: 매 사이클 보정은 정책이 현재 위치 기준으로 다시 계획해서 누적됨(y -264 까지 밀림). 닫기 지점에서 한 번만 옮긴다.
                    tgt[0] += a.close_offset[0]; tgt[1] += a.close_offset[1]
                    print(f"     닫기 지점 보정 dx{a.close_offset[0]:+.0f} dy{a.close_offset[1]:+.0f} -> x{tgt[0]:.0f} y{tgt[1]:.0f}"
                          " (z260 으로 올라가 옆으로 옮긴 뒤 수직 하강)", flush=True)
                    hz = max(cur[2], grasp_floor(tgt[0], tgt[1]) + 65.0)   # 손끝이 상자 꼭대기(8.5cm)를 2cm 넘는 높이만 (예전 z260)
                    go([cur[0], cur[1], hz], 30.0, "보정전상승"); go([tgt[0], tgt[1], hz], 30.0, "보정이동")
                tgt[2] = grasp_floor(tgt[0], tgt[1])
                print(f"     닫는 높이를 수집 때 잡는 높이 z{tgt[2]:.0f} 로 맞춤", flush=True)
                safe_target(tgt); go(tgt, V_MIN + 20.0, "닫기지점")
                pos = close_gripper(); closed = True
                print(f"     닫힘 위치 {pos:.0f} ({'물고 있음' if GRIP_EMPTY < pos < GRIP_OPEN_OK else '빈손 가능성'})", flush=True)
                log({"close_at": tgt.tolist(), "closed_pos": pos})
                if pos <= GRIP_EMPTY or pos >= GRIP_OPEN_OK:
                    emit("grasp_failed", xyz=tgt, closed_pos=pos)
                    go([tgt[0], tgt[1], max(tgt[2] + 150.0, 300.0)], 30.0, "빈손상승"); raise Stop("빈손으로 닫힘 -> 위로 빠지고 멈춤 (그리퍼 안 엶)")
                emit("grasped", xyz=tgt, closed_pos=pos)
                continue
            if closed and gc[:K].max() > OPEN_TH:
                if cur[1] <= RELEASE_ZONE["y_max"] and cur[2] >= RELEASE_ZONE["z_min"]:
                    print(f"[{i:2d}] 바구니 위(x{cur[0]:.0f} y{cur[1]:.0f} z{cur[2]:.0f})에서 정책이 열기 -> 엶", flush=True)
                    gripper_cmd(750, 200); gripper_wait(timeout=12.0); log({"release_at": cur.tolist()}); emit("released", xyz=cur); verify_release()
                    print("완료: 바구니 위에서 놓음", flush=True); return 0
                print(f"[{i:2d}] 정책이 열려 하지만 바구니 위가 아님 -> 무시 (열지 않고 계속)", flush=True)
            # 10-21 속도: 쥐고 운반 높이(z440 이상)에서는 계획을 2초 분량(20스텝)까지 실행 (멈춤-추론 반복 줄임)
            # 10-21: 운반 높이에선 VLA 계획 전체(약 5초 분량) 끝점까지 한 번에. 단 바구니 중심 150mm 안에선 1초 분량씩
            # (큰 걸음으로 바구니 앞 7cm 에 도착하면 새우깡 정책이 놓기를 안 내고 맴돎 2회. 짧은 걸음일 땐 스스로 중심까지 가서 놓았음)
            far_b = math.hypot(cur[0] - 350.0, cur[1] + 500.0) > 150.0
            KX = len(xyz) if (closed and cur[2] >= 440.0 and far_b) else K
            tgt = xyz[KX - 1].copy(); lift = False; descend = False
            # 수집 규칙과 같게: 쥔 뒤에는 z445(바구니 턱 위, 수집 운반 높이)까지 수직으로만 올라간다(낮은 높이 수평 이동 금지).
            # 2026-10-19 18:22 쥔 직후 정책이 z142~188 에서 옆으로 80mm 끌다가 봉지가 빠짐.
            demo_f = HERE / "demo_drop.json"   # 10-23 시나리오용: {"object": "choco"} 가 있으면 그 물건을 일부러 떨어뜨림(demo_drop.sh)
            # 켜 두면 끌 때까지 매 주문 첫 시도에서만 떨어뜨림(재시도는 정상으로 집음). pick_loop 가 첫 시도에 DEMO_FIRST=1 을 줌
            if (closed and cur[2] < 440.0 and os.environ.get("DEMO_FIRST") == "1" and not demo_done
                    and demo_f.exists() and json.loads(demo_f.read_text()).get("object") == a.object):
                demo_done = True
                up = [cur[0], cur[1], cur[2] + 100.0]
                print(f"[{i:2d}] (시연) 작업대 위 10cm 까지 들고 그리퍼를 열어 떨어뜨림", flush=True)
                go(up, 30.0, "시연들기"); g_ = grip(); cur_d = FKC.fk(fresh_q())[0]
                gripper_cmd(750, 200); gripper_wait(timeout=12.0); spin_for(1.0)
                log({"dropped_at": cur_d.tolist(), "grip": g_, "demo": True}); emit("dropped", xyz=cur_d, grip=g_)
                go([cur_d[0], cur_d[1], 445.0 if cur_d[0] <= 600.0 else 300.0], 30.0, "낙하뒤상승")   # 위로만
                raise Stop("(시연) 들어 올리는 중 물건이 빠짐 -> 위로 빠지고 다시 찾음")
            if closed and cur[0] > 600.0:
                # 먼 곳(X>600)은 z445 까지 못 올라감(2026-10-20 X620 z435 에서 특이점 0.014 로 멈춤).
                # 수집 때와 같은 길: z300 으로 맞춘 뒤 X520 으로 당겨 오고, 그다음 z445 로 올림.
                tgt = np.array([cur[0], cur[1], 300.0]) if abs(cur[2] - 300.0) > 5.0 else np.array([520.0, cur[1], 300.0])
                lift = True   # 10-23: 80mm 씩 끊지 않고 한 번에 (수집 때 길 그대로)
                print(f"     먼 곳이라 수집 때 경로로: z300 -> X520 -> z445 (지금 목표 x{tgt[0]:.0f} z{tgt[2]:.0f})", flush=True)
            elif closed and cur[2] < 440.0:
                # 10-21 속도: 쥔 뒤 z445 까지 수직 상승은 규칙이라 8사이클로 나누지 않고 한 번에 (정책은 이 구간에서 위로 올리기만 했음)
                tgt = np.array([cur[0], cur[1], 445.0]); lift = True
            elif closed:
                tgt[2] = max(tgt[2], 440.0)   # 쥔 채로는 다시 z440 아래로 안 내려감 (봉지가 바닥/바구니 턱에 닿지 않게)
            if closed and cur[2] >= 440.0 and not far_b and math.hypot(cur[0] - 350.0, cur[1] + 500.0) > 15.0:
                # 10-23: 바구니 150mm 안에서 1초 분량(10~24mm)씩 찔끔 다가가던 것 -> 수집 때 놓던 바구니 중심으로 한 번에. 놓는 시점은 계속 정책이 정함
                tgt = np.array([350.0, -500.0, 445.0])
            if closed and cur[2] >= 440.0:
                # 쥔 채 운반 높이는 수집과 같은 z445 로 고정(정책이 z450~458 을 내면 바구니 쪽에서 팔이 다 펴져 특이점에 걸림, 10-20 3회)
                tgt[2] = 445.0
            if not closed and cam_xy is not None and a.cam_start:
                tgt[0], tgt[1] = float(cam_xy[0]), float(cam_xy[1])   # 10-22: 카메라가 위치를 아니 좌우는 고정, 수직으로만 내려감
                # 10-23 사용자 "찔끔찔끔 보기 싫어": 1초 분량(24~38mm)씩 끊어 내려가던 것을, 정책 계획 전체(약 5초) 중 가장 낮은 지점까지 한 번에
                tgt[2] = float(xyz[:, 2].min()); descend = True
            if not closed and cur[2] < grasp_floor(cur[0], cur[1]) + 60.0:
                # 손가락이 물건 높이까지 내려온 뒤에는 옆으로 크게 쓸지 않는다(10-21 z147 에서 y 를 16cm 쓸고 다님 -> 물건·주변을 칠 수 있음).
                # 수평은 한 번에 10mm 까지만. 위치는 닫을 때 카메라로 맞춘다.
                dxy = tgt[:2] - cur[:2]; dn = float(np.linalg.norm(dxy))
                if dn > 10.0: tgt[:2] = cur[:2] + dxy / dn * 10.0
            if closed and tgt[1] < -500.0:
                # 바구니(X350·Y-500) 너머는 z445 에서 팔이 안 닿음(2026-10-20 Y-519 도달 불가로 멈춤). 수집 때 놓던 Y-500 까지만.
                tgt[1] = -500.0
            step = tgt - cur; d = float(np.linalg.norm(step))
            mstep = 400.0 if (lift or descend) else (400.0 if (closed and cur[2] >= 440.0) else MAX_STEP_MM)
            if d > mstep: tgt = cur + step / d * mstep; d = mstep
            # 10-21 키오스크: 새우깡을 쥐고 바구니 위(x380 y-440)까지 와서 정책이 '놓기'를 안 내고 1cm 씩 57사이클 맴돎 -> 시간 초과.
            # 쥔 채 바구니 위 범위에서 4사이클 연속 20mm 미만으로 맴돌면 바구니 중심(수집 때 놓던 곳)으로 가서 놓는다(정책이 놓으면 그게 먼저).
            near_b = math.hypot(cur[0] - 350.0, cur[1] + 500.0)
            stall = (locals().get("stall", 0) + 1) if (closed and cur[1] <= RELEASE_ZONE["y_max"] and cur[2] >= RELEASE_ZONE["z_min"] and d < 20.0) else 0
            if stall >= (2 if near_b <= 15.0 else 4) and near_b <= 120.0:
                print(f"[{i:2d}] 바구니 위(중심에서 {near_b:.0f}mm)에서 정책이 놓지 않고 맴돎 -> 바구니 중심으로 가서 놓음", flush=True)
                try: go([350.0, -500.0, 445.0], 30.0, "바구니중심으로")
                except Stop as e3: print(f"     바구니 중심으로 못 감({e3}) -> 이 자리에서 놓음", flush=True)
                cur = FKC.fk(fresh_q())[0]
                gripper_cmd(750, 200); gripper_wait(timeout=12.0); log({"release_stall_at": cur.tolist()}); emit("released", xyz=cur); verify_release()
                print("완료: 바구니 위에서 놓음 (정책이 맴돌아 대신 놓음)", flush=True); return 0
            safe_target(tgt)
            v = float(np.clip(d / (KX * 0.1), V_MIN, V_MAX)) if not lift else 60.0
            if descend: v = float(np.clip(d / 2.0, 20.0, 40.0))   # 10-23: 한 번에 내려가되 물건 위 접근은 40mm/s 이하
            if closed and cur[2] >= 440.0: v = float(np.clip(d / (KX * 0.1), 30.0, 60.0))   # 10-22: 100 -> 60 (컵라면이 운반 중 빠짐). 큰 걸음은 유지
            print(f"[{i:2d}] x{cur[0]:5.0f} y{cur[1]:5.0f} z{cur[2]:5.0f} -> x{tgt[0]:5.0f} y{tgt[1]:5.0f} z{tgt[2]:5.0f}"
                  f"  ({d:4.1f}mm, 그리퍼계획 {gc[:K].min():.2f}~{gc[:K].max():.2f}, {'쥠' if closed else '열림'})", flush=True)
            try:
                go(tgt, v, "정책")
            except Stop as e:
                # 바구니 근처는 팔이 거의 다 펴지는 곳이라(조작성 0.01~0.02) 정책의 작은 이동도 사전검사에 걸린다(2026-10-20 2회).
                # 쥔 채로 바구니 중심(X350·Y-500)에서 6cm 안, z380 이상이면 거기서 놓는다(수집 때 놓던 곳과 같은 바구니 안).
                near = math.hypot(cur[0] - 350.0, cur[1] + 500.0)
                # 10-22: 운반 중간(x450 y-312)에서도 막힘(특이점 0.009, 컵라면 먼 쪽) -> 운반 높이면 어디서든 바구니로 직접(수집 때 길)
                if closed and cur[2] >= 440.0 and near > 30.0 and "경로 사전검사" in str(e):
                    # 바구니 바로 앞에서 막히면 수집 때 놓던 자리(X350·Y-500·Z445)로 직접 가 본다
                    print(f"[{i:2d}] 바구니 앞에서 막힘({e}) -> 수집 때 놓던 자리 X350 Y-500 Z445 로 직접 이동", flush=True)
                    try:
                        go([350.0, -500.0, 445.0], 30.0, "바구니로직접"); cur = FKC.fk(fresh_q())[0]; near = math.hypot(cur[0] - 350.0, cur[1] + 500.0)
                    except Stop as e2:
                        print(f"     직접 이동도 막힘: {e2}", flush=True)
                if closed and near <= 80.0 and cur[2] >= RELEASE_ZONE["z_min"] and "경로 사전검사" in str(e):
                    print(f"[{i:2d}] 바구니 근처({near:.0f}mm)에서 더 못 감({e}) -> 이 자리에서 놓음", flush=True)
                    gripper_cmd(750, 200); gripper_wait(timeout=12.0); log({"release_fallback_at": cur.tolist(), "why": str(e)}); emit("released", xyz=cur); verify_release()
                    print("완료: 바구니 위에서 놓음 (정책 열기 신호 전, 바구니 안 대체 놓기)", flush=True); return 0
                raise
        cur = FKC.fk(fresh_q())[0]
        if closed and cur[1] <= RELEASE_ZONE["y_max"] and cur[2] >= RELEASE_ZONE["z_min"] and math.hypot(cur[0] - 350.0, cur[1] + 500.0) <= 120.0:
            # 쥔 채 바구니 위에서 시간이 다 됨 -> 실패로 두지 않고 여기서 놓고 카메라로 확인 (10-21: 정리 동작이 바구니 위에서 열어 담겼는데 실패로 기록됨)
            print("최대 사이클 도달, 쥔 채 바구니 위 -> 여기서 놓음", flush=True)
            gripper_cmd(750, 200); gripper_wait(timeout=12.0); log({"release_timeout_at": cur.tolist()}); emit("released", xyz=cur); verify_release()
            return 0
        print("최대 사이클 도달 -> 그 자리에서 멈춤", flush=True)
        emit("timeout", xyz=cur)   # 재시도 흐름이 실패로 알 수 있게 (10-21 새우깡 60사이클 맴돎)
    except Stop as e:
        print(f"\n!!! 멈춤: {e}", flush=True); rc = 2   # pick_loop.py 가 정리 실패를 알 수 있게
    finally:
        try: cap.release()
        except Exception: pass
        try: worker.stdin.close(); worker.terminate()
        except Exception: pass
        try: grip_state(False)
        except Exception: pass
        print(f"기록: {run}"); lf.close(); rclpy.shutdown()
    return rc


if __name__ == "__main__":
    sys.exit(main())
