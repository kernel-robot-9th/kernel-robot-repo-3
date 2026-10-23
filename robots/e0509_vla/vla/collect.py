#!/usr/bin/env python3
"""새우깡 자동 시연 수집 — 로봇이 새우깡을 스스로 놓고 집으며 '집으러 가는' 시연을 녹화한다.

한 에피소드:
  [녹화 안 함] (물고 있으면) 다음 위치 위 공중 -> 수직 하강 -> 놓기 -> 수직 상승
  [녹화 안 함] 무작위 시작 자세로
  [녹화]       새우깡 위 공중(z 260) -> 수직 하강 -> 닫기 -> 수직 상승(z 320)
다음 위치는 9칸을 회차마다 섞은 순서 + ±25mm 흩뜨림.

=== 안전 규칙 (코드로 강제) ===
 R1 낮은 높이(z < LOW_Z)로는 '수직 하강' 함수 두 개로만 간다:
      descend_to_grasp: 그리퍼가 '열림'으로 방금 읽혀야 함 (못 읽으면 안 내려감)
      descend_to_place: 새우깡을 '물고 있음'으로 방금 읽혀야 함
 R2 놓쳤거나(빈손) 상태를 못 믿겠으면 절대 다시 내려가지 않는다. 정지 요청 후 수집 전체 중단. 자동 복구 이동 없음.
 R3 그리퍼 여닫기는 팔이 멈춘 뒤에만, 실제로 멈출 때까지 기다린다.
 R4 z < LOW_Z 에서는 수평 이동 금지. 수평 이동은 항상 z >= LOW_Z.
 R5 어떤 목표도 HARD_FLOOR 아래 금지 (학습 데이터에서 실제로 내려간 최저 높이 근처).
 R6 에피소드마다 로봇 상태(AUTONOMOUS+STANDBY)와 응답속도(ping) 점검. 이상하면 중단.
 그리퍼 상태는 노드가 2Hz 로만 읽는다(20Hz 폴링 때 컨트롤러가 멈춘 적 있음).

    python3 collect.py --dry --episodes 9        # 계획만 출력, 로봇 안 움직임
    python3 collect.py --episodes 1              # 감독하에 1개
    python3 collect.py --episodes 20             # 반복 수집
  시작 위치: --start-xy x y (사람이 처음 새우깡을 놓은 곳, 기본 8번 칸 515 -140)
  멈추기: vla_test/STOP 파일 생성(다음 안전 지점에서 멈춤) 또는 비상정지
"""
import argparse, json, math, random, subprocess, sys, threading, time
from pathlib import Path

import cv2, numpy as np, rclpy
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bag_vision import bag_region, remaining_fraction, set_object
from sensor_msgs.msg import JointState

HERE = Path(__file__).resolve().parent
CAMERA = "/dev/video8"
ROBOT_IP = "110.120.1.59"
ALL_CELLS = {int(k): v for k, v in json.loads((HERE / "shrimp_cells.json").read_text()).items()}
SAFE_X_MIN = 420.0   # 베이스 가까운 칸(1·4·7번, x 330~370)은 특이점 영역 근처라 자동 이동에서 뺀다 (2026-10-16 4번 칸 사고)
REACH_MAX = 690.0    # 베이스에서 이보다 먼 곳은 z260 에서도 팔이 거의 다 펴진다(9번 칸 715mm 는 도달 불가로 계산됨)
CELLS = {k: v for k, v in ALL_CELLS.items() if v[0] >= SAFE_X_MIN and math.hypot(v[0], v[1]) <= REACH_MAX}

LOW_Z = 250.0        # 이 아래는 수직 하강 함수로만
TRAVEL_Z = 320.0     # 수평 이동 높이
PREGRASP_Z = 260.0   # 녹화 중 새우깡 위 공중 지점 (LOW_Z 위)
HARD_FLOOR = 115.0   # 학습 데이터 최저 z 117 근처
PLACE_DZ = 12.0      # 놓을 때는 잡는 높이보다 12mm 위에서 연다 (바닥 누르지 않게)
JITTER = 25.0
BOUNDS_X, BOUNDS_Y = (440.0, 700.0), (-190.0, 190.0)
START_BASE, START_JIT = (430.0, 13.0, 427.0), (25.0, 60.0, 20.0)
ORI = [0.0, 180.0, 0.0]   # 수직, 손목 회전 0 (Codex 시연과 같음). 봉지 방향이 늘 같게 유지된다
V_TRAVEL, V_APPROACH, V_DESCEND, V_LIFT = 60.0, 60.0, 40.0, 50.0
GRIP_OPEN_OK = 700.0      # 이 이상이면 '열림'
GRIP_EMPTY = 60.0         # 이 이하면 빈손일 수 있음. --empty-pos 로 덮어씀(힘별 빈손 닫힘 실측값 + 여유)
# 주의: 힘 250 으로 봉지를 쥐면 공기가 빠져 위치 18 까지 닫혀 빈손(29)과 구분이 안 됐다. 그래서 약하게 쥔다.
GRIP_FRESH_S = 5.0        # 상태가 이보다 오래됐으면 못 믿음 (팔 이동 중 갱신 간격 3.6s 까지 관측)
PING_MAX_MS = 10.0
# 이동 감시: 모든 이동은 '경로 사전검사 -> 비동기 출발 -> 관절값으로 위치 계산(FK)하며 감시 -> 도착 확인'
DEV_MAX_MM = 15.0        # 계획 직선에서 이만큼 벗어나면 즉시 정지
MANIP_MIN = 0.020        # 경로상 조작성(특이점 근접도) 하한. 팔이 다 펴지는 곳(0.012) 같은 극단을 거른다
J2_RANGE, J3_MAX = (-15.0, 60.0), 125.0   # 어깨가 뒤로 젖혀지거나 팔꿈치가 과하게 접히는 경로 거부
ELBOW_X_MIN = -60.0      # 팔꿈치가 베이스 뒤로 넘어가는 경로 거부
SETTLE_S, SETTLE_MAX_S = 2.5, 15.0   # 닫은 뒤 위치가 이 시간 동안 안 변해야 '다 쥠'
# 새우깡: 봉지 겉면에서 멈춘 것처럼 보여도(moving=0) 공기가 빠지며 손가락이 계속 파고든다.
# 그때 들어 올리면 꼬집기가 완성되기 전에 빠진다(2026-10-16 위치 430 에서 들었다가 놓침).
LIFT_SLOW_DZ, V_LIFT_SLOW = 30.0, 15.0
# 바구니 모드 (Codex 시연 29회 모두 x350 y-500 z422~437 에서 열었다. 바구니 높이 30cm)
CARRY_Z = 445.0          # 들고 옮기는 높이. 바구니(높이 30cm) 턱에 처진 봉지가 걸리지 않게 집은 자리에서 먼저 여기까지 올린다.
# 바구니 위(350,-500) 에서 z450 은 조작성 0.019(특이점 직전), z470 이상은 도달 불가로 계산됨 -> 445 (0.024)
V_CARRY = 60.0
RETREAT = (400.0, -350.0, 450.0)
CLEAR = (450.0, 0.0, 450.0)
# 먼 칸(x>600)은 그 자리에서 z445 가 팔 길이 밖(6번 근처 z400 이상 도달 불가, 2026-10-19 계산).
# 그 자리에서 FAR_LIFT_Z 까지만 올리고, 같은 높이로 안쪽 INNER_X 까지 당긴 뒤 CARRY_Z 로 올린다.
FAR_X, FAR_LIFT_Z, INNER_X = 600.0, 300.0, 520.0   # 바구니 쪽에서 다음 칸으로 갈 때 높이를 유지한 채 먼저 들르는 작업대 가운데   # 놓은 뒤 바구니에서 빠져나오는 지점 (옮기는 높이보다 낮아지지 않게)
POINT_Z = 260.0          # 사람이 새우깡을 놓을 자리를 가리키는 높이 (9번 칸에서 300 은 팔이 안 닿음)
# 먼 칸(x~690) 위에서 z430 으로 바로 올리면 손목중심이 어깨에서 ~795mm -> 팔길이(~776mm) 초과 = 다 펴진 특이점.
# 그래서 z260 까지만 올리고 안쪽 경유점으로 온 뒤 거기서 z430 으로 올린다.
TRANSIT = (420.0, -250.0)
RELEASE_TOL_MM = 5.0
# 카메라 판정 (2026-10-19, 금요일 성공 2판: 바구니로 옮긴 뒤 원래 자리 잔존 0.02, 옮기기 전 0.82~0.85)
CAM_HELD_FRAC, CAM_MISSED_FRAC = 0.3, 0.5     # 바구니 위 지점에서 이 이상 벗어나 있으면 열지 않는다


class Stop(Exception):
    """수집 중단. 메시지는 사람에게 보여줄 이유."""


# 잡는 높이: 9칸의 실제 시연 높이를 거리 가중(IDW)으로 섞는다. 칸 중심에서는 시연 높이 그대로라
# 평면 맞춤처럼 어떤 칸에서 시연보다 깊게(4번 칸은 7mm) 내려가는 일이 없다.
_P = np.array([v[:2] for v in ALL_CELLS.values()]); _z = np.array([v[2] for v in ALL_CELLS.values()])
AIR = 0.0
GRASP_MARGIN = 0.0   # 잡는 높이 여유(mm). 3번 칸 z120 에서 손끝 접촉/2번축 충돌감지(2026-10-16 23시)
# 물체별 설정. z_offset 은 새우깡 칸 높이(shrimp_cells.json) 위로 더 올리는 양(mm), out 은 녹화 폴더
OBJECTS = {"shrimp": {"z_offset": 0.0, "out": "collect"},
           "choco": {"z_offset": 15.0, "out": "collect_choco"},
           "ramen": {"z_offset": 53.0, "out": "collect_ramen"}}   # 2026-10-21 컵라면 거꾸로(입구 바닥), 손끝이 윗면 25mm 아래(z186 @ x534 y-49 실기 확인). 전류 80 권장(힘 시험 40~80 모두 버팀, 안 찌그러짐)   # 초코송이 3.5x12x8.5cm 세워 놓음. 2026-10-20 +15mm: 베이스 쪽(1·4·7번)에서 손끝이 책상에 닿을 듯해 사용자 요청. 63편까지는 +0 (손끝-책상 약 30mm)
OBJ_Z = 0.0
OBJ_NAME = "새우깡"
NAMES = {"shrimp": "새우깡", "choco": "초코송이", "ramen": "컵라면"}
def grasp_z(x, y):
    if AIR: return PREGRASP_Z           # 공중 시험: 내려가지 않음
    return _grasp_z_raw(x, y) + GRASP_MARGIN + OBJ_Z

def _grasp_z_raw(x, y):
    d = np.linalg.norm(_P - [x, y], axis=1)
    if d.min() < 1e-6: return float(_z[d.argmin()])
    w = 1.0 / d ** 2
    return float(w @ _z / w.sum())


# 무작위 위치 모드(--random): random_area_check.py 가 만든 20mm 격자 지도(random_area.json)에서
# 둘러싼 네 격자점이 모두 조작성 0.03 이상인 곳만 쓴다. 작업대를 3x3 구역으로 나눠 구역마다 골고루 뽑는다.
RAND_X, RAND_Y, RAND_MAN = (330.0, 670.0), (-185.0, 185.0), 0.03   # 2026-10-19 x330 까지(1·4·7번 칸 포함).
# 베이스 쪽(x<450)은 팔꿈치가 접혀 조작성이 0.02~0.03 이라 실행 중 검사 하한(MANIP_MIN 0.02)을 쓴다. 4번 칸 잡는 자세 j3 124°, 조작성 0.028
def _area_ok(x, y, grid):
    x0, y0 = math.floor(x / 20) * 20, math.floor(y / 20) * 20
    lim = MANIP_MIN if x < 450 else RAND_MAN
    return all(grid.get(f"{gx},{gy}", -1) >= lim for gx in (x0, x0 + 20) for gy in (y0, y0 + 20))

NEAR_ONLY = False   # --near-only: 로봇 쪽 줄(R1~R3 구역 + 1·4·7번 칸)만 (10-22 컵라면 로봇 쪽 보정용)
FAR_EXTRA = 0   # 먼 줄(3·6·9번 칸 쪽, R7~R9) 구역을 한 바퀴에 몇 번 더 넣을지 (--far-extra)
def schedule_random(n, seed):
    grid = json.loads((HERE / "random_area.json").read_text())
    rng = random.Random(seed); out = []
    xe = np.linspace(*RAND_X, 4); ye = np.linspace(*RAND_Y, 4)
    # 베이스 쪽 1·4·7번 칸은 9구역 무작위로는 거의 안 뽑혀서(가장자리) 칸 자체를 한 바퀴에 한 번씩 넣는다.
    # 칸 중심 ±20mm 를 실제 경로 IK 로 하나씩 검사(random_area_check.route). 4번 칸은 베이스 쪽(-x)으로 20mm 가면 관절 범위 밖.
    from random_area_check import route as _route
    NEAR = {1: ((-20, 20), (-20, 20)), 4: ((0, 20), (-20, 20)), 7: ((-20, 20), (-20, 20))}
    slots = [(i, j) for i in range(3) for j in range(3)] + [("C", c) for c in NEAR]
    if NEAR_ONLY: slots = [(0, j) for j in range(3)] + [("C", c) for c in NEAR]
    slots += [(2, j) for j in range(3)] * FAR_EXTRA   # 2026-10-21 사용자: 3·6·9번 칸 쪽을 더 (안전 영역 안, x 557~650)
    while len(out) < n:
        rng.shuffle(slots)
        for i, j in slots:
            for _ in range(300):
                if i == "C":
                    (dx0, dx1), (dy0, dy1) = NEAR[j]; cx, cy = ALL_CELLS[j][:2]
                    x, y = cx + rng.uniform(dx0, dx1), cy + rng.uniform(dy0, dy1)
                    if _route(x, y) >= MANIP_MIN: break
                else:
                    x, y = rng.uniform(xe[i], xe[i + 1]), rng.uniform(ye[j], ye[j + 1])
                    if _area_ok(x, y, grid) and math.hypot(x, y) <= REACH_MAX: break
            else: continue                      # 이 구역은 거의 다 막힘 -> 건너뜀
            s = [START_BASE[i_] + rng.uniform(-START_JIT[i_], START_JIT[i_]) for i_ in range(3)]
            out.append({"cell": j if i == "C" else f"R{i * 3 + j + 1}", "x": x, "y": y, "start": s})
    return out[:n]

def place_name(p):
    return f"{p['cell']}번 칸" if isinstance(p["cell"], int) else f"무작위 {p['cell']}구역"

def schedule(n, seed):
    rng = random.Random(seed); out = []
    while len(out) < n:
        cells = list(CELLS); rng.shuffle(cells)
        for c in cells:
            cx, cy = CELLS[c][:2]
            for _ in range(100):
                x = float(np.clip(cx + rng.uniform(-JITTER, JITTER), *BOUNDS_X))
                y = float(np.clip(cy + rng.uniform(-JITTER, JITTER), *BOUNDS_Y))
                if math.hypot(x, y) <= REACH_MAX: break
            s = [START_BASE[i] + rng.uniform(-START_JIT[i], START_JIT[i]) for i in range(3)]
            out.append({"cell": c, "x": x, "y": y, "start": s})
    return out[:n]


class Recorder:
    """카메라 10Hz + 최신 관절/그리퍼 상태를 프레임마다 기록. ROS 호출 없음(값은 메인에서 갱신)."""
    def __init__(self, shared):
        self.shared = shared; self.cap = cv2.VideoCapture(CAMERA, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640); self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 30); self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        for _ in range(25): self.cap.read()
        self.latest = None; self.alive = True; self.rec = None
        self.rec_lock = threading.Lock()
        threading.Thread(target=self._grab, daemon=True).start()
        threading.Thread(target=self._write, daemon=True).start()

    def _grab(self):
        while self.alive:
            ok, f = self.cap.read()
            if ok: self.latest = (time.monotonic(), f)

    def _write(self):
        nxt = time.monotonic()
        while self.alive:
            nxt += 0.1; time.sleep(max(0.0, nxt - time.monotonic()))
            with self.rec_lock:
                r = self.rec
                if r is None or self.latest is None: continue
                t, f = self.latest; s = dict(self.shared); now = time.monotonic()
                q_image = next((x for x in reversed(s.get("q_history", ())) if x["received_mono"] <= t), None)
                g_image = next((x for x in reversed(s.get("g_history", ())) if x["received_mono"] <= t), None)
                i = len(r["rows"]); name = f"frames/{i:05d}.jpg"
                encode_t = time.monotonic()
                cv2.imwrite(str(r["dir"] / name), f, [cv2.IMWRITE_JPEG_QUALITY, 95])
                r["rows"].append({"i": i, "t": now, "image": name, "image_age_s": now - t,
                                  "joints": s.get("q"), "joints_age_s": now - s.get("q_t", 0),
                                  "gripper_pos": s.get("g_pos"), "gripper_current": s.get("g_cur"),
                                  "gripper_age_s": now - s.get("g_t", 0) if s.get("g_t") else None,
                                  "cmd_gripper_open": s.get("cmd_open"), "cmd_current": s.get("cmd_cur"),
                                  "phase": s.get("phase"), "image_received_mono": t,
                                  "arm_target": s.get("arm_target"), "arm_requested_mono": s.get("arm_requested_mono"),
                                  "joints_received_mono": s.get("q_t"), "gripper_received_mono": s.get("g_t"),
                                  "state_minus_image_s": s.get("q_t", t) - t,
                                  "joints_at_image": q_image, "gripper_at_image": g_image,
                                  "arm_status": s.get("arm_status"), "jpeg_write_s": time.monotonic()-encode_t})

    def start(self, d):
        (d / "frames").mkdir(parents=True); self.rec = {"dir": d, "rows": []}

    def stop(self):
        with self.rec_lock:
            r, self.rec = self.rec, None
        if r:
            with (r["dir"] / "frames.jsonl").open("w") as fh:
                for row in r["rows"]: fh.write(json.dumps(row) + "\n")
        return 0 if r is None else len(r["rows"])

    def close(self):
        self.alive = False; time.sleep(0.2); self.cap.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=1)
    ap.add_argument("--current", type=int, default=130, help="파지 전류. 250 은 봉지가 터질 듯 눌림")
    ap.add_argument("--empty-pos", type=float, default=None, help="이 위치 이하면 빈손으로 본다")
    ap.add_argument("--start-xy", type=float, nargs=2, default=[515.0, -140.0])
    ap.add_argument("--seed", type=int, default=int(time.time()) % 100000)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--near-only", action="store_true", help="로봇 쪽 줄(R1~R3 + 1·4·7번 칸)만 뽑음")
    ap.add_argument("--look-photo", action="store_true", help="놓은 뒤 팔을 비킨 자세(RETREAT)에서 사진 한 장(ep/look.jpg). 그리퍼가 안 가린 사진으로 카메라 보정")
    ap.add_argument("--far-extra", type=int, default=0, help="먼 줄(R7~R9) 구역을 한 바퀴에 이만큼 더 넣음 (1 이면 2배)")
    ap.add_argument("--basket", action="store_true", help="집은 뒤 바구니까지 옮겨 놓는 전체 작업을 녹화 (매 판 사람이 봉지를 꺼내 놓음)")
    ap.add_argument("--basket-xy", type=float, nargs=2, default=[350.0, -500.0])
    ap.add_argument("--cells", type=int, nargs="+", help="이 칸들만 사용 (예: --cells 5)")
    ap.add_argument("--random", action="store_true", help="칸 대신 작업대 전체(안전 지도 안)에서 무작위 위치, 3x3 구역 골고루")
    ap.add_argument("--snack-xy", type=float, nargs=2, help="새우깡이 이미 이 자리에 놓여 있음: 첫 판은 가리키지 않고 바로 집기")
    ap.add_argument("--grasp-margin", type=float, default=0.0, help="잡는 높이를 이만큼 올림(mm)")
    ap.add_argument("--object", choices=sorted(OBJECTS), default="shrimp", help="잡을 물체 (높이·색·녹화 폴더가 바뀜)")
    ap.add_argument("--air", action="store_true", help="공중 시험: 실제 경로로 가되 새우깡 위 아래로 안 내려가고 그리퍼·녹화·질문 없음")
    ap.add_argument("--gripper-empty-ok", action="store_true", help="시작 시 그리퍼가 닫혀 있으면 사람이 빈손을 확인했을 때만 공중에서 연다")
    a = ap.parse_args()
    if not 0 < a.current <= 400: print("current 1~400"); return 1
    global GRIP_EMPTY, LOW_Z, TRAVEL_Z, PREGRASP_Z, HARD_FLOOR, CARRY_Z, POINT_Z, RETREAT, START_BASE, AIR, OBJ_NAME
    if a.empty_pos is not None: GRIP_EMPTY = a.empty_pos
    AIR = a.air
    if AIR:
        print(f"*** 공중 시험: 실제 경로 그대로, 단 {OBJ_NAME} 위 z{PREGRASP_Z:.0f} 아래로는 안 내려감. 그리퍼/녹화/질문 없음 ***")

    global CELLS, GRASP_MARGIN, OBJ_Z, FAR_EXTRA, NEAR_ONLY
    NEAR_ONLY = a.near_only
    FAR_EXTRA = max(0, a.far_extra)
    GRASP_MARGIN = a.grasp_margin
    obj = OBJECTS[a.object]
    if obj["z_offset"] is None: print(f"{a.object}: 잡는 높이가 아직 정해지지 않음 (height_check 먼저)"); return 1
    OBJ_Z = obj["z_offset"]; OBJ_NAME = NAMES[a.object]
    try: set_object(a.object)
    except ValueError as e: print(e); return 1
    print(f"물체 {a.object}: 칸 높이 +{OBJ_Z:.0f}mm, 녹화 {obj['out']}/")
    if a.cells:
        bad = [c for c in a.cells if c not in CELLS]
        if bad: print(f"사용 불가 칸 {bad} (가능: {sorted(CELLS)})"); return 1
        CELLS = {c: CELLS[c] for c in a.cells}
    if a.random and a.cells: print("--random 과 --cells 는 같이 못 씀"); return 1
    plan = schedule_random(a.episodes, a.seed) if a.random else schedule(a.episodes, a.seed)
    print(f"잡는 높이: 9칸 시연 높이 IDW 보간 (seed {a.seed})")
    snack = list(a.start_xy)
    for k, p in enumerate(plan, 1):
        if k > 1 or a.basket:
            how = f"사람이 놓음(가리키기 z{POINT_Z:.0f})" if a.basket else f"로봇이 놓음(여는 높이 z{grasp_z(p['x'], p['y']) + PLACE_DZ:.0f})"
            print(f"  {place_name(p)} x{p['x']:.0f} y{p['y']:.0f} {how}")
            snack = [p["x"], p["y"]]
        gz = grasp_z(*snack)
        print(f"ep{k:02d} 시작 x{p['start'][0]:.0f} y{p['start'][1]:.0f} z{p['start'][2]:.0f} -> {OBJ_NAME} x{snack[0]:.0f} y{snack[1]:.0f}"
              f" 위 z{PREGRASP_Z:.0f} -> 하강 z{gz:.1f} -> 닫기 -> "
              + (f"z{CARRY_Z:.0f} -> 바구니 x{a.basket_xy[0]:.0f} y{a.basket_xy[1]:.0f} 열기 -> 빠짐" if a.basket else f"z{TRAVEL_Z:.0f}"))
        assert gz >= HARD_FLOOR and gz + PLACE_DZ >= HARD_FLOOR
    if a.dry:
        print("--dry: 로봇 안 움직임"); return 0

    import DR_init
    DR_init.__dsr__id, DR_init.__dsr__model = "dsr01", "e0509"
    rclpy.init(); node = rclpy.create_node("shrimp_collect", namespace="dsr01"); DR_init.__dsr__node = node
    from DSR_ROBOT2 import movel, posx, get_current_posx, DR_BASE
    from dsr_msgs2.srv import GetRobotMode, GetRobotState
    from dsr_gripper import gripper_cmd, gripper_wait
    from dsr_gripper.gripper_api import gripper_state

    shared = {"cmd_open": 1.0, "cmd_cur": None, "phase": "idle"}
    def sample_history(key, sample):
        # Immutable snapshots: recorder thread cannot observe a mutated deque/list.
        shared[key] = (shared.get(key, ()) + (sample,))[-500:]

    def on_js(m):
        d = dict(zip(m.name, m.position))
        if "joint_1" in d:
            shared["q"] = [d[f"joint_{i}"] for i in range(1, 7)]; shared["q_t"] = time.monotonic()
            dv = dict(zip(m.name, m.velocity)) if len(m.velocity) == len(m.name) else {}
            shared["qd"] = [dv[f"joint_{i}"] for i in range(1, 7)] if all(f"joint_{i}" in dv for i in range(1, 7)) else None
            sample_history("q_history", {"received_mono": shared["q_t"],
                "source_stamp": [m.header.stamp.sec, m.header.stamp.nanosec],
                "position": list(shared["q"]), "velocity": shared["qd"]})
    def on_grip(m):
        shared["g_pos"] = m.position[0]; shared["g_cur"] = m.effort[0]; shared["g_mov"] = m.velocity[0] > 0.5
        shared["g_t"] = time.monotonic()
        sample_history("g_history", {"received_mono": shared["g_t"],
            "source_stamp": [m.header.stamp.sec, m.header.stamp.nanosec],
            "position": shared["g_pos"], "current": shared["g_cur"], "moving": shared["g_mov"]})
    node.create_subscription(JointState, "/dsr01/joint_states", on_js, 10)
    node.create_subscription(JointState, "/dsr01/gripper/state", on_grip, 10)

    def spin_for(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end: rclpy.spin_once(node, timeout_sec=0.02)

    def tcp():
        # 컨트롤러 get_current_posx 가 가끔 0 을 돌려줬다(2026-10-16 23:34, 'R4 현재 z0' 오거부).
        # 관절값 FK 로 계산한다 (컨트롤러 TCP=플랜지, FK 와 0.0mm 일치 확인). 이동 판단에는 xyz 만 쓴다.
        p = FKC.fk(fresh_q())[0]
        return [float(p[0]), float(p[1]), float(p[2])] + list(ORI)

    sim = {"g": 750.0}
    def grip(fresh_within=GRIP_FRESH_S):
        """방금 받은 그리퍼 위치. 오래됐으면 Stop. 공중 시험에서는 가상의 값."""
        if AIR: return sim["g"]
        spin_for(0.05)
        if "g_t" not in shared or time.monotonic() - shared["g_t"] > fresh_within:
            raise Stop("그리퍼 상태가 안 들어옴/오래됨 -> 상태를 믿을 수 없어 중단")
        if not math.isfinite(shared["g_pos"]): raise Stop("유효하지 않은 그리퍼 위치")
        # 2026-10-19 17:0x: 한 번 -5138 이 읽힘(레지스터 읽기 깨짐, 곧바로 750). 물리 범위(-50~800) 밖이면
        # 새 메시지를 최대 3개(약 3초) 더 기다려 다시 본다. 그래도 이상하면 그 값을 그대로 돌려 호출한 쪽이 멈추게 함.
        for _ in range(3):
            if -50.0 <= shared["g_pos"] <= 800.0: break
            event("gripper_bad_read", position=shared["g_pos"]); t_bad = shared["g_t"]; t_w = time.monotonic()
            while shared["g_t"] == t_bad and time.monotonic() - t_w < 3.0: spin_for(0.1)
        return shared["g_pos"]

    def check_robot():
        for srv, name, attr in ((GetRobotMode, "get_robot_mode", "robot_mode"), (GetRobotState, "get_robot_state", "robot_state")):
            c = node.create_client(srv, f"/dsr01/dsr_controller2/system/{name}")
            if not c.wait_for_service(timeout_sec=3.0): raise Stop(f"{name} 서비스 없음")
            f = c.call_async(srv.Request()); rclpy.spin_until_future_complete(node, f, timeout_sec=5.0)
            v = getattr(f.result(), attr, None)
            if name == "get_robot_state" and v == 3 and sys.stdin.isatty():
                if ask("서보가 꺼졌습니다(대기가 길면 꺼짐). 서보 켤까요? 팔은 안 움직입니다 [Enter=예 / n]: ") == "n":
                    raise Stop("서보 꺼짐")
                from dsr_msgs2.srv import SetRobotControl
                cc = node.create_client(SetRobotControl, "/dsr01/dsr_controller2/system/set_robot_control"); cc.wait_for_service(timeout_sec=3.0)
                ff = cc.call_async(SetRobotControl.Request(robot_control=3)); rclpy.spin_until_future_complete(node, ff, timeout_sec=5.0)
                spin_for(2.0); return check_robot()
            if v != 1: raise Stop(f"{name}={v} (AUTONOMOUS+STANDBY 아님)")
        # 2026-10-19 15:30: 학습·업로드 중 ping 이 가끔 한 번씩 16~87ms 로 튐(곧바로 0.15ms). 평균 3개는 튀는 1개에 끌려가
        # 멈췄다. 과부하는 계속 느려지는 것(40~150ms 지속)이라 7개 중앙값으로 보고, 넘으면 3초 뒤 한 번 더 잰다.
        def ping_med():
            out = subprocess.run(["ping", "-c", "7", "-i", "0.2", "-W", "1", ROBOT_IP], capture_output=True, text=True).stdout
            t = sorted(float(l.split("time=")[1].split()[0]) for l in out.splitlines() if "time=" in l)
            return (t[len(t) // 2] if len(t) >= 5 else None), (t[-1] if t else None)
        med, mx = ping_med()
        if med is None or med > PING_MAX_MS:
            print(f"    ping 중앙값 {med} ms (최대 {mx}) -> 3초 뒤 다시 잼", flush=True); spin_for(3.0); med, mx = ping_med()
        event("ping", median_ms=med, max_ms=mx)
        if med is None or med > PING_MAX_MS: raise Stop(f"로봇 응답 느림/없음 (ping 중앙값 {med} ms, 최대 {mx}) -> 컨트롤러 과부하 의심")
        if (HERE / "STOP").exists(): raise Stop("STOP 파일")

    def ask(msg):
        if AIR: print("    (공중시험) 질문 생략:", msg.strip()[:40], flush=True); spin_for(1.0); return ""
        if not sys.stdin.isatty(): raise Stop("사람 입력이 필요한데 대화형 터미널이 아님")
        return input(msg).strip().lower()

    # ---- 안전 이동 함수들: 낮은 곳은 여기로만 간다 ----
    sys.path.insert(0, str(HERE))
    from fk import Chain, zyz_to_matrix
    from path_check import ik as _ik, jac as _jac, validate_solution
    from DSR_ROBOT2 import amovel, check_motion
    from dsr_msgs2.srv import MoveStop
    FKC, FK3 = Chain(), Chain(tip="link_3"); R_ORI = zyz_to_matrix(*ORI)
    stop_cli = node.create_client(MoveStop, "/dsr01/dsr_controller2/motion/move_stop")
    mlog = None

    stop_requested = False
    def event(kind, **fields):
        row = {"event": kind, "t": time.time(), "mono": time.monotonic(), **fields}
        if mlog is not None:
            try:
                mlog.write(json.dumps(row, ensure_ascii=False) + "\n"); mlog.flush()
            except (OSError, TypeError, ValueError) as exc:
                shared["logging_error"] = repr(exc)
                # Recording failures must never prevent a stop request.
                try: print("이벤트 기록 실패:", repr(exc), flush=True)
                except OSError: pass

    def stop_now():
        nonlocal stop_requested
        if stop_requested: return
        stop_requested = True
        event("stop_requested")
        try:
            if not stop_cli.wait_for_service(timeout_sec=1.0): raise RuntimeError("stop service unavailable")
            f = stop_cli.call_async(MoveStop.Request(stop_mode=1))
            rclpy.spin_until_future_complete(node, f, timeout_sec=2.0)
            result = f.result() if f.done() else None
            ok = result is not None and bool(result.success)
            event("stop_response", success=ok)
            if not ok: print("정지 응답 확인 실패: 현장 정지 상태 확인 필요", flush=True)
        except Exception as exc:
            event("stop_response", success=False, error=repr(exc))
            print("정지 요청 실패:", repr(exc), flush=True)

    def fresh_q(max_age=0.3):
        end = time.monotonic() + (max_age if shared.get("motion_pending") else 2.0)
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.01)
            if "q_t" in shared and time.monotonic() - shared["q_t"] < max_age:
                q = np.array(shared["q"])
                if q.shape == (6,) and np.isfinite(q).all(): return q
        raise Stop("관절 상태가 안 들어옴")

    def check_path(q0, p0, target, name):
        """직선 경로를 관절 공간에서 미리 따라가 본다. 위험하면 출발 전에 거부."""
        q = np.array(q0, float); worst = 9.0
        for t in np.linspace(0.0, 1.0, 10):
            pt = p0 + (target - p0) * t
            try:
                q, err = _ik(q, pt, R_ORI, it=40)
                validate_solution(q, pt, R_ORI)
            except ValueError as exc:
                raise Stop(f"{name}: 경로 사전검사 - {exc}") from exc
            if err > 2.0: raise Stop(f"{name}: 경로 사전검사 - 도달 불가(IK 오차 {err:.1f}mm)")
            J = _jac(q); man = math.sqrt(max(np.linalg.det(J @ J.T), 0.0)); worst = min(worst, man)
            jd = np.degrees(q)
            if not (J2_RANGE[0] <= jd[1] <= J2_RANGE[1]) or jd[2] > J3_MAX:
                raise Stop(f"{name}: 경로 사전검사 - 관절 범위 밖 (j2 {jd[1]:.0f}, j3 {jd[2]:.0f}) @ {pt.round(0)}")
            if FK3.fk(q)[0][0] < ELBOW_X_MIN:
                raise Stop(f"{name}: 경로 사전검사 - 팔꿈치가 베이스 뒤로 넘어감 @ {pt.round(0)}")
        if worst < MANIP_MIN:
            raise Stop(f"{name}: 경로 사전검사 - 특이점 근접 (조작성 {worst:.3f} < {MANIP_MIN})")
        return worst

    def _go(p, v, name="move"):
        assert p[2] >= HARD_FLOOR, f"R5 위반 z{p[2]}"
        target = np.array(p, float)
        q0 = fresh_q(); p0 = FKC.fk(q0)[0]
        shared["arm_status"] = "preflight"
        preflight_t = time.monotonic()
        event("preflight_started", name=name, target=list(p)+ORI)
        man = check_path(q0, p0, target, name)
        event("preflight_completed", name=name, sec=time.monotonic()-preflight_t)
        seg = target - p0; L = float(np.linalg.norm(seg))
        t0 = time.monotonic(); t_lim = L / v * 1.6 + 5.0; maxdev = 0.0
        try:
            event("motion_requested", name=name, target=list(p) + ORI, velocity=[v, 30.0], acceleration=[2*v, 60.0])
            shared["arm_target"] = list(p) + ORI
            shared["arm_requested_mono"] = time.monotonic()
            shared["motion_pending"] = True; shared["arm_status"] = "requested"
            result = amovel(posx(list(p) + ORI), vel=[v, 30.0], acc=[2 * v, 60.0], ref=DR_BASE)
            event("motion_response", name=name, result=result)
            if result != 0: raise Stop(f"{name}: 이동 명령 거부 {result}")
            shared["arm_status"] = "accepted"
            while True:
                if (HERE / "STOP").exists(): raise Stop("STOP 파일")
                q = fresh_q(); pf = FKC.fk(q)[0]
                if not np.isfinite(pf).all(): raise Stop("유효하지 않은 FK 상태")
                s_ = float(np.clip(np.dot(pf - p0, seg) / (L * L), 0.0, 1.0)) if L > 1e-6 else 0.0
                dev = float(np.linalg.norm(pf - (p0 + s_ * seg))); maxdev = max(maxdev, dev)
                if dev > DEV_MAX_MM:
                    stop_now()
                    raise Stop(f"{name}: 계획 경로에서 {dev:.0f}mm 벗어남 -> 즉시 정지 (위치 {pf.round(0)}, 목표 {target.round(0)})")
                if np.linalg.norm(pf - target) < 1.0 and shared.get("qd") is not None and np.isfinite(shared["qd"]).all() and max(abs(x) for x in shared["qd"]) < 0.005:
                    break
                if time.monotonic() - t0 > t_lim:
                    stop_now(); raise Stop(f"{name}: 시간 초과 (위치 {pf.round(0)}, 목표 {target.round(0)})")
            # 관절값으로는 도착했어도 컨트롤러 내부 동작이 마무리 중일 수 있다. 그 사이 다음 명령을 보내면
            # 7025(모션 컨트롤러 시퀀스 번호 오류)가 의심됨(2026-10-19 11:24, 12:19 두 번 모두 연속 이동 중 발생).
            # 컨트롤러가 대기(0)라고 할 때까지 기다린다.
            t_idle = time.monotonic(); st_m = None
            while time.monotonic() - t_idle < 3.0:
                st_m = check_motion()
                if st_m == 0: break
                spin_for(0.05)
            event("controller_idle_wait", name=name, status=st_m, wait_s=time.monotonic() - t_idle)
            if st_m != 0: raise Stop(f"{name}: 도착했지만 컨트롤러가 동작 완료를 알리지 않음 (check_motion={st_m})")
            shared["arm_status"] = "completed"
            event("motion_completed", name=name, arrived=pf.tolist(), sec=time.monotonic()-t0)
            if mlog is not None:
                mlog.write(json.dumps({"t": time.time(), "name": name, "from": p0.tolist(), "to": target.tolist(),
                                       "arrived": pf.tolist(), "max_dev_mm": maxdev, "min_manip": man,
                                       "sec": time.monotonic() - t0}) + "\n"); mlog.flush()
        except (Exception, KeyboardInterrupt) as exc:
            stop_now()
            shared["arm_status"] = "failed"
            event("motion_failed", name=name, target=list(p)+ORI, error=repr(exc))
            raise
        finally:
            shared["motion_pending"] = False

    def move_high(x, y, z, v):
        """R4: 수평 이동은 출발·도착 모두 LOW_Z 이상일 때만."""
        cur = tcp()
        if cur[2] < LOW_Z - 1.0 or z < LOW_Z:
            raise Stop(f"R4: 낮은 높이 수평 이동 거부 (현재 z{cur[2]:.0f} -> 목표 z{z:.0f})")
        _go([x, y, z], v, "수평이동")

    def rise_to(z, v=V_LIFT):
        """수직 상승만 (xy 그대로). 내려가는 데 쓰면 거부."""
        cur = tcp()
        if z < cur[2] - 1.0: raise Stop("rise_to 로 하강 시도")
        _go([cur[0], cur[1], z], v, "상승")

    def _vertical_only(x, y):
        cur = tcp()
        if math.dist(cur[:2], (x, y)) > 2.0 or cur[2] < LOW_Z - 1.0:
            raise Stop(f"수직 하강 전제 위반: 현재 x{cur[0]:.0f} y{cur[1]:.0f} z{cur[2]:.0f}")

    def descend_to_grasp(x, y, z):
        """R1: 그리퍼가 열려 있다고 방금 읽혀야만."""
        _vertical_only(x, y)
        g = grip()
        if g < GRIP_OPEN_OK: raise Stop(f"R1: 그리퍼가 열려 있지 않음(위치 {g:.0f}) -> 잡으러 내려가지 않음")
        _go([x, y, z], V_DESCEND, "잡기하강")

    def descend_to_place(x, y, z):
        """R1: 물고 있다고 방금 읽혀야만."""
        _vertical_only(x, y)
        g = grip()
        if not (GRIP_EMPTY < g < GRIP_OPEN_OK): raise Stop(f"R1: 물고 있지 않음(위치 {g:.0f}) -> 놓으러 내려가지 않음")
        _go([x, y, z], V_DESCEND, "놓기하강")

    def open_gripper():
        if AIR: sim["g"] = 750.0; print("    (공중시험) 그리퍼 열기 생략", flush=True); spin_for(0.5); return
        event("gripper_requested", position=750, current=200)
        if not gripper_cmd(750, 200): raise Stop("그리퍼 열기 명령 실패")
        shared["cmd_open"] = 1.0; shared["cmd_cur"] = 200
        event("gripper_accepted", position=750, current=200)
        shared["closed_once"] = False
        st = gripper_wait(timeout=12.0)
        if st is None or st["moving"] or st["position"] < GRIP_OPEN_OK: raise Stop(f"그리퍼가 다 안 열림: {st}")

    def close_gripper(current):
        if AIR: sim["g"] = 300.0; print("    (공중시험) 그리퍼 닫기 생략", flush=True); spin_for(0.5); return 300.0
        event("gripper_requested", position=0, current=current)
        if not gripper_cmd(0, current): raise Stop("그리퍼 닫기 명령 실패")
        shared["cmd_open"] = 0.0; shared["cmd_cur"] = current; shared["closed_once"] = True
        event("gripper_accepted", position=0, current=current)
        st = gripper_wait(timeout=12.0)
        if st is None or st["moving"]: raise Stop("닫기 완료 확인 실패")
        event("gripper_stopped", state=st)
        last, t0 = st["position"], time.monotonic(); t_change = t0
        last_stamp = st["t"]
        while True:
            if time.monotonic() - t0 > SETTLE_MAX_S: raise Stop("그리퍼 안정화 시간 초과")
            st = gripper_state()
            if st is None: raise Stop("그리퍼 피드백 없음")
            if st["t"] <= last_stamp: continue
            last_stamp = st["t"]; p = st["position"]
            if st["moving"] or abs(p - last) > 3.0:
                last, t_change = p, time.monotonic()
            elif time.monotonic() - t_change >= SETTLE_S: break
        event("gripper_settled", position=last, sec=time.monotonic()-t0)
        return last

    def carry_to_basket(bx, by):
        """봉지를 쥔 상태에서 바구니 위(CARRY_Z)까지. 바구니 쪽으로 낮게 다가가는 구간 없음."""
        cur = tcp()
        if cur[0] > FAR_X:
            if cur[2] < FAR_LIFT_Z - 1: rise_to(FAR_LIFT_Z)
            move_high(INNER_X, cur[1], max(FAR_LIFT_Z, tcp()[2]), V_CARRY)   # 바구니 반대편(안쪽)으로 당김
        if tcp()[2] < CARRY_Z - 1: rise_to(CARRY_Z)
        move_high(bx, by, CARRY_Z, V_CARRY)

    def abort_up(reason, empty):
        """Failure stops only; never move or open automatically."""
        stop_now()
        event("failure", reason=str(reason))
        print(f"\n!!! 중단: {reason}. 자동 복구 이동 없음. 집게 상태 유지.", flush=True)

    run = HERE / OBJECTS[a.object]["out"] / time.strftime("%Y%m%d_%H%M%S"); run.mkdir(parents=True)
    (run / "plan.json").write_text(json.dumps({"seed": a.seed, "current": a.current, "plan": plan,
                                               "start_xy": a.start_xy, "cells": CELLS}, indent=1))
    class _NoRec:
        rec = None
        def start(self, d): d.mkdir(parents=True, exist_ok=True)
        def stop(self): return 0
        def close(self): pass
    rec = _NoRec() if AIR else Recorder(shared); holding = False; snack = list(a.start_xy); done = 0
    mlog = (run / "motion_log.jsonl").open("w")
    # 2026-10-21: 그리퍼 상태 읽기는 평소 꺼져 있음(컨트롤러 과부하 대책) -> 수집하는 동안만 켠다
    from std_srvs.srv import SetBool
    st_cli = node.create_client(SetBool, "/dsr01/gripper/state_enable")
    def grip_state(on):
        if not st_cli.wait_for_service(timeout_sec=2.0): return False
        f = st_cli.call_async(SetBool.Request(data=on)); rclpy.spin_until_future_complete(node, f, timeout_sec=3.0)
        return f.done() and f.result() is not None and f.result().success
    try:
        if not grip_state(True): print("(그리퍼 상태 켜기 서비스 없음: 예전 노드면 늘 켜져 있음)", flush=True)
        check_robot()
        cur = tcp()
        if cur[2] < LOW_Z:
            # 제자리 수직 상승은 언제나 안전한 동작이다(놓쳤을 때도 위로만 빠지는 게 원칙). 멈추지 않고 올린다.
            print(f"    시작 높이 z{cur[2]:.0f} 가 낮음 -> 제자리에서 수직으로 z{LOW_Z + 10:.0f} 까지 상승", flush=True)
            rise_to(LOW_Z + 10.0)
        # 2026-10-19 15:54: 시작 직후 첫 그리퍼 상태(1.5Hz)가 오기 전에 읽어 '안 들어옴'으로 멈춤 -> 첫 메시지를 최대 8초 기다림
        t_w = time.monotonic()
        while "g_t" not in shared and time.monotonic() - t_w < 8.0: spin_for(0.1)
        g0 = grip()
        if GRIP_EMPTY < g0 < GRIP_OPEN_OK:
            # 지난 실행이 새우깡을 문 채 끝났다. 여기서 열면 공중에서 떨어뜨린다 -> 놓기부터 한다.
            holding = True
            print(f"그리퍼가 물고 있는 상태(위치 {g0:.0f}) -> 첫 동작은 놓기", flush=True)
        elif g0 <= GRIP_EMPTY:
            # 위치만으로는 빈손과 얇게 꼬집은 봉지를 구분 못 한다. 사람이 확인한 경우에만 연다.
            if not a.gripper_empty_ok:
                shared["closed_once"] = True     # 내용물을 모르니 중단 처리에서도 열지 않게
                raise Stop(f"시작 시 그리퍼가 닫혀 있음(위치 {g0:.0f}). 빈손이면 --gripper-empty-ok 로 다시 실행")
            open_gripper()
        for k, p in enumerate(plan, 1):
            ep = run / f"ep{k:03d}"
            placed = holding
            if holding and a.basket:   # ---- 쥔 채로 시작: 작업대에 내려놓지 않고(충돌 위험) 바구니에 갖다 놓음, 녹화 안 함
                shared["phase"] = "deliver"
                print(f"    쥐고 있던 {OBJ_NAME}을(를) 바구니에 먼저 갖다 놓음 (녹화 안 함)", flush=True)
                carry_to_basket(*a.basket_xy); open_gripper(); move_high(*RETREAT, V_TRAVEL)
                holding = False; placed = False
                print(f"    바구니에 놓음. {OBJ_NAME}을(를) 꺼내 두세요.", flush=True)
            if holding:   # ---- 놓기 (녹화 안 함, 바구니 모드가 아닐 때만)
                shared["phase"] = "place"
                gz = grasp_z(p["x"], p["y"])
                rise_to(max(TRAVEL_Z, tcp()[2])); move_high(p["x"], p["y"], TRAVEL_Z, V_TRAVEL)
                descend_to_place(p["x"], p["y"], gz + PLACE_DZ)
                open_gripper(); rise_to(TRAVEL_Z); holding = False; snack = [p["x"], p["y"]]
            elif a.basket and k == 1 and a.snack_xy:   # ---- 이미 놓여 있는 자리에서 바로 시작
                placed = True; snack = list(a.snack_xy)
                print(f"[ep{k}] {OBJ_NAME}(이) x{snack[0]:.0f} y{snack[1]:.0f} 에 있다고 보고 바로 시작", flush=True)
            elif a.basket:   # ---- 사람이 바구니에서 꺼내 가리킨 자리에 놓음
                check_robot()
                if grip() < GRIP_OPEN_OK: raise Stop("그리퍼가 열려 있지 않음")
                cur = tcp()
                if cur[1] < -200.0:
                    # 바구니 쪽에서 곧장 대각선으로 내려가면 바구니 턱 근처를 낮게 지난다 (2026-10-19 사용자 지적)
                    move_high(CLEAR[0], CLEAR[1], max(cur[2], CLEAR[2]), V_TRAVEL)
                move_high(p["x"], p["y"], POINT_Z, V_TRAVEL)
                ans = ask(f"\n[ep{k}] {place_name(p)} — 그리퍼 바로 아래에 {OBJ_NAME} 가운데가 오게 놓고, 손을 치운 뒤 Enter (q=끝): ")
                if ans == "q": print("사용자가 끝냄"); break
                placed = True; snack = [p["x"], p["y"]]
            if a.look_photo and placed and not AIR:
                # 10-22: 시작 자세 그리퍼(검정)가 로봇 쪽 컵의 검은 테이프와 붙어 보임 -> 팔을 비킨 자세에서 한 장 (카메라 보정용)
                move_high(*RETREAT, V_TRAVEL); spin_for(1.0)
                if getattr(rec, "latest", None) is not None:
                    ep.mkdir(parents=True, exist_ok=True); cv2.imwrite(str(ep / "look.jpg"), rec.latest[1])
                    print(f"    비킨 자세 사진 저장 {ep.name}/look.jpg", flush=True)
            check_robot()
            if grip() < GRIP_OPEN_OK: raise Stop("시작 전 그리퍼가 열려 있지 않음")
            s = p["start"]; move_high(s[0], s[1], s[2], V_TRAVEL)
            spin_for(0.5)
            # ---- 녹화 구간
            gz = grasp_z(*snack)
            meta = {"object": a.object, "episode": k, "cell": p["cell"] if placed else "start", "snack_xy": snack, "grasp_z": gz,
                    "start": s, "current": a.current, "orientation_zyz": ORI}
            shared.update(phase="approach", cmd_open=1.0, cmd_cur=None); rec.start(ep)
            # 카메라로 봉지 자리를 기억해 둔다(팔이 시작 자세라 가리지 않음). 바구니로 옮긴 뒤 그 자리에 남았는지로 집었는지 판정.
            bag = None
            if a.basket and not AIR and getattr(rec, "latest", None) is not None:
                spin_for(0.3)
                bag = bag_region(rec.latest[1])
                print(f"    카메라: {OBJ_NAME} {'찾음 (면적 %dpx)' % bag[1] if bag else '못 찾음 -> 그리퍼 위치로만 판정'}", flush=True)
            move_high(snack[0], snack[1], PREGRASP_Z, V_APPROACH)
            shared["phase"] = "descend"; descend_to_grasp(snack[0], snack[1], gz)
            shared["phase"] = "close"; pos = close_gripper(a.current)
            meta["closed_pos"] = pos
            if pos <= GRIP_EMPTY and a.basket and bag is not None:
                # 봉지를 얇게 꼬집으면 빈손과 위치가 비슷하다. 바구니 모드는 내려가는 동작이 없으니 바구니까지 가서 카메라로 판정.
                print(f"    닫힘 위치 {pos:.0f} 는 빈손과 비슷 -> 멈추지 않고 바구니에서 카메라로 판정", flush=True)
            elif pos <= GRIP_EMPTY:
                n = rec.stop(); meta.update(success=False, frames=n, why="빈손")
                (ep / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                abort_up(f"ep{k}: 닫았는데 빈손(위치 {pos:.0f})", empty=True); raise Stop("빈손")
            if a.basket:
                bx, by = a.basket_xy
                shared["phase"] = "lift"
                if tcp()[2] < gz + LIFT_SLOW_DZ - 1: rise_to(gz + LIFT_SLOW_DZ, V_LIFT_SLOW)
                # 2026-10-16: z260 으로 경유점까지 낮게 전진하다 처진 봉지가 바구니 턱에 걸림.
                # 집은 자리에서 수직으로 옮기는 높이까지 먼저 다 올라간 뒤에만 바구니 쪽으로 간다.
                cur_l = tcp()
                lift_to = FAR_LIFT_Z if cur_l[0] > FAR_X else CARRY_Z
                if cur_l[2] < lift_to - 1: rise_to(lift_to)
                pos2 = grip(); meta["lifted_pos"] = pos2
                if pos2 <= GRIP_EMPTY and bag is not None:
                    print(f"    든 뒤 위치 {pos2:.0f} 는 빈손과 비슷 -> 바구니에서 카메라로 판정", flush=True)
                elif pos2 <= GRIP_EMPTY:
                    n = rec.stop(); meta.update(success=False, frames=n, why="들다가 놓침")
                    (ep / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                    abort_up(f"ep{k}: 들다가 놓침(위치 {pos2:.0f})", empty=True); raise Stop("놓침")
                shared["phase"] = "carry"
                carry_to_basket(bx, by)                                     # 먼 칸은 안쪽으로 당겨 온 뒤 올림
                cur = tcp()
                if math.dist(cur[:3], (bx, by, CARRY_Z)) > RELEASE_TOL_MM:
                    raise Stop(f"바구니 위 지점이 아님(x{cur[0]:.0f} y{cur[1]:.0f} z{cur[2]:.0f}) -> 열지 않음")
                pos3 = grip(); meta["carry_pos"] = pos3
                cam_missed = False
                if bag is not None:
                    spin_for(0.3)
                    frac = remaining_fraction(bag[0], bag[1], rec.latest[1]); meta["cam_remaining_frac"] = frac
                    cam_missed = frac > CAM_MISSED_FRAC
                    verdict = "들고 옴" if frac < CAM_HELD_FRAC else ("못 집음(봉지가 그 자리에 그대로)" if cam_missed else "애매")
                    print(f"    카메라: 원래 자리에 {OBJ_NAME} {frac:.2f} 남음 -> {verdict} (그리퍼 위치 {pos3:.0f})", flush=True)
                elif pos3 <= GRIP_EMPTY:
                    n = rec.stop(); meta.update(success=False, frames=n, why="옮기다 놓침")
                    (ep / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                    raise Stop(f"ep{k}: 옮기다 놓침(위치 {pos3:.0f}). {OBJ_NAME}(이) 어디 떨어졌는지 확인하세요")
                shared["phase"] = "release"; open_gripper(); spin_for(1.0)
                shared["phase"] = "retreat"; move_high(*RETREAT, V_TRAVEL)
                n = rec.stop(); meta["frames"] = n
                if cam_missed:
                    meta.update(success=False, why="카메라: 못 집음")
                    (ep / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                    raise Stop(f"ep{k}: 카메라상 {OBJ_NAME}(이) 원래 자리에 그대로 -> 못 집음. {OBJ_NAME} 위치를 확인하세요")
                ans = ask(f"[ep{k}] 바구니에 잘 들어갔나요? [Enter=예 / n=아니오]: ")
                meta.update(success=True, in_basket=(ans != "n"))
                (ep / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                holding = False; done += 1
                print(f"ep{k:02d} 완료  {OBJ_NAME} x{snack[0]:.0f} y{snack[1]:.0f}  닫힘 {pos:.0f} -> 든 뒤 {pos2:.0f} -> 옮긴 뒤 {pos3:.0f}"
                      f"  바구니 {'O' if meta['in_basket'] else 'X'}  프레임 {n}", flush=True)
                shared["phase"] = "idle"
                continue
            shared["phase"] = "lift"; rise_to(gz + LIFT_SLOW_DZ, V_LIFT_SLOW); rise_to(TRAVEL_Z)
            pos2 = grip(); meta["lifted_pos"] = pos2
            n = rec.stop(); meta["frames"] = n
            if pos2 <= GRIP_EMPTY:
                meta.update(success=False, why="들다가 놓침")
                (ep / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
                abort_up(f"ep{k}: 들다가 놓침(위치 {pos2:.0f})", empty=True); raise Stop("놓침")
            meta["success"] = True; holding = True; done += 1
            (ep / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
            print(f"ep{k:02d} 성공  {OBJ_NAME} x{snack[0]:.0f} y{snack[1]:.0f}  닫힘 {pos:.0f} -> 든 뒤 {pos2:.0f}  프레임 {n}", flush=True)
            shared["phase"] = "idle"
    except Stop as e:
        abort_up(str(e), empty=False)
        if rec.rec is not None: rec.stop()
    except (Exception, KeyboardInterrupt) as e:
        abort_up(repr(e), empty=False)
        if rec.rec is not None: rec.stop()
    finally:
        rec.close()
        print(f"\n완료 에피소드 {done}/{len(plan)}  물고 있음={holding}  결과: {run}")
        if holding: print(f"  {OBJ_NAME}을(를) 물고 공중에 있음. 다음 실행은 놓기부터 이어서 하거나 사람이 받아주세요.")
        try: grip_state(False)
        except Exception: pass
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
