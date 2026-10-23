#!/usr/bin/env python3
"""칸별 잡는 높이 확인. 새우깡 없이, 그리퍼를 연 채 칸마다 천천히 내려갔다 올라온다.
바닥에서 멈춰 사람에게 손끝-책상 간격을 묻고 기록한다 (height_check_result.json).
    python3 height_check.py --cells 8 5 2 6 --margin 5"""
import argparse, json, math, sys, time
from pathlib import Path
import numpy as np, rclpy
from sensor_msgs.msg import JointState
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fk import Chain, zyz_to_matrix
from path_check import ik as _ik, jac as _jac

ORI = [0.0, 180.0, 0.0]; CLEAR = (450.0, 0.0, 450.0); HOVER_Z = 300.0
DEV_MAX, MANIP_MIN = 15.0, 0.020
CELLS = {int(k): v for k, v in json.loads((HERE / "shrimp_cells.json").read_text()).items()}

class Stop(Exception): pass

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--cells", type=int, nargs="+", default=[8, 5, 2, 6])
    ap.add_argument("--margin", type=float, default=5.0); a = ap.parse_args()
    import DR_init
    DR_init.__dsr__id, DR_init.__dsr__model = "dsr01", "e0509"
    rclpy.init(); node = rclpy.create_node("height_check", namespace="dsr01"); DR_init.__dsr__node = node
    from DSR_ROBOT2 import amovel, posx, DR_BASE
    from dsr_msgs2.srv import GetRobotMode, GetRobotState, MoveStop
    sh = {}
    def on_js(m):
        d = dict(zip(m.name, m.position))
        if "joint_1" in d:
            sh["q"] = [d[f"joint_{i}"] for i in range(1, 7)]; sh["q_t"] = time.monotonic()
            dv = dict(zip(m.name, m.velocity)) if len(m.velocity) == len(m.name) else {}
            sh["qd"] = [dv.get(f"joint_{i}", 0.0) for i in range(1, 7)]
    def on_g(m): sh["g"] = m.position[0]; sh["g_t"] = time.monotonic()
    node.create_subscription(JointState, "/dsr01/joint_states", on_js, 10)
    node.create_subscription(JointState, "/dsr01/gripper/state", on_g, 10)
    stop_cli = node.create_client(MoveStop, "/dsr01/dsr_controller2/motion/move_stop")
    FKC, FK3 = Chain(), Chain(tip="link_3"); R = zyz_to_matrix(*ORI)
    def stop_now():
        stop_cli.wait_for_service(timeout_sec=1.0)
        f = stop_cli.call_async(MoveStop.Request(stop_mode=1)); rclpy.spin_until_future_complete(node, f, timeout_sec=2.0)
    def fresh_q():
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.01)
            if "q_t" in sh and time.monotonic() - sh["q_t"] < 0.3: return np.array(sh["q"])
        raise Stop("관절 상태 없음")
    def check_robot():
        for srv, name, attr in ((GetRobotMode, "get_robot_mode", "robot_mode"), (GetRobotState, "get_robot_state", "robot_state")):
            c = node.create_client(srv, f"/dsr01/dsr_controller2/system/{name}"); c.wait_for_service(timeout_sec=3.0)
            f = c.call_async(srv.Request()); rclpy.spin_until_future_complete(node, f, timeout_sec=5.0)
            if getattr(f.result(), attr, None) != 1: raise Stop(f"{name}={getattr(f.result(), attr, None)}")
    def go(p, v, name):
        target = np.array(p, float); q0 = fresh_q(); p0 = FKC.fk(q0)[0]
        if np.linalg.norm(target - p0) < 0.5: return
        q = q0.copy(); worst = 9.0
        for t in np.linspace(0, 1, 8):
            q, err = _ik(q, p0 + (target - p0) * t, R, it=40)
            if err > 2: raise Stop(f"{name}: 도달 불가")
            J = _jac(q); worst = min(worst, math.sqrt(max(np.linalg.det(J @ J.T), 0)))
            if FK3.fk(q)[0][0] < -60 or np.degrees(q)[2] > 125: raise Stop(f"{name}: 위험 자세")
        if worst < MANIP_MIN: raise Stop(f"{name}: 특이점 근접 {worst:.3f}")
        seg = target - p0; L = float(np.linalg.norm(seg)); t0 = time.monotonic()
        amovel(posx(list(target) + ORI), vel=[v, 20.0], acc=[2 * v, 40.0], ref=DR_BASE)
        while True:
            pf = FKC.fk(fresh_q())[0]
            s_ = float(np.clip(np.dot(pf - p0, seg) / (L * L), 0, 1)); dev = float(np.linalg.norm(pf - (p0 + s_ * seg)))
            if dev > DEV_MAX: stop_now(); raise Stop(f"{name}: 경로 이탈 {dev:.0f}mm -> 정지")
            if np.linalg.norm(pf - target) < 1.0 and max(abs(x) for x in sh.get("qd", [0] * 6)) < 0.005: break
            if time.monotonic() - t0 > L / v * 1.6 + 5: stop_now(); raise Stop(f"{name}: 시간 초과")
        return worst
    out = {}
    try:
        check_robot()
        cur = FKC.fk(fresh_q())[0]
        print(f"현재 x{cur[0]:.0f} y{cur[1]:.0f} z{cur[2]:.0f}", flush=True)
        if cur[0] > 600 and cur[2] < CLEAR[2] - 1:   # 먼 칸(x>600)은 z450 까지 못 올라감 -> z300 에서 안쪽(x520)으로 먼저 (collect.py 와 같은 길)
            if cur[2] < 299: go([cur[0], cur[1], 300.0], 30.0, "수직상승300")
            go([520.0, cur[1], 300.0], 30.0, "안쪽으로"); cur = FKC.fk(fresh_q())[0]
        if cur[2] < CLEAR[2] - 1: go([cur[0], cur[1], CLEAR[2]], 30.0, "수직상승")
        go(list(CLEAR), 50.0, "작업대가운데로")            # 바구니에서 먼저 벗어남 (높이 유지)
        for c in a.cells:
            x, y, zc = CELLS[c]; z = zc + a.margin
            print(f"\n[{c}번 칸] x{x:.0f} y{y:.0f} 위 z{HOVER_Z:.0f} 로 이동", flush=True)
            check_robot(); go([x, y, HOVER_Z], 50.0, "칸위로")
            rclpy.spin_once(node, timeout_sec=0.5)
            g = sh.get("g"); gage = time.monotonic() - sh.get("g_t", 0)
            if g is None or gage > 5 or g < 700: raise Stop(f"그리퍼가 열려 있다고 확인 안 됨(위치 {g}, {gage:.1f}s 전) -> 안 내려감")
            print(f"  그리퍼 열림({g:.0f}) 확인 -> 초당 10mm로 z{z:.1f} 까지 하강", flush=True)
            m = go([x, y, z], 10.0, "하강")
            ans = input(f"  [{c}번] z{z:.1f} 도착. 손끝과 책상 간격 대략 몇 mm? (Enter=괜찮음, 숫자=mm, q=끝): ").strip()
            out[c] = {"xy": [x, y], "z": z, "cell_z": zc, "answer": ans, "min_manip": m}
            go([x, y, HOVER_Z], 20.0, "상승")
            if ans.lower() == "q": break
        go(list(CLEAR), 50.0, "작업대가운데로")
        print("\n끝. 작업대 가운데 (450, 0, 450) 에서 멈춤", flush=True)
    except Stop as e:
        print(f"\n!!! 멈춤: {e}", flush=True)
    finally:
        (HERE / "height_check_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
        print("기록:", HERE / "height_check_result.json", out); rclpy.shutdown()

if __name__ == "__main__":
    main()
