#!/usr/bin/env python3
"""E0509 집기 디지털 트윈 (RViz). 로봇 자세는 드라이버의 TF/robot_description 그대로, 여기서는 환경과 물건·상태만 그린다.

입력  /dsr01/pick/event   std_msgs/String (JSON 한 줄). vla_run.py 가 보낸다. 예)
        {"event":"located","object":"choco","xy":[512,154]}      카메라로 찾은 물건 위치(mm, 로봇 기준)
        {"event":"grasped","object":"choco","closed_pos":208}    쥠 -> 물건이 그리퍼를 따라감
        {"event":"grasp_failed","object":"choco","xy":[...]}     빈손으로 닫힘
        {"event":"dropped","object":"choco","xyz":[...]}         운반 중 빠짐
        {"event":"released","object":"choco","xyz":[...]}        그리퍼 엶(바구니 안이면 적재, 밖이면 적재 실패)
        {"event":"reset"}                                        화면 초기화
출력  /dsr01/twin/markers MarkerArray (RViz),  /dsr01/twin/alert std_msgs/String (JSON, 관제용)
"""
import json, textwrap, math, time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import Point
from tf2_ros import Buffer, TransformListener
from sensor_msgs.msg import JointState, Image
from PIL import Image as PILImage, ImageDraw, ImageFont
import numpy as np

# RH-P12-RN(A) 공식 메시(ROBOTIS-GIT/RH-P12-RN-A, Apache-2.0)를 플랜지(link_6)에 붙여 그린다. 관절 위치는 공식 xacro 값.
MESH = "file:///home/omen/doosan_ws/vla_test/twin/rh_p12_rn_a/meshes/"
GRIP_YAW = math.pi / 2   # 플랜지에 붙은 그리퍼 회전(z축). 10-21 사용자 확인: 실물은 90도 돌아가 있음
def _rx(a):
    c, s_ = math.cos(a), math.sin(a); return np.array([[1, 0, 0, 0], [0, c, -s_, 0], [0, s_, c, 0], [0, 0, 0, 1.0]])
def _rz(a):
    c, s_ = math.cos(a), math.sin(a); return np.array([[c, -s_, 0, 0], [s_, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1.0]])
def _tr(x, y, z):
    m = np.eye(4); m[:3, 3] = (x, y, z); return m
def _quat(R):
    w = math.sqrt(max(0.0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    x = math.copysign(math.sqrt(max(0.0, 1 + R[0, 0] - R[1, 1] - R[2, 2])) / 2, R[2, 1] - R[1, 2])
    y = math.copysign(math.sqrt(max(0.0, 1 - R[0, 0] + R[1, 1] - R[2, 2])) / 2, R[0, 2] - R[2, 0])
    z = math.copysign(math.sqrt(max(0.0, 1 - R[0, 0] - R[1, 1] + R[2, 2])) / 2, R[1, 0] - R[0, 1])
    return x, y, z, w
def _tf_to_mat(t):
    q = t.rotation; x, y, z, w = q.x, q.y, q.z, q.w
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4); m[:3, :3] = R; m[:3, 3] = (t.translation.x, t.translation.y, t.translation.z); return m

FRAME = "base_link"
TABLE = dict(cx=0.50, cy=0.0, sx=0.46, sy=0.52, z=0.0)           # 작업대 윗면 z=0 (로봇 베이스 높이)
BASKET = dict(cx=0.35, cy=-0.50, sx=0.36, sy=0.26, h=0.30)       # 장바구니 (중심·크기는 대략, 실측 후 수정)
FINGER = 0.105                                                     # 플랜지 -> 손끝 (높이 확인 실측으로 추정)
# top: 쥐었을 때 물건 윗면이 손끝보다 얼마나 위인지(m). 실기: 초코송이 손끝이 책상 위 45mm(상자 85), 컵라면 윗면 25mm 아래를 잡음
OBJ = {"choco": dict(size=(0.035, 0.12, 0.085), color=(0.98, 0.82, 0.10), name="CHOCO", top=0.040),
       "shrimp": dict(size=(0.14, 0.20, 0.05), color=(0.90, 0.15, 0.10), name="SHRIMP", top=0.020),
       "ramen": dict(size=(0.10, 0.10, 0.11), color=(0.85, 0.30, 0.25), name="RAMEN", top=0.025)}
# 처음 놓아 둘 자리 (작업대 위, m). 세 물건을 늘 같이 보여 준다(10-21 사용자 요청)
PARK = {"choco": (0.40, 0.14), "shrimp": (0.56, 0.0), "ramen": (0.40, -0.14)}
EMPTY = {"choco": 150.0, "shrimp": 42.0, "ramen": 150.0}   # 이 값 이하로 닫히면 빈손 (vla_run 과 같게)
OBJ_MESH = "file:///home/omen/doosan_ws/vla_test/twin/meshes/"   # 2026-10-21 물건 3D 모델(.dae, 초코송이는 실제 사진 텍스처). gen_meshes.py / tex_box.py

def in_basket(x, y):
    return abs(x - BASKET["cx"]) <= BASKET["sx"] / 2 and abs(y - BASKET["cy"]) <= BASKET["sy"] / 2

# RViz 글자(TEXT 마커)는 영문만: 한글을 넣으면 rviz2 가 Ogre 'Vertex Buffer: Out of memory' 로 죽음(2026-10-21)
class Twin(Node):
    def __init__(self):
        super().__init__("pick_twin", namespace="dsr01")
        self.pub = self.create_publisher(MarkerArray, "twin/markers", 10)
        # RViz 3D 글자는 이 PC 에서 띄어쓰기 간격이 깨지고 한글이 안 나옴 -> 상태·경고·원인은 이미지 패널(twin/panel)로 그린다
        self.panel_pub = self.create_publisher(Image, "twin/panel", 1)
        self.head_ko = "대기 중"; self.bad = False; self.causes_ko = []
        F = "/usr/share/fonts/opentype/noto/NotoSansCJK-%s.ttc"
        self.f_big, self.f_small = ImageFont.truetype(F % "Bold", 34), ImageFont.truetype(F % "Regular", 30)
        self.f_warn = ImageFont.truetype(F % "Black", 72)
        self.create_timer(0.5, self.draw_panel)
        self.alert_pub = self.create_publisher(String, "twin/alert", 10)
        self.create_subscription(String, "pick/event", self.on_event, 10)
        self.grip = 750.0   # 서비스 기준 0=닫힘 750=열림
        self.create_subscription(JointState, "gripper/state", lambda m: setattr(self, "grip", float(m.position[0])) if m.position else None, 10)
        self.tf = Buffer(); TransformListener(self.tf, self)
        self.parked = {o: [x, y, TABLE["z"]] for o, (x, y) in PARK.items()}   # 지금 다루지 않는 물건들의 마지막 자리
        self.obj = "choco"; self.pos = list(self.parked["choco"]); self.held = False; self.in_basket = False
        self.status = "IDLE"; self.alert = None; self.alert_t = 0.0; self.history = []; self.causes = []; self.miss = {}; self.seen_once = set()
        self.create_timer(0.1, self.draw)

    # ---- 이벤트 ----
    def on_event(self, msg):
        try: e = json.loads(msg.data)
        except Exception: self.get_logger().warn(f"이벤트 해석 실패: {msg.data}"); return
        k = e.get("event"); new = e.get("object") if e.get("object") in OBJ else self.obj
        if new != self.obj:   # 다른 물건으로 넘어감: 지금 물건은 그 자리에 두고(쥐고 있지 않으면), 새 물건은 마지막 자리에서 시작
            if self.pos is not None and not self.held: self.parked[self.obj] = list(self.pos)
            self.obj = new; p0 = self.parked.get(new); self.pos = list(p0) if p0 else None; self.held = False; self.in_basket = False
        name = OBJ[self.obj]["name"]
        if k == "reset":
            self.parked = {o: [x, y, TABLE["z"]] for o, (x, y) in PARK.items()}; self.pos = list(self.parked[self.obj])
            self.held = False; self.in_basket = False; self.status = "IDLE"; self.alert = None; self.causes = []; self.history = []
        elif k == "located":
            x, y = [v / 1000.0 for v in e["xy"]]; self.pos = [x, y, TABLE["z"]]; self.held = False; self.in_basket = False
            self.status = f"{name} located x{e['xy'][0]:.0f} y{e['xy'][1]:.0f}"; self.alert = None; self.causes = []
        elif k == "retry":   # pick_loop.py: 시도 시작 (2번째부터는 재시도)
            self.history = list(e.get("history", [])); n_, t_ = e.get("attempt", 1), e.get("tries", 1)
            self.alert = None; self.bad = False; self.causes = []; self.held = False
            self.status = f"ATTEMPT {n_}/{t_}: locating {name}" if n_ == 1 else f"RETRY {n_}/{t_}: re-locating {name}"
            self.publish_alert("retry", f"{name} attempt {n_}/{t_}", e)
        elif k == "done":
            self.history = list(e.get("history", [])); self.alert = None; self.bad = False
            self.status = f"{name} LOADED on attempt {e.get('attempt', 1)}"
        elif k == "gave_up":
            self.history = list(e.get("history", [])); self.bad = True
            self.raise_alert("GAVE UP", f"{name} failed {e.get('attempt', 0)} times, operator needed", e)
        elif k == "loop_end":
            self.history = list(e.get("history", [])); self.bad = True
            self.raise_alert("STOPPED", f"{name} retry loop stopped ({e.get('reason', '?')}), check terminal", e)
        elif k == "seen":   # 10-22: 주문 서버가 쉬는 동안 카메라로 본 작업대 위 물건들 (트윈을 실제에 맞춤)
            for o, xy in e.get("objects", {}).items():
                if o not in OBJ or (o == self.obj and self.held): continue
                cur = self.pos if o == self.obj else self.parked.get(o)
                if xy:
                    self.miss[o] = 0; pnew = [xy[0] / 1000.0, xy[1] / 1000.0, TABLE["z"]]
                    self.seen_once.add(o)
                else:
                    self.miss[o] = self.miss.get(o, 0) + 1
                    if cur is not None and in_basket(cur[0], cur[1]): continue      # 바구니 안은 카메라로 못 봄 -> 그대로
                    if cur is not None and o in self.seen_once and self.arm_near(cur):   # 10-22: 켤 때 기본 자리(PARK)는 시작 자세 팔 근처라 영영 안 지워짐 -> 카메라로 본 적 있는 자리만
                         self.miss[o] = 0; continue   # 10-22: 멈춘 팔이 위에서 가림 -> 지우지 않음
                    if self.miss[o] < 3: continue                                     # 세 번 연속 안 보이면 작업대에서 지움
                    pnew = None
                if o == self.obj: self.pos = pnew; self.in_basket = False
                else: self.parked[o] = pnew
            return
        elif k == "analysis":
            # vla_run 이 failure_analysis.py 로 낸 원인. RViz 는 한글 글꼴이 없어 영문, 관제(twin/alert)로는 한글
            self.causes = list(e.get("en", [])) if e.get("outcome") != "loaded" else []
            if e.get("ko"): self.publish_alert("analysis", " / ".join(e["ko"]), e)
            self.causes_ko = list(e.get("ko", [])) if e.get("outcome") != "loaded" else []
        elif k == "grasped":
            self.held = True; self.status = f"{name} GRASPED (gripper {e.get('closed_pos', 0):.0f}) - carrying"
        elif k == "grasp_failed":
            self.held = False; self.raise_alert("GRASP FAILED", f"{name}: closed empty, retreated up", e)
        elif k == "dropped":
            self.held = False
            x, y, _ = [v / 1000.0 for v in e["xyz"]]
            self.pos = [x, y, TABLE["z"]] if not in_basket(x, y) else [x, y, TABLE["z"]]
            self.raise_alert("DROP DETECTED", f"{name} slipped out while carrying (x{e['xyz'][0]:.0f} y{e['xyz'][1]:.0f})", e)
        elif k == "not_found":
            self.pos = None; self.held = False
            self.raise_alert("NOT FOUND", f"camera found no {name} on the table", e)
        elif k == "not_in_basket":
            x, y = [v / 1000.0 for v in e["xy"]]; self.pos = [x, y, TABLE["z"]]; self.held = False; self.in_basket = False
            self.raise_alert("LOAD FAILED", f"{name} still on table after release (x{e['xy'][0]:.0f} y{e['xy'][1]:.0f})", e)
        elif k == "loaded":
            if self.alert is None: self.status = f"{name} LOADED (camera: table clear)"
            self.publish_alert("loaded", f"{name} loaded, table clear", e)
        elif k == "released":
            self.held = False
            x, y, _ = [v / 1000.0 for v in e["xyz"]]
            if in_basket(x, y):
                self.pos = [x, y, TABLE["z"]]; self.in_basket = True; self.status = f"{name} LOADED in basket"; self.alert = None
                pass
            else:
                self.pos = [x, y, TABLE["z"]]; self.in_basket = False
                self.raise_alert("LOAD FAILED", f"{name} released outside basket (x{e['xyz'][0]:.0f} y{e['xyz'][1]:.0f})", e)
        self.set_head_ko(k, e)
        self.get_logger().info(f"[{k}] {self.status if not self.alert else self.alert}")

    def set_head_ko(self, k, e):
        n = {"choco": "초코송이", "shrimp": "새우깡", "ramen": "컵라면"}.get(self.obj, self.obj)
        jg, jr = ("이", "을") if self.obj == "shrimp" else ("가", "를")   # 조사: 새우깡이/을, 초코송이가/를
        xy = lambda key: f"x{e[key][0]:.0f} y{e[key][1]:.0f}" if key in e else ""
        if k in ("reset", "located"): self.causes_ko = []
        rel_ok = k == "released" and self.in_basket
        t = {"reset": ("대기 중", False), "located": (f"{n} 위치 확인 {xy('xy')}", False),
             "grasped": (f"{n} 잡음 (그리퍼 {e.get('closed_pos', 0):.0f}) - 운반 중", False),
             "grasp_failed": (f"잡기 실패: {n}{jr} 못 물고 빈손으로 닫힘 -> 위로 빠져 멈춤", True),
             "dropped": (f"떨어뜨림 감지: 운반 중 {n}{jg} 빠짐 ({xy('xyz')})", True),
             "not_found": (f"작업대에서 {n}{jr} 못 찾음", True),
             "not_in_basket": (f"적재 실패: 놓은 뒤에도 {n}{jg} 작업대 위에 있음 ({xy('xy')})", True),
             "loaded": (f"적재 완료: {n} 바구니에 들어감 (작업대 비어 있음)", False),
             "released": ((f"{n} 바구니 위에서 놓음", False) if rel_ok else (f"적재 실패: 바구니 밖에서 놓음 ({xy('xyz')})", True))}.get(k)
        if t and not (k == "loaded" and self.bad): self.head_ko, self.bad = t

    def draw_panel(self):
        # RViz 왼쪽 칸(좁고 김)에 맞춰 세로로 긴 그림. 화면은 영문(사용자 요청 10-21), 관제(twin/alert)는 한글 그대로
        W = 520; lines = []
        if self.bad:
            lines.append(("WARNING", self.f_warn, (255, 255, 255), 84))
            head = (self.alert or self.status).replace("!! ", "", 1)
        else:
            head = self.status
        for ln in textwrap.wrap(head, 24): lines.append((ln, self.f_big, (255, 255, 255), 44))
        head_h = 16 + sum(l[3] for l in lines)
        if self.causes:
            lines.append(("", self.f_small, (0, 0, 0), 10)); lines.append(("CAUSE ANALYSIS", self.f_big, (255, 210, 60), 46))
            for c in self.causes:
                for k, ln in enumerate(textwrap.wrap(c, 30)): lines.append((("- " if k == 0 else "  ") + ln, self.f_small, (240, 240, 240), 38))
        if self.history:   # 이전 시도들 (pick_loop.py)
            lines.append(("", self.f_small, (0, 0, 0), 10)); lines.append(("ATTEMPTS", self.f_big, (140, 190, 255), 46))
            for h in self.history:
                for k, ln in enumerate(textwrap.wrap(h, 30)): lines.append((("" if k == 0 else "  ") + ln, self.f_small, (210, 210, 220), 38))
        lines.append(("", self.f_small, (0, 0, 0), 14)); lines.append((f"gripper {self.grip:.0f} (0 closed, 750 open)", self.f_small, (150, 150, 160), 38))
        H = 16 + sum(l[3] for l in lines); im = PILImage.new("RGB", (W, H), (30, 30, 34)); d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, head_h], fill=(170, 25, 25) if self.bad else (35, 110, 60))
        y = 8
        for t, f, c, h in lines: d.text((14, y), t, font=f, fill=c); y += h
        m = Image(); m.header.stamp = self.get_clock().now().to_msg(); m.header.frame_id = FRAME
        m.height, m.width, m.encoding, m.step = H, W, "rgb8", W * 3; m.data = im.tobytes(); self.panel_pub.publish(m)

    def arm_near(self, pos, r=0.15):
        """그리퍼(link_6)가 이 물건 자리 위 r(m) 안에 있나 -> 위 카메라에서 물건을 가림"""
        try:
            t = self.tf.lookup_transform(FRAME, "link_6", rclpy.time.Time()).transform.translation
            return math.hypot(t.x - pos[0], t.y - pos[1]) < r
        except Exception: return False

    def raise_alert(self, title, text, e):
        self.alert = f"!! {title}: {text}"; self.alert_t = time.monotonic(); self.status = title
        self.publish_alert(title, text, e)

    def publish_alert(self, kind, text, e):
        m = String(); m.data = json.dumps({"t": time.time(), "kind": kind, "text": text, "event": e}, ensure_ascii=False)
        self.alert_pub.publish(m)

    # ---- 그리기 ----
    def mk(self, mid, typ, ns="twin"):
        m = Marker(); m.header.frame_id = FRAME; m.header.stamp = self.get_clock().now().to_msg()
        m.ns = ns; m.id = mid; m.type = typ; m.action = Marker.ADD; m.pose.orientation.w = 1.0; return m

    def box(self, mid, cx, cy, cz, sx, sy, sz, rgba, ns="twin"):
        m = self.mk(mid, Marker.CUBE, ns); m.pose.position.x, m.pose.position.y, m.pose.position.z = cx, cy, cz
        m.scale.x, m.scale.y, m.scale.z = sx, sy, sz; m.color.r, m.color.g, m.color.b, m.color.a = [float(v) for v in rgba]; return m

    def text(self, mid, x, y, z, s, rgba, size=0.04):
        m = self.mk(mid, Marker.TEXT_VIEW_FACING); m.pose.position.x, m.pose.position.y, m.pose.position.z = x, y, z
        s = "\n".join(textwrap.fill(ln, 34) for ln in s.split("\n"))   # 긴 줄은 화면 밖으로 잘려서 줄바꿈
        m.scale.z = size; m.text = s; m.color.r, m.color.g, m.color.b, m.color.a = [float(v) for v in rgba]; return m

    def draw(self):
        arr = MarkerArray(); T, B = TABLE, BASKET
        arr.markers.append(self.box(0, T["cx"], T["cy"], T["z"] - 0.01, T["sx"], T["sy"], 0.02, (0.85, 0.85, 0.88, 1.0)))
        t, h = 0.006, B["h"]; bz = T["z"] + h / 2; c = (0.95, 0.95, 0.95, 0.35)
        for i, (dx, dy, sx, sy) in enumerate([(B["sx"] / 2, 0, t, B["sy"]), (-B["sx"] / 2, 0, t, B["sy"]),
                                               (0, B["sy"] / 2, B["sx"], t), (0, -B["sy"] / 2, B["sx"], t)]):
            arr.markers.append(self.box(10 + i, B["cx"] + dx, B["cy"] + dy, bz, sx, sy, h, c))
        arr.markers.append(self.box(14, B["cx"], B["cy"], T["z"] + 0.003, B["sx"], B["sy"], 0.006, c))
        # 10-22: 이벤트를 안 보내는 프로그램(수집 등)도 따라가게, 그리퍼 값과 손 높이로 집기/놓기를 스스로 판단
        try:
            t6 = self.tf.lookup_transform(FRAME, "link_6", rclpy.time.Time()).transform.translation
            g = self.grip; low = (t6.z - FINGER) < 0.20   # 손끝이 작업대 위 20cm 안
            if not self.held and low and EMPTY.get(self.obj, 150.0) < g < 700.0:
                self.held = True; self.in_basket = False
            elif self.held and g >= 700.0:
                x, y = float(t6.x), float(t6.y); self.held = False
                self.pos = [x, y, TABLE["z"]]; self.in_basket = in_basket(x, y)
        except Exception: pass
        # 물건 3개를 늘 같이 그린다: 지금 다루는 물건(self.obj)은 로봇·이벤트를 따라가고, 나머지는 마지막 자리(self.parked)
        for idx, name in enumerate(OBJ):
            o = OBJ[name]; sx, sy, sz = o["size"]
            if name == self.obj:
                if self.held:
                    try:
                        tr = self.tf.lookup_transform(FRAME, "link_6", rclpy.time.Time()).transform.translation
                        self.pos = [tr.x, tr.y, tr.z - FINGER + o.get("top", 0.02) - sz / 2]
                    except Exception: pass
                pos, held = self.pos, self.held
            else:
                pos, held = self.parked.get(name), False
            if pos is not None:
                z = pos[2] if held else pos[2] + sz / 2
                m = self.mk(20 + idx, Marker.MESH_RESOURCE, "object"); m.mesh_resource = OBJ_MESH + name + ".dae"
                m.mesh_use_embedded_materials = True; m.color.r = m.color.g = m.color.b = m.color.a = 0.0   # 모델 안의 색·사진을 그대로
                m.pose.position.x, m.pose.position.y, m.pose.position.z = float(pos[0]), float(pos[1]), float(z)
                m.scale.x = m.scale.y = m.scale.z = 1.0; arr.markers.append(m)
            else:
                d = self.mk(20 + idx, Marker.MESH_RESOURCE, "object"); d.action = Marker.DELETE; arr.markers.append(d)
        d = self.mk(20, Marker.CUBE); d.action = Marker.DELETE; arr.markers.append(d)   # 예전 상자 지우기
        try:
            T6 = _tf_to_mat(self.tf.lookup_transform(FRAME, "link_6", rclpy.time.Time()).transform)
            th = max(0.0, min(1.1, (750.0 - self.grip) / 740.0 * 1.1))   # 하드웨어 위치(=750-서비스값) 0~740 -> 손가락 0~1.1rad
            Tb = T6 @ _rz(GRIP_YAW)
            Tr1 = Tb @ _tr(0, 0.008, 0.048) @ _rx(th);  Tr2 = Tr1 @ _tr(0, 0.0493634, 0.0285) @ _rx(-th)
            Tl1 = Tb @ _tr(0, -0.008, 0.048) @ _rx(-th); Tl2 = Tl1 @ _tr(0, -0.0493634, 0.0285) @ _rx(th)
            for k, (T, f) in enumerate([(Tb, "base.stl"), (Tr1, "r1.stl"), (Tr2, "r2.stl"), (Tl1, "l1.stl"), (Tl2, "l2.stl")]):
                m = self.mk(40 + k, Marker.MESH_RESOURCE, "gripper"); m.mesh_resource = MESH + f
                m.pose.position.x, m.pose.position.y, m.pose.position.z = [float(v) for v in T[:3, 3]]
                qx, qy, qz, qw = _quat(T[:3, :3]); m.pose.orientation.x, m.pose.orientation.y, m.pose.orientation.z, m.pose.orientation.w = qx, qy, qz, qw
                m.scale.x = m.scale.y = m.scale.z = 0.001; m.color.r = m.color.g = m.color.b = 0.25; m.color.a = 1.0
                arr.markers.append(m)
        except Exception as ex:
            pass
        alert_on = self.alert and (time.monotonic() - self.alert_t) % 1.0 < 0.7
        if False:
            arr.markers.append(self.text(31, 0.45, -0.15, 0.72, self.alert, (1.0, 0.15, 0.15, 1.0), 0.06))
        else:   # 빈 글자(" ") TEXT 마커는 rviz2 를 죽인다(Ogre Vertex Buffer out of memory) -> 지운다
            d = self.mk(31, Marker.TEXT_VIEW_FACING); d.action = Marker.DELETE; arr.markers.append(d)
        for mid in (30, 32):
            d = self.mk(mid, Marker.TEXT_VIEW_FACING); d.action = Marker.DELETE; arr.markers.append(d)
        if False:
            arr.markers.append(self.text(32, 0.45, -0.15, 0.50, "CAUSE:\n" + "\n".join("- " + c for c in self.causes), (1.0, 0.85, 0.2, 1.0), 0.035))
        else:
            pass
        self.pub.publish(arr)

def main():
    rclpy.init(); n = Twin()
    try: rclpy.spin(n)
    except KeyboardInterrupt: pass
    finally: rclpy.shutdown()

if __name__ == "__main__":
    main()
