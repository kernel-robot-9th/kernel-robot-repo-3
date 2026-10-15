"""Project-level state machine. No vendor ROS names or physical robot claims."""
from copy import deepcopy
from functools import wraps
import hashlib
import hmac
import json
import math
import secrets
import threading
import time
import uuid

from .store import Store

PRODUCTS = [
    {"sku": "DEMO-APPLE", "name": "모의 사과", "station": "load-a"},
    {"sku": "DEMO-JUICE", "name": "모의 주스", "station": "load-a"},
    {"sku": "DEMO-SNACK", "name": "모의 과자", "station": "load-b"},
]
STATIONS = {"load-a": "omx-a", "load-b": "omx-b", "handoff": "omx-handoff"}
TERMINAL = {"SUCCEEDED", "FAILED", "UNCERTAIN", "CANCELLED"}


class DomainError(Exception):
    def __init__(self, message, status=409):
        self.message, self.status = message, status
        super().__init__(message)


def require(condition, message, status=409):
    if not condition:
        raise DomainError(message, status)


def uid():
    return str(uuid.uuid4())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def atomic(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.lock:
            before = deepcopy(self.state)
            self.records = []
            try:
                result = method(self, *args, **kwargs)
                self._pump()
                self._invariants()
                self.store.save(self.state, self.records)
                return result
            except DomainError as exc:
                self.state = before
                self.records = []
                self._log("request_rejected", {"operation": method.__name__, "reason": exc.message})
                self.store.save(self.state, self.records)
                raise
            except Exception:
                self.state = before
                raise
            finally:
                self.records = []
    return wrapped


class Engine:
    # These are mock development limits, NOT measured physical tolerances.
    capacity = 6
    observation_ttl = 300
    command_timeout = 120
    heartbeat_timeout = 10

    def __init__(self, path=":memory:", clock=time.time):
        self.clock, self.lock, self.records = clock, threading.RLock(), []
        self.store = Store(path)
        stored = self.store.load()
        self.state = stored or self._fresh()
        if stored:
            self._recover()
        self.store.save(self.state, self.records)
        self.records = []

    def _fresh(self):
        return {
            "run_id": uid(), "mode": "mock", "sessions": {}, "orders": {}, "tasks": {},
            "commands": {}, "results": {}, "gateway_id": None, "heartbeat_at": None,
            "permits": 0, "pick_failures": [], "basket": None,
            "devices": {name: {"connected": False, "forced_offline": False}
                        for name in ["pinky-1", "pinky-2", *STATIONS.values()]},
            "robots": {name: {"session_id": None} for name in ["pinky-1", "pinky-2"]},
            "zones": {name: {"owner": None, "queue": []} for name in STATIONS},
        }

    def _log(self, kind, detail=None, task=None, command=None, session_id=None):
        if command:
            task = self.state["tasks"][command["task_id"]]
        self.records.append({"at": self.clock(), "kind": kind, "detail": detail or {},
                             "session_id": task["session_id"] if task else session_id,
                             "task_id": task["id"] if task else None,
                             "command_id": command["id"] if command else None})

    def _recover(self):
        self.state["gateway_id"] = None
        self.state["heartbeat_at"] = None
        self.state["basket"] = None
        self.state["permits"] = 0
        for device in self.state["devices"].values():
            device["connected"] = False
        for cmd in self.state["commands"].values():
            if cmd["status"] not in TERMINAL:
                cmd["status"] = "UNCERTAIN"
        for session in self.state["sessions"].values():
            if session["current_task"]:
                task = self.state["tasks"][session["current_task"]]
                task["state"] = "RECOVERY_REQUIRED"
                session["error"] = "서버 재시작: 장비·상품·구역 상태 확인 필요"
                if session["state"] != "COMPLETED":
                    session["state"] = "RECOVERY_REQUIRED"
        self._log("server_restarted", {"policy": "retain zones; no automatic replay"})

    def _session(self, session_id):
        require(session_id in self.state["sessions"], "쇼핑 세션을 찾을 수 없습니다", 404)
        return self.state["sessions"][session_id]

    @atomic
    def create_session(self, label):
        require(isinstance(label, str) and 1 <= len(label.strip()) <= 40, "고객 이름은 1~40자입니다", 422)
        available = next((rid for rid, robot in self.state["robots"].items()
                          if robot["session_id"] is None), None)
        require(available, "사용 가능한 로봇이 없습니다. 기존 고객 인계·이탈 후 다시 시작하세요")
        sid, token = uid(), secrets.token_urlsafe(32)
        session = {"id": sid, "label": label.strip(), "robot_id": available, "basket_id": "basket-" + sid,
                   "token_hash": hashlib.sha256(token.encode()).hexdigest(), "state": "SHOPPING",
                   "checkout_requested": False, "current_task": None, "inventory": [],
                   "error": None, "created_at": self.clock(), "completed_at": None}
        self.state["sessions"][sid] = session
        self.state["robots"][available]["session_id"] = sid
        self._log("session_started", {"robot_id": available}, session_id=sid)
        return {"session_id": sid, "token": token, "robot_id": available}

    def authenticate_customer(self, token):
        hashed = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            for session in self.state["sessions"].values():
                if hmac.compare_digest(session["token_hash"], hashed):
                    return session["id"]
        raise DomainError("고객 세션 인증이 필요합니다", 401)

    def _task(self, session, kind, zone, items, order_id=None):
        tid = uid()
        task = {"id": tid, "session_id": session["id"], "robot_id": session["robot_id"],
                "kind": kind, "zone_id": zone, "device_id": STATIONS[zone], "items": items,
                "order_id": order_id, "state": "QUEUED", "stopped_at": None,
                "arm_clear": False, "created_at": self.clock()}
        self.state["tasks"][tid] = task
        self._log("task_created", {"kind": kind, "zone_id": zone, "items": items}, task=task)
        return task

    @atomic
    def submit_order(self, sid, items, request_id):
        session = self._session(sid)
        normalized = {}
        for item in items:
            sku, qty = item.get("sku"), item.get("quantity")
            require(sku in {p["sku"] for p in PRODUCTS} and type(qty) is int and 1 <= qty <= self.capacity,
                    "지원 상품과 허용 수량을 확인하세요", 422)
            normalized[sku] = normalized.get(sku, 0) + qty
        require(normalized, "한 개 이상의 상품이 필요합니다", 422)
        for order in self.state["orders"].values():
            if order["session_id"] == sid and order["request_id"] == request_id:
                require(order["items"] == normalized, "같은 요청 ID의 주문 내용이 다릅니다")
                return deepcopy(order)
        require(not session["checkout_requested"] and session["state"] == "SHOPPING" and not session["error"],
                "지금은 추가 주문을 받을 수 없습니다")
        used = sum(sum(o["items"].values()) for o in self.state["orders"].values() if o["session_id"] == sid)
        require(used + sum(normalized.values()) <= self.capacity, "모의 바구니 최대 6개를 초과했습니다")
        order = {"id": uid(), "session_id": sid, "request_id": request_id,
                 "items": normalized, "created_at": self.clock()}
        self.state["orders"][order["id"]] = order
        for sku, qty in normalized.items():
            product = next(p for p in PRODUCTS if p["sku"] == sku)
            task_items = [{"sku": sku, "slot": used + i} for i in range(qty)]
            used += qty
            self._task(session, "LOAD", product["station"], task_items, order["id"])
        self._log("order_received", {"order_id": order["id"], "items": normalized}, session_id=sid)
        return deepcopy(order)

    @atomic
    def checkout(self, sid):
        session = self._session(sid)
        if session["checkout_requested"]:
            return {"checkout_requested": True}
        require(not session["error"] and session["state"] == "SHOPPING", "오류를 먼저 확인하세요")
        require(any(o["session_id"] == sid for o in self.state["orders"].values()), "주문 후 인계를 요청하세요")
        session["checkout_requested"] = True
        session["state"] = "CHECKOUT_REQUESTED"
        self._log("checkout_requested", session_id=sid)
        return {"checkout_requested": True}

    def _command(self, task, kind, device_id):
        cmd = {"id": uid(), "run_id": self.state["run_id"], "task_id": task["id"],
               "session_id": task["session_id"], "robot_id": task["robot_id"], "device_id": device_id,
               "mode": "mock", "kind": kind, "zone_id": task["zone_id"], "items": deepcopy(task["items"]),
               "status": "CREATED", "created_at": self.clock(), "sent_at": None,
               "accepted_at": None, "result": None}
        if kind == "HANDOFF":
            cmd["basket_id"] = self.state["basket"]["basket_id"]
        self.state["commands"][cmd["id"]] = cmd
        self._log("command_created", {"kind": kind, "device_id": device_id}, command=cmd)
        return cmd

    def _fresh_observation(self, at):
        return at is not None and -2 <= self.clock() - at <= self.observation_ttl

    def _ready(self, task):
        basket = self.state["basket"]
        return bool(basket and basket["session_id"] == task["session_id"]
                    and basket["task_id"] == task["id"] and self._fresh_observation(basket["at"]))

    def _pump(self):
        for session in self.state["sessions"].values():
            if session["error"] or session["state"] == "COMPLETED":
                continue
            if session["current_task"] is None:
                task = next((t for t in self.state["tasks"].values()
                             if t["session_id"] == session["id"] and t["state"] == "QUEUED"), None)
                if task is None and session["checkout_requested"]:
                    outstanding = [i for i in session["inventory"] if not i["delivered"]]
                    if outstanding:
                        task = self._task(session, "HANDOFF", "handoff",
                                          [{"sku": i["sku"], "slot": i["slot"]} for i in outstanding])
                        session["state"] = "DELIVERING"
                if task:
                    session["current_task"] = task["id"]
                    task["state"] = "WAIT_ZONE"
                    self.state["zones"][task["zone_id"]]["queue"].append(task["id"])
            if session["current_task"]:
                task = self.state["tasks"][session["current_task"]]
                if task["state"] in {"WAIT_STOP", "WAIT_BASKET"} and self._fresh_observation(task["stopped_at"]):
                    if task["kind"] == "HANDOFF" and not self._ready(task):
                        task["state"] = "WAIT_BASKET"
                    elif self.state["devices"][task["device_id"]]["connected"]:
                        task["state"] = "ARM_WORK"
                        self._command(task, "PICK" if task["kind"] == "LOAD" else "HANDOFF", task["device_id"])
        for zone_id, zone in self.state["zones"].items():
            if zone["owner"] or not zone["queue"]:
                continue
            task = self.state["tasks"][zone["queue"][0]]
            session = self._session(task["session_id"])
            if session["error"]:
                continue
            if not all(self.state["devices"][d]["connected"] for d in [task["robot_id"], task["device_id"]]):
                continue
            zone["owner"] = zone["queue"].pop(0)
            task["state"] = "MOVING"
            self._command(task, "NAVIGATE", task["robot_id"])
            self._log("zone_reserved", {"zone_id": zone_id}, task=task)

    def _fault(self, task, reason):
        session = self._session(task["session_id"])
        if session["error"]:
            return
        session["error"] = reason
        if session["state"] != "COMPLETED":
            session["state"] = "ERROR"
        task["state"] = "ERROR"
        for cmd in list(self.state["commands"].values()):
            if cmd["task_id"] == task["id"] and cmd["status"] not in TERMINAL:
                cmd["status"] = "CANCELLED" if cmd["status"] == "CREATED" else "UNCERTAIN"
        for device_id in [task["robot_id"], task["device_id"]]:
            self._command(task, "STOP", device_id)
        self._log("work_fault", {"reason": reason, "zone_retained": True,
                                 "physical_stop_confirmed": False}, task=task)

    @atomic
    def heartbeat(self, gateway_id):
        old = self.state["gateway_id"]
        if old and old != gateway_id:
            for session in self.state["sessions"].values():
                if session["current_task"]:
                    self._fault(self.state["tasks"][session["current_task"]], "연결 프로그램 재시작: 상태 확인 필요")
        self.state["gateway_id"] = gateway_id
        self.state["heartbeat_at"] = self.clock()
        for device in self.state["devices"].values():
            device["connected"] = not device["forced_offline"]
        if old != gateway_id:
            self._log("gateway_connected", {"gateway_id": gateway_id})
        return {"run_id": self.state["run_id"], "mode": "mock"}

    def _validate_gateway(self, gateway_id):
        require(gateway_id == self.state["gateway_id"] and self._fresh_gateway(), "현재 연결 프로그램 인증 상태가 아닙니다")

    @atomic
    def claim(self, gateway_id, device_ids=None):
        self._validate_gateway(gateway_id)
        for cmd in sorted(self.state["commands"].values(), key=lambda c: c["kind"] != "STOP"):
            if device_ids is not None and cmd["device_id"] not in device_ids:
                continue
            if cmd["status"] != "CREATED" or not self.state["devices"][cmd["device_id"]]["connected"]:
                continue
            task = self.state["tasks"][cmd["task_id"]]
            if cmd["kind"] != "STOP":
                require(not self._session(cmd["session_id"])["error"], "중단된 작업입니다")
                require(self.state["zones"][cmd["zone_id"]]["owner"] == cmd["task_id"], "구역 사용 권한 없음")
                if cmd["kind"] in {"PICK", "HANDOFF"}:
                    if not self._fresh_observation(task["stopped_at"]) or (cmd["kind"] == "HANDOFF" and not self._ready(task)):
                        self._fault(task, "장비 실행 전 정차 또는 장바구니 관측 만료")
                        return None
                if cmd["kind"] == "LEAVE":
                    require(task["arm_clear"], "팔 이탈 미확인")
            cmd["status"], cmd["sent_at"] = "SENT", self.clock()
            self._log("command_sent", {"gateway_id": gateway_id}, command=cmd)
            return deepcopy(cmd)
        return None

    def _fresh_gateway(self):
        at = self.state["heartbeat_at"]
        return at is not None and 0 <= self.clock() - at <= self.heartbeat_timeout

    @atomic
    def event(self, event):
        require(event["run_id"] == self.state["run_id"] and event["mode"] == "mock", "실행 또는 연결 모드 불일치")
        require(event["command_id"] in self.state["commands"], "알 수 없는 명령", 404)
        cmd = self.state["commands"][event["command_id"]]
        for field in ["task_id", "session_id", "device_id"]:
            require(event[field] == cmd[field], f"결과의 {field} 불일치")
        key, fingerprint = event["event_id"], digest(event)
        if key in self.state["results"]:
            require(self.state["results"][key] == fingerprint, "같은 이벤트 ID의 내용이 다릅니다")
            return {"duplicate": True}
        kind, data = event["kind"], event["data"]
        task = self.state["tasks"][cmd["task_id"]]
        session = self._session(cmd["session_id"])
        result = {"kind": kind, "data": data}
        if kind in {"SUCCEEDED", "FAILED"} and cmd["result"]:
            require(cmd["result"] == result, "이미 확정된 결과와 충돌합니다")
            self.state["results"][key] = fingerprint
            self._log("duplicate_result", command=cmd)
            return {"duplicate": True}
        require(cmd["status"] not in {"UNCERTAIN", "CANCELLED"}, "중단·불명 명령의 결과는 자동 반영하지 않습니다")
        require(not session["error"] or cmd["kind"] == "STOP", "오류 작업의 후속 결과는 상태 확인이 필요합니다")
        require(self._fresh_gateway() and self.state["devices"][cmd["device_id"]]["connected"], "연결 상태 미확인")
        require(session["current_task"] == task["id"], "현재 작업의 관측이 아닙니다")
        if kind in {"ACCEPTED", "SUCCEEDED", "FAILED"} and cmd["kind"] != "STOP":
            require(cmd["sent_at"] is not None and self.clock() - cmd["sent_at"] <= self.command_timeout,
                    "명령 결과 수신 기한이 지났습니다. 상태 확인이 필요합니다")
        if kind in {"STOPPED", "ARM_CLEAR", "EXITED"}:
            at = event.get("observed_at")
            require(type(at) in {float, int} and math.isfinite(at) and self._fresh_observation(at),
                    "오래됐거나 미래 시각인 관측입니다", 422)
        if kind == "ACCEPTED":
            require(cmd["status"] in {"SENT", "ACCEPTED"}, "전송 후에만 수락할 수 있습니다")
            cmd["status"], cmd["accepted_at"] = "ACCEPTED", self.clock()
        elif kind in {"SUCCEEDED", "FAILED"}:
            require(cmd["status"] == "ACCEPTED", "명령 수락 전에 결과를 확정할 수 없습니다")
            if cmd["kind"] in {"PICK", "HANDOFF"}:
                confirmed = data.get("confirmed_items", [])
                require(isinstance(confirmed, list), "확인 상품 형식 오류", 422)
                require(all(isinstance(i, dict) and isinstance(i.get("sku"), str)
                            and type(i.get("slot")) is int and set(i) == {"sku", "slot"}
                            for i in confirmed), "확인 상품 형식 오류", 422)
                canonical = [(i["sku"], i["slot"]) for i in confirmed]
                expected = {(i["sku"], i["slot"]) for i in cmd["items"]}
                require(len(canonical) == len(confirmed) and len(set(canonical)) == len(canonical)
                        and all(type(i.get("slot")) is int for i in confirmed)
                        and set(canonical).issubset(expected), "확인 상품·슬롯이 명령과 다릅니다")
                if cmd["kind"] == "HANDOFF":
                    require(data.get("basket_id") == cmd["basket_id"], "다른 고객 장바구니의 인계 결과입니다")
                require(kind != "SUCCEEDED" or set(canonical) == expected, "일부 상품만 확인된 결과는 전체 성공이 아닙니다")
                for sku, slot in canonical:
                    if cmd["kind"] == "PICK":
                        require(not any(i["slot"] == slot for i in session["inventory"]), "이미 적재된 슬롯")
                        session["inventory"].append({"sku": sku, "slot": slot, "delivered": False,
                                                     "load_command_id": cmd["id"], "handoff_command_id": None})
                    else:
                        item = next((i for i in session["inventory"] if i["slot"] == slot and i["sku"] == sku), None)
                        require(item and not item["delivered"], "인계할 상품을 확인할 수 없습니다")
                        item["delivered"], item["handoff_command_id"] = True, cmd["id"]
                    self._log("item_confirmed", {"sku": sku, "slot": slot,
                                                "direction": "LOAD" if cmd["kind"] == "PICK" else "HANDOFF"}, command=cmd)
            if cmd["kind"] == "STOP" and kind == "SUCCEEDED":
                require(data.get("stopped") is True, "장비 중단 결과에는 정지 확인이 필요합니다")
            cmd["status"], cmd["result"] = kind, result
            if kind == "FAILED":
                if cmd["kind"] != "STOP":
                    self._fault(task, str(data.get("reason", "장비 작업 실패"))[:200])
            elif cmd["kind"] == "NAVIGATE":
                task["state"] = "WAIT_STOP"
            elif cmd["kind"] in {"PICK", "HANDOFF"}:
                task["state"] = "WAIT_ARM_CLEAR"
                if cmd["kind"] == "HANDOFF":
                    require(session["inventory"] and all(i["delivered"] for i in session["inventory"]), "미인계 상품 존재")
                    requested = sum(sum(o["items"].values()) for o in self.state["orders"].values()
                                    if o["session_id"] == session["id"])
                    require(len(session["inventory"]) == requested, "접수된 주문에 미적재 상품이 남아 있습니다")
                    session["state"], session["completed_at"] = "COMPLETED", self.clock()
                    self._log("shopping_completed", {"customer_mobile_receipt": "not_implemented_optional_SR29"}, task=task)
            elif cmd["kind"] == "LEAVE":
                task["state"] = "WAIT_EXIT"
        elif kind == "STOPPED":
            require(cmd["kind"] == "NAVIGATE" and cmd["status"] == "SUCCEEDED"
                    and task["state"] in {"WAIT_STOP", "WAIT_BASKET"}, "현재 이동 결과 이후에 정차를 확인해야 합니다")
            require(data.get("stopped") is True and data.get("zone_id") == task["zone_id"], "정차 구역 미확인")
            task["stopped_at"] = event["observed_at"]
        elif kind == "ARM_CLEAR":
            require(cmd["kind"] in {"PICK", "HANDOFF"} and cmd["status"] == "SUCCEEDED"
                    and task["state"] == "WAIT_ARM_CLEAR", "적재·인계 성공 후 팔 이탈을 확인해야 합니다")
            require(data.get("clear") is True, "팔 이탈 미확인")
            task["arm_clear"], task["state"] = True, "LEAVING"
            self._command(task, "LEAVE", task["robot_id"])
        elif kind == "EXITED":
            require(cmd["kind"] == "LEAVE" and cmd["status"] == "SUCCEEDED"
                    and task["state"] == "WAIT_EXIT" and data.get("outside") is True
                    and data.get("zone_id") == task["zone_id"], "현재 구역 이탈이 확인되지 않았습니다")
            zone = self.state["zones"][task["zone_id"]]
            require(zone["owner"] == task["id"], "구역 점유자 불일치")
            zone["owner"], task["state"], session["current_task"] = None, "DONE", None
            if task["kind"] == "HANDOFF":
                self.state["basket"] = None
                self.state["robots"][task["robot_id"]]["session_id"] = None
            self._log("zone_released", {"zone_id": task["zone_id"]}, task=task)
        else:
            raise DomainError("지원하지 않는 결과 종류", 422)
        self.state["results"][key] = fingerprint
        self._log("device_event", {"kind": kind, "data": data, "event_id": key}, command=cmd)
        return {"duplicate": False}

    @atomic
    def basket_ready(self, sid, task_id, basket_id):
        session = self._session(sid)
        require(basket_id == session["basket_id"], "이 고객에게 배정된 장바구니 식별값이 아닙니다")
        require(not session["error"] and session["current_task"] == task_id, "현재 고객 작업과 일치하지 않습니다")
        task = self.state["tasks"][task_id]
        require(task["kind"] == "HANDOFF" and task["state"] in {"MOVING", "WAIT_STOP", "WAIT_BASKET"}, "현재 인계 준비 단계가 아닙니다")
        require(self.state["zones"]["handoff"]["owner"] == task_id, "인계 구역 사용 고객이 아닙니다")
        self.state["basket"] = {"session_id": sid, "task_id": task_id, "basket_id": basket_id, "at": self.clock()}
        self._log("basket_ready_confirmed", {"basket_id": basket_id, "source": "operator_confirmation"}, task=task)

    @atomic
    def watchdog(self):
        if self.state["heartbeat_at"] is not None and not self._fresh_gateway():
            for device in self.state["devices"].values():
                device["connected"] = False
            for session in self.state["sessions"].values():
                if session["current_task"]:
                    self._fault(self.state["tasks"][session["current_task"]], "연결 프로그램 통신 시간 초과")
        for cmd in list(self.state["commands"].values()):
            if cmd["kind"] != "STOP" and cmd["status"] in {"SENT", "ACCEPTED"} and self.clock() - cmd["sent_at"] > self.command_timeout:
                self._fault(self.state["tasks"][cmd["task_id"]], "명령 결과 시간 초과: 성공 여부 불명")

    @atomic
    def mock_steps(self, count):
        require(type(count) is int and 1 <= count <= 100, "허용 단계는 1~100입니다", 422)
        self.state["permits"] = min(100, self.state["permits"] + count)
        return {"remaining": self.state["permits"]}

    @atomic
    def take_permit(self):
        if self.state["permits"]:
            self.state["permits"] -= 1
            return True
        return False

    @atomic
    def inject_failure(self, device_id, kind):
        require(device_id in self.state["devices"], "장비 ID를 확인하세요", 422)
        if kind == "PICK_FAIL":
            require(device_id in STATIONS.values(), "로봇팔을 선택하세요", 422)
            if device_id not in self.state["pick_failures"]:
                self.state["pick_failures"].append(device_id)
        elif kind == "DISCONNECT":
            self.state["devices"][device_id].update(connected=False, forced_offline=True)
            for session in self.state["sessions"].values():
                if session["current_task"]:
                    task = self.state["tasks"][session["current_task"]]
                    if device_id in {task["robot_id"], task["device_id"]}:
                        self._fault(task, f"모의 통신 끊김: {device_id}")
        else:
            raise DomainError("지원하지 않는 오류 주입", 422)
        self._log("mock_failure_injected", {"device_id": device_id, "kind": kind})

    @atomic
    def consume_failure(self, device_id):
        if device_id in self.state["pick_failures"]:
            self.state["pick_failures"].remove(device_id)
            return True
        return False

    @atomic
    def reset_mock(self):
        self.store.archive(self.state)
        self.state = self._fresh()
        self._log("mock_run_created", {"previous_run": "archived; real hardware not supported"})
        return {"run_id": self.state["run_id"]}

    def snapshot(self, sid=None):
        with self.lock:
            out = deepcopy(self.state)
            out.pop("results")
            for session in out["sessions"].values():
                session.pop("token_hash")
            out["products"], out["capacity"] = deepcopy(PRODUCTS), self.capacity
            out["server_time"] = self.clock()
            if sid is not None:
                self._session(sid)
                out["sessions"] = {sid: out["sessions"][sid]}
                for field in ["orders", "tasks", "commands"]:
                    out[field] = {k: v for k, v in out[field].items() if v["session_id"] == sid}
                out["zones"] = {name: {"busy": bool(zone["owner"]),
                                      "mine": zone["owner"] in out["tasks"],
                                      "waiting": len(zone["queue"])} for name, zone in out["zones"].items()}
                for field in ["robots", "gateway_id", "pick_failures", "basket", "permits", "devices"]:
                    out.pop(field, None)
            return out

    def logs(self):
        with self.lock:
            return self.store.logs(self.state["run_id"])

    def _invariants(self):
        assigned = [r["session_id"] for r in self.state["robots"].values() if r["session_id"]]
        assert len(assigned) == len(set(assigned)), "customer assigned more than one robot"
        for zone in self.state["zones"].values():
            assert len(zone["queue"]) == len(set(zone["queue"]))
            assert zone["owner"] not in zone["queue"]
        for session in self.state["sessions"].values():
            slots = [item["slot"] for item in session["inventory"]]
            assert len(slots) == len(set(slots))
            if session["state"] == "COMPLETED":
                assert session["checkout_requested"] and session["inventory"]
                assert all(item["delivered"] for item in session["inventory"])
