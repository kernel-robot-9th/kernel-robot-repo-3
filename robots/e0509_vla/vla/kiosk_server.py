#!/usr/bin/env python3
"""담고 키오스크 주문 서버 (2026-10-21).
화면(vla_test/kiosk/)을 보여 주고, 주문이 오면 pick_loop.py 를 상품별로 하나씩 돌린다. 진행 상황은 /dsr01/pick/event 를 듣고 화면에 넘긴다.
- 이 PC 안에서만 받는다(127.0.0.1). 한 번에 주문 하나.
- 취소는 '다음 상품부터' 안 함. 지금 움직이는 동작은 멈추지 않는다(비상정지는 하드웨어 버튼).
- 학습이 끝난 상품만 ENABLED 에 넣는다.

  python3 vla_test/kiosk_server.py      ->  브라우저에서 http://localhost:8765
"""
import json, subprocess, sys, threading, time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import rclpy
from std_msgs.msg import String

HERE = Path(__file__).resolve().parent
WEB = HERE / "kiosk"; LOGS = WEB / "logs"; LOGS.mkdir(exist_ok=True)
ENABLED = ["shrimp", "choco", "ramen", "drink"]   # 10-26 오후: 게토레이 다시 염 (1번 칸에 세워 두고 마지막에 밀어 눕혀 집기)  # 10-26 게토레이(drink): gd_pick.py (카메라+깊이로 무게 중심 맞춰 잡기)          # 학습·실기 확인 끝난 상품만 (게토레이 drink, 컵라면 ramen 은 학습 뒤 추가)
NAMES = {"shrimp": "새우깡", "choco": "초코송이", "drink": "게토레이", "ramen": "컵라면"}
MAX_UNITS = 6
lock = threading.Lock(); order = None; seq = 0
SYNC_S = 4.0   # 10-22: 로봇이 쉬는 동안 이 주기로 카메라로 작업대를 보고 트윈에 물건 위치를 보냄
joint = {}

def camera_busy():
    """주문 중이거나 다른 프로그램(실행·수집)이 카메라를 쓰는 중이면 True"""
    with lock:
        if order and order["state"] == "running": return True
    r = subprocess.run(["pgrep", "-f", "vla_test/(vla_run|collect|pick_loop|gd_pick|gd_tip|gd_grasp_test|gd_tilt_regrasp|cam_align|layout_check)\\.py"], capture_output=True)
    return r.returncode == 0

def sync_loop(pub):
    import cv2, numpy as np
    sys.argv = [sys.argv[0]]
    import vla_run as V
    from fk import Chain
    fkc = Chain()
    while True:
        time.sleep(SYNC_S)
        try:
            if camera_busy() or "q" not in joint: continue
            tcp = fkc.fk(np.array(joint["q"]))[0]
            occl = float(np.linalg.norm(tcp - np.array(V.START))) < 60.0   # 팔이 시작 자세면 그리퍼 자리를 가림
            cap = cv2.VideoCapture(V.CAMERA, cv2.CAP_V4L2); cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            for _ in range(25): cap.read()   # 8 장이면 색 보정 전 사진이라 아무것도 못 찾음 (10-22)
            ok, f = cap.read(); cap.release()
            if not ok: continue
            seen, allp = {}, {}
            yaw = {}; stand = {}
            for o in ENABLED:
                if o == "drink":   # 10-26: 게토레이는 뚜껑 + 빈 작업대 비교로 가운데·누운 방향
                    from gatorade_vision import locate_bottle
                    from gatorade_vision import find_bottle
                    rr = find_bottle(f)
                    if rr is not None and rr["cap_area"] >= 260:   # 10-26: 서 있음 -> 카메라 자세로 높이 315mm 뚜껑의 바닥 자리
                        import json as _j, numpy as _np
                        P_ = _j.loads((HERE / "cam_pose.json").read_text()); K_ = _np.array(P_["K"]); D_ = _np.array(P_["dist"]); R_, _ = cv2.Rodrigues(_np.array(P_["rvec"])); C_ = -R_.T @ _np.array(P_["tvec"])
                        u_ = cv2.undistortPoints(_np.array([[rr["cap_px"]]], _np.float64), K_, D_).ravel(); d_ = R_.T @ _np.array([u_[0], u_[1], 1.0]); xy_ = (C_ + (315.0 - C_[2]) / d_[2] * d_)[:2]
                        seen[o] = [round(float(xy_[0]), 1), round(float(xy_[1]), 1)]; allp[o] = [seen[o]]; stand[o] = seen[o]; continue
                    b = locate_bottle(f)
                    seen[o] = None if b is None else [round(b["center"][0], 1), round(b["center"][1], 1)]
                    allp[o] = [] if b is None else [seen[o]]
                    if b is not None: yaw[o] = round(b["yaw_deg"], 1)
                    continue
                xy = V.cam_locate(o, f, occl=occl)
                seen[o] = None if xy is None else [round(float(xy[0]), 1), round(float(xy[1]), 1)]
                allp[o] = [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in V.cam_locate_all(o, f, occl=occl)]   # 10-23: 같은 상품 여러 개
            m = String(); m.data = json.dumps({"event": "seen", "objects": seen, "all": allp, "yaw": yaw, "stand": stand, "t": time.time()}); pub.publish(m)
        except Exception as e:
            print("동기화 오류:", repr(e), flush=True)


def on_event(msg):
    global order
    try: e = json.loads(msg.data)
    except Exception: return
    with lock:
        o = order
        if not o or o["state"] != "running" or e.get("object") != o["units"][o["index"]]: return
        k = e.get("event"); nm = NAMES.get(e.get("object"), "")
        if k == "retry":
            o["phase"] = 0; o["title"] = None
            o["message"] = f"다시 시도하고 있어요 ({e.get('attempt')}/{e.get('tries')})" if e.get("attempt", 1) > 1 else f"{nm} 위치를 찾고 있어요"
        elif k == "waiting": o["message"] = "상품을 다시 찾고 있어요"
        elif k == "located": o["phase"] = 0; o["message"] = f"{nm}를 찾았어요"
        elif k == "grasped": o["phase"] = 1; o["message"] = f"{nm}를 잡았어요"
        elif k == "released": o["phase"] = 2; o["message"] = "바구니에 내려놓았어요"
        elif k == "loaded": o["message"] = "담긴 것까지 확인했어요"
        elif k == "grasp_failed": o["message"] = "잡지 못했어요. 다시 해 볼게요"
        elif k == "dropped": o["message"] = "옮기다 떨어뜨렸어요. 다시 해 볼게요"
        elif k == "not_in_basket": o["message"] = "바구니에 안 들어갔어요. 다시 해 볼게요"
        elif k == "timeout": o["message"] = "잡지 못하고 헤맸어요. 다시 해 볼게요"
        elif k == "not_found": o["fail_reason"] = f"작업대에서 {nm}를 찾지 못했어요"
        elif k == "tipping": o["message"] = f"서 있는 {nm}를 눕히고 있어요"   # 10-26 gd_tip.py
        elif k == "tilt_warn":   # 10-26 게토레이: 운반 중 병이 손가락에서 돌기 시작
            dg = e.get("deg", -999); o["message"] = f"{nm}가 기울어져 멈췄어요" + (f" (약 {dg:.0f}도)" if dg > -900 else "")
        elif k == "analysis" and e.get("ko"): o["last_cause"] = e["ko"][0]
        elif k == "done": o["unit_ok"] = True
        elif k == "gave_up": o["unit_ok"] = False; o["fail_reason"] = "여러 번 시도했지만 담지 못했어요"
        elif k == "loop_end":
            o["unit_ok"] = False; r = e.get("reason", "")
            if "응답 느림" in r: o["fail_reason"] = "로봇 통신이 느려져 멈췄어요 (그리퍼 노드 재시작 필요)"
            elif "수집 범위 밖" in r: o["fail_reason"] = f"{nm}가 로봇이 닿기 어려운 곳에 있어요. 작업대 가운데로 옮겨 주세요"
            elif "AUTONOMOUS" in r or "STANDBY" in r: o["fail_reason"] = "로봇이 대기 상태가 아니에요 (서보·모드 확인)"
            else: o.setdefault("fail_reason", f"로봇이 안전을 위해 멈췄어요: {r}" if r else "로봇이 안전을 위해 멈췄어요")

def layout(units):
    """10-26: layout_check.py (카메라 한 장으로 배치 검사·다음 상품). 실패하면 None -> 예전 순서(게토레이 마지막)"""
    try:
        r = subprocess.run([sys.executable, "-u", str(HERE / "layout_check.py")] + list(units), capture_output=True, text=True, timeout=90)
        for line in r.stdout.splitlines()[::-1]:
            if line.startswith("LAYOUT_JSON "): return json.loads(line[12:]), r.stderr[-1500:]
        return None, r.stderr[-1500:]
    except Exception as ex:
        return None, str(ex)

def worker(o):
    global order
    with lock: o["message"] = "작업대 배치를 확인하고 있어요"
    done, need = [], list(o["units"])
    while need:
        with lock:
            if o["cancel"]: o["state"] = "cancelled"; o["message"] = "요청대로 남은 상품은 담지 않았어요"; return
        # 10-26: 서 있는 게토레이가 팔 몸체에 걸려 충돌 + 놓는 칸 때문에 중간에 멈춤 -> 상품마다 카메라로 배치를 보고 지금 안전한 상품을 고름.
        # 처음 검사에서 끝까지 막히는 상품이 있으면 로봇이 움직이기 전에 알려 줌
        # 10-26 18:30: 앞 실패 뒤 팔이 병 바로 위(z260)에 남아 사진을 가림 -> 게토레이를 못 찾음. 작업대 위 낮은 곳이면 먼저 시작 자세로 (위로 먼저 올림)
        try:
            from fk import Chain
            p_ = Chain().fk(joint["q"])[0] if "q" in joint else None
            if p_ is not None and 285 <= p_[0] <= 720 and -235 <= p_[1] <= 235 and p_[2] < 400:
                with lock: o["message"] = "팔을 시작 자세로 옮기고 있어요"
                with (LOGS / f"{o[id]}.log").open("a") as lf:
                    subprocess.run([sys.executable, "-u", str(HERE / "vla_run.py"), "--home"], stdout=lf, stderr=subprocess.STDOUT, timeout=180)
        except Exception as ex: print("시작 자세로 옮기기 실패", ex, flush=True)
        lay, err = layout(need)
        with (LOGS / f"{o['id']}.log").open("a") as lf: lf.write(f"[배치 검사] {json.dumps(lay, ensure_ascii=False)}\n{err}\n")
        if lay is not None and lay.get("problems"):
            with lock:
                o["state"] = "failed"; o["message"] = ("담기 전에 확인해 주세요: " if not done else "") + " / ".join(lay["problems"])
            return
        u = lay["next"] if lay is not None and lay.get("next") in need else ([x for x in need if x != "drink"] + [x for x in need if x == "drink"])[0]
        need.remove(u); i = len(done)
        with lock:
            o["units"] = done + [u] + need; o["index"] = i; o["phase"] = 0; o["unit_ok"] = None; o.pop("fail_reason", None); o.pop("last_cause", None)
            o["message"] = f"{NAMES[u]} 담기를 시작해요"
        with (LOGS / f"{o['id']}.log").open("a") as lf:
            cmd = [sys.executable, "-u", str(HERE / "gd_pick.py")] if u == "drink" else [sys.executable, "-u", str(HERE / "pick_loop.py"), "--object", u]
            r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT)
        time.sleep(1.0)   # 마지막 이벤트가 도착할 시간
        with lock:
            if o.get("unit_ok"):
                done.append(u); o["done_units"] = len(done); continue
            why = o.get("fail_reason") or "로봇이 멈췄어요"
            cause = f" ({o['last_cause']})" if o.get("last_cause") else ""
            o["state"] = "failed"; o["message"] = f"{why}{cause}. 직원을 불러 주세요"
            return
    with lock:
        o["state"] = "done"; o["phase"] = 2; o["message"] = f"{len(o['units'])}개 모두 담았어요"

class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=str(WEB), **k)
    def log_message(self, *a): pass
    def send_json(self, code, d):
        b = json.dumps(d, ensure_ascii=False).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(b)
    def view(self):
        with lock:
            return None if order is None else {k: v for k, v in order.items() if k in ("id", "units", "index", "phase", "state", "message", "done_units", "cancel", "title")}
    def do_GET(self):
        if self.path.startswith("/api/status"): return self.send_json(200, {"enabled": ENABLED, "order": self.view()})
        if self.path.startswith("/logs"): return self.send_error(404)
        return super().do_GET()
    def do_POST(self):
        global order, seq
        n = int(self.headers.get("Content-Length", 0) or 0)
        try: body = json.loads(self.rfile.read(n) or b"{}")
        except Exception: return self.send_json(400, {"error": "잘못된 요청"})
        if self.path == "/api/order":
            units = body.get("units") or []
            if not units or len(units) > MAX_UNITS: return self.send_json(400, {"error": f"상품은 1~{MAX_UNITS}개"})
            bad = [u for u in units if u not in ENABLED]
            if bad: return self.send_json(400, {"error": f"아직 담을 수 없는 상품: {', '.join(NAMES.get(u, u) for u in bad)}"})
            with lock:
                if order and order["state"] == "running": return self.send_json(409, {"error": "이미 다른 주문을 담는 중이에요"})
                seq += 1
                order = {"id": time.strftime("K%m%d-") + f"{seq:02d}", "units": units, "index": 0, "phase": 0, "state": "running",
                         "message": "주문을 받았어요", "done_units": 0, "cancel": False, "title": None}
                o = order
            print(f"[{time.strftime('%H:%M:%S')}] 주문 {o['id']}: {units}", flush=True)
            threading.Thread(target=worker, args=(o,), daemon=True).start()
            return self.send_json(200, self.view())
        if self.path == "/api/cancel":
            with lock:
                if order and order["state"] == "running": order["cancel"] = True
            return self.send_json(200, self.view() or {})
        return self.send_json(404, {"error": "없는 주소"})

def main():
    rclpy.init(); node = rclpy.create_node("kiosk_server", namespace="dsr01")
    node.create_subscription(String, "pick/event", on_event, 50)
    from sensor_msgs.msg import JointState
    def on_js(m):
        d = dict(zip(m.name, m.position))
        if "joint_1" in d: joint["q"] = [d[f"joint_{i}"] for i in range(1, 7)]
    node.create_subscription(JointState, "/dsr01/joint_states", on_js, 10)
    pub = node.create_publisher(String, "pick/event", 10)
    threading.Thread(target=sync_loop, args=(pub,), daemon=True).start()
    threading.Thread(target=rclpy.spin, args=(node,), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", 8765), H)
    print("키오스크: http://localhost:8765  (Ctrl+C 로 끝)", flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    finally: rclpy.shutdown()

if __name__ == "__main__":
    main()
