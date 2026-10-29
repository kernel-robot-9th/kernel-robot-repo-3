"""Project-level state machine. No vendor ROS names or physical robot claims."""
from copy import deepcopy
from functools import wraps
import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid

from .catalog import PRODUCTS_PATH, load_products
from .store import Store

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
    # Connection age is displayed separately from device execution.
    capacity = 6
    cart_capacity = 3
    heartbeat_timeout = 10

    def __init__(self, path=":memory:", clock=time.time, *, catalog_path=PRODUCTS_PATH, mode="mock", readiness=None, test_only=False):
        require(mode in {"mock", "hardware"}, "장비 모드 오류", 422)
        self.mode, self.readiness = mode, readiness or {}
        self.test_only = test_only
        self.receiver_epoch = uid()  # Monotonic receipt times never cross process restarts.
        self.receiver_clock = time.monotonic
        if mode == "hardware":
            require(test_only or self.readiness.get("approved") is True, "현장 연결 검증 설정이 필요합니다")
        self.products = load_products(catalog_path)
        self.clock, self.lock, self.records = clock, threading.RLock(), []
        self.store = Store(path)
        stored = self.store.load()
        if stored and stored["mode"] != mode:
            self.store.close()
            raise DomainError("모의·실물 DB를 분리하세요")
        self.state = stored or self._fresh()
        from .device_tests import empty
        self.state.setdefault('device_tests', empty())
        if stored:
            self._recover()
        self.store.save(self.state, self.records)
        self.records = []

    def _fresh(self):
        return {
            "schema_version": 2, "units": {}, "trips": {},
            "device_tests": {"jobs": {}, "nodes": {}, "hold": None},
            "stock": {sku: {"on_hand": p["initial_stock"], "reserved": 0} for sku, p in self.products.items()},
            "catalog_reconciliation_required": False,
            "run_id": uid(), "mode": self.mode, "sessions": {}, "orders": {}, "tasks": {},
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
        for job in self.state['device_tests']['jobs'].values():
            if job['status'] not in {'SUCCEEDED', 'FAILED', 'CANCELLED', 'WAIT_REVIEW'}:
                job['status'] = 'UNCERTAIN' if job['kind'] in {'PICK', 'HANDOFF', 'NAVIGATE'} else 'FAILED'
                job['stop_requested_at'] = job['stop_requested_at'] or self.clock()
        self.state['device_tests']['nodes'] = {}
        # Never invent current stock for an earlier checkpoint or a changed catalog.
        legacy = self.state.get("schema_version") != 2
        if legacy:
            self.state.update(schema_version=2, units={}, trips={}, stock={}, catalog_reconciliation_required=True)
        if set(self.state["stock"]) != set(self.products):
            self.state["catalog_reconciliation_required"] = True
        for session in self.state["sessions"].values():
            session.setdefault("active_trip", None)
            session.setdefault("basket_side", None)
            session.setdefault("receipt_confirmed_at", None)
            if legacy and session["state"] != "COMPLETED":
                session.update(state="RECOVERY_REQUIRED", error="이전 실행 보존: 새 모의 시나리오 준비 필요")
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
        candidates = list(self.state['robots'].items())
        if self.mode == 'hardware':
            preferred = self.readiness.get('preferred_robot')
            candidates.sort(key=lambda pair: pair[0] != preferred)
        available = next((rid for rid, robot in candidates
                          if robot["session_id"] is None), None)
        require(available, "사용 가능한 로봇이 없습니다. 기존 고객 인계·이탈 후 다시 시작하세요")
        sid, token = uid(), secrets.token_urlsafe(32)
        session = {"id": sid, "label": label.strip(), "robot_id": available, "basket_id": "basket-" + sid,
                   "basket_side": "left" if available == "pinky-1" else "right", "active_trip": None,
                   "receipt_confirmed_at": None,
                   "token_hash": hashlib.sha256(token.encode()).hexdigest(), "state": "SHOPPING",
                   "checkout_requested": False, "current_task": None, "inventory": [],
                   "error": None, "created_at": self.clock(), "completed_at": None}
        self.state["sessions"][sid] = session
        session['route_version'] = self.state.get('field_route_version', 4)
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
            require(sku in self.products and type(qty) is int and 1 <= qty <= self.capacity,
                    "지원 상품과 허용 수량을 확인하세요", 422)
            require(sku not in normalized, "중복 SKU 행은 허용하지 않습니다", 422)
            normalized[sku] = qty
        require(normalized, "한 개 이상의 상품이 필요합니다", 422)
        for order in self.state["orders"].values():
            if order["session_id"] == sid and order["request_id"] == request_id:
                require(order["items"] == normalized, "같은 요청 ID의 주문 내용이 다릅니다")
                return deepcopy(order)
        require(not self.test_only and not self.state['device_tests']['hold'], '장비 시험 중입니다. 시험 종료·원위치 확인 후 주문할 수 있습니다')
        require(not session["checkout_requested"] and session["state"] == "SHOPPING" and not session["error"],
                "지금은 추가 주문을 받을 수 없습니다")
        require(not self.state["catalog_reconciliation_required"], "기존 실행의 재고 확인이 필요합니다")
        require(sum(normalized.values()) <= self.capacity, "한 주문은 최대 6개입니다", 422)
        for sku, qty in normalized.items():
            stock = self.state["stock"][sku]
            require(qty <= stock["on_hand"] - stock["reserved"], "주문 가능 재고가 부족합니다: " + self.products[sku]["name"])
        order = {"id": uid(), "session_id": sid, "request_id": request_id,
                 "items": normalized, "created_at": self.clock(), "status": "ACTIVE", "cancelled_at": None}
        self.state["orders"][order["id"]] = order
        for sku, qty in normalized.items():
            self.state["stock"][sku]["reserved"] += qty
            for _ in range(qty):
                item_id = uid()
                self.state["units"][item_id] = {"id": item_id, "order_id": order["id"], "session_id": sid,
                    "sku": sku, "state": "RESERVED", "trip_id": None, "slot": None}
        self._log("order_received", {"order_id": order["id"], "items": normalized}, session_id=sid)
        return deepcopy(order)

    @atomic
    def cancel_order(self, sid, order_id):
        session = self._session(sid)
        order = self.state["orders"].get(order_id)
        require(order and order["session_id"] == sid, "주문을 찾을 수 없습니다", 404)
        if order.get("status") == "CANCELLED":
            return deepcopy(order)
        require(not session["error"], "결과 불명·오류 작업은 자동 취소할 수 없습니다")
        tasks = [t for t in self.state["tasks"].values() if t.get("order_id") == order_id]
        task_ids = {t["id"] for t in tasks}
        require(not any(c["task_id"] in task_ids and c["sent_at"] is not None
                        for c in self.state["commands"].values()), "장비 명령 전송 후에는 자동 취소할 수 없습니다")
        units = [u for u in self.state["units"].values() if u["order_id"] == order_id]
        require(all(u["state"] in {"RESERVED", "PLANNED"} for u in units), "이미 출고된 상품이 있습니다")
        for task in tasks:
            zone = self.state["zones"][task["zone_id"]]
            if task["id"] in zone["queue"]:
                zone["queue"].remove(task["id"])
            if zone["owner"] == task["id"]:
                zone["owner"] = None
            task["state"] = "CANCELLED"
            if session["current_task"] == task["id"]:
                session["current_task"] = None
        for cmd in self.state["commands"].values():
            if cmd["task_id"] in task_ids:
                cmd["status"] = "CANCELLED"
        for unit in units:
            self.state["stock"][unit["sku"]]["reserved"] -= 1
            unit["state"] = "CANCELLED"
        order.update(status="CANCELLED", cancelled_at=self.clock())
        self._log("order_cancelled", {"order_id": order_id}, session_id=sid)
        return deepcopy(order)

    def _plan_trip(self, session):
        trip = self.state["trips"].get(session.get("active_trip"))
        if trip and trip["state"] != "LOADING":
            return
        occupied = [self.state["units"][i] for i in trip["unit_ids"]
                    if self.state["units"][i]["state"] != "CANCELLED"] if trip else []
        available_slots = [slot for slot in range(self.cart_capacity) if slot not in {u["slot"] for u in occupied}]
        pending = [u for u in self.state["units"].values()
                   if u["session_id"] == session["id"] and u["state"] == "RESERVED"][:len(available_slots)]
        if not pending:
            return
        if not trip:
            trip = {"id": uid(), "session_id": session["id"], "number": 1 + sum(
                t["session_id"] == session["id"] for t in self.state["trips"].values()),
                "unit_ids": [], "state": "LOADING"}
            self.state["trips"][trip["id"]] = trip
            session["active_trip"] = trip["id"]
        groups = {}
        for unit, slot in zip(pending, available_slots):
            unit.update(state="PLANNED", trip_id=trip["id"], slot=slot)
            trip["unit_ids"].append(unit["id"])
            key = (unit["order_id"], self.products[unit["sku"]]["station"])
            groups.setdefault(key, []).append({"sku": unit["sku"], "slot": slot, "item_id": unit["id"]})
        for (order_id, station), items in groups.items():
            task = self._task(session, "LOAD", station, items, order_id)
            task["trip_id"] = trip["id"]

    def _complete_shopping(self, session, task=None):
        units = [u for u in self.state["units"].values()
                 if u["session_id"] == session["id"] and u["state"] != "CANCELLED"]
        if session["checkout_requested"] and all(u["state"] == "DELIVERED" for u in units):
            session.update(state="COMPLETED", completed_at=self.clock())
            self._log("shopping_completed", {"customer_mobile_receipt": "not_implemented_optional_SR29"},
                      task=task, session_id=session["id"])
            return True
        return False

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
               "mode": self.mode, "kind": kind, "zone_id": task["zone_id"], "items": deepcopy(task["items"]),
               "status": "CREATED", "created_at": self.clock(), "sent_at": None,
               "accepted_at": None, "result": None}
        cmd['route_version'] = self._session(task['session_id']).get('route_version', 4)
        if kind == "HANDOFF":
            cmd["basket_id"] = self._session(task["session_id"])["basket_id"]
            cmd["basket_side"] = self._session(task["session_id"])["basket_side"]
            cmd["model_id"] = "act-left-v2-050000" if cmd["basket_side"] == "left" else self.readiness.get("right_model_id", "act-right-pending")
        cmd["trip_id"] = task.get("trip_id")
        if kind == "STOP_POLICY":
            cmd["target_command_id"] = next(c["id"] for c in self.state["commands"].values()
                                            if c["task_id"] == task["id"] and c["kind"] == "HANDOFF")
        if self.mode == 'hardware' and device_id.startswith('pinky-') and kind in {'NAVIGATE', 'LEAVE'}:
            routes = self.readiness.get('pinky_routes_files', {}).get(device_id) or self.readiness.get('pinky_routes_file')
            if routes:
                from robots.pinky.field_routes import command_route
                try:
                    cmd['path_plan'] = command_route(routes, cmd)
                except (OSError, KeyError, ValueError) as exc:
                    require(False, '실물 Pinky 관제 경로 설정 확인 필요: ' + str(exc)[:120])
        self.state["commands"][cmd["id"]] = cmd
        self._log("command_created", {"kind": kind, "device_id": device_id}, command=cmd)
        return cmd

    def _observed(self, at):
        return at is not None

    def _ready(self, task):
        basket = self.state["basket"]
        return bool(basket and basket["session_id"] == task["session_id"]
                    and basket["task_id"] == task["id"] and self._observed(basket["at"]))

    def _pump(self):
        if self.test_only or self.state['device_tests']['hold']:
            return
        for session in self.state["sessions"].values():
            if session["error"] or session["state"] == "COMPLETED":
                continue
            if session["current_task"] is None:
                self._plan_trip(session)
                task = next((t for t in self.state["tasks"].values()
                             if t["session_id"] == session["id"] and t["state"] == "QUEUED"), None)
                if task is None and session["checkout_requested"]:
                    outstanding = [i for i in session["inventory"] if not i["delivered"]]
                    if outstanding:
                        task = self._task(session, "HANDOFF", "handoff",
                                          [{"sku": i["sku"], "slot": i["slot"], "item_id": i["item_id"]} for i in outstanding])
                        task["trip_id"] = session["active_trip"]
                        self.state["trips"][session["active_trip"]]["state"] = "HANDOFF"
                        session["state"] = "DELIVERING"
                    elif self._complete_shopping(session):
                        self.state["robots"][session["robot_id"]]["session_id"] = None
                if task:
                    session["current_task"] = task["id"]
                    task["state"] = "WAIT_ZONE"
                    self.state["zones"][task["zone_id"]]["queue"].append(task["id"])
            if session["current_task"]:
                task = self.state["tasks"][session["current_task"]]
                if task["state"] in {"WAIT_STOP", "WAIT_BASKET"} and self._observed(task["stopped_at"]):
                    if task["kind"] == "HANDOFF" and not self._ready(task):
                        task["state"] = "WAIT_BASKET"
                    elif self.state["devices"][task["device_id"]]["connected"]:
                        task["state"] = "ARM_WORK"
                        self._command(task, "PICK" if task["kind"] == "LOAD" else "HANDOFF", task["device_id"])
        for zone_id, zone in self.state["zones"].items():
            if zone["owner"] or not zone["queue"]:
                continue
            task = next((self.state['tasks'][tid] for tid in zone['queue']
                         if self._can_reserve_zone(self.state['tasks'][tid])), None)
            if task is None:
                continue
            session = self._session(task["session_id"])
            if session["error"]:
                continue
            if not all(self.state["devices"][d]["connected"] for d in [task["robot_id"], task["device_id"]]):
                continue
            zone['queue'].remove(task['id'])
            zone["owner"] = task['id']
            task["state"] = "MOVING"
            self._command(task, "NAVIGATE", task["robot_id"])
            self._log("zone_reserved", {"zone_id": zone_id}, task=task)

    def _can_reserve_zone(self, task):
        return True

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
        return {"run_id": self.state["run_id"], "mode": self.mode}

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
            cmd["status"], cmd["sent_at"] = "SENT", self.clock()
            self._log("command_sent", {"gateway_id": gateway_id}, command=cmd)
            return deepcopy(cmd)
        return None

    def _fresh_gateway(self):
        at = self.state["heartbeat_at"]
        return at is not None

    @atomic
    def event(self, event):
        require(event["run_id"] == self.state["run_id"] and event["mode"] == self.mode, "실행 또는 연결 모드 불일치")
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
        if kind == 'TRANSFER_READY' and cmd.get('transfer'):
            require(cmd['transfer'] == data, '이미 확인된 인계 근거와 충돌합니다')
            self.state['results'][key] = fingerprint
            return {'duplicate': True}
        if kind in {"SUCCEEDED", "FAILED"} and cmd["result"]:
            require(cmd["result"] == result, "이미 확정된 결과와 충돌합니다")
            self.state["results"][key] = fingerprint
            self._log("duplicate_result", command=cmd)
            return {"duplicate": True}
        require(cmd["status"] not in {"UNCERTAIN", "CANCELLED"}, "중단·불명 명령의 결과는 자동 반영하지 않습니다")
        require(not session["error"] or cmd["kind"] == "STOP", "오류 작업의 후속 결과는 상태 확인이 필요합니다")
        require(self._fresh_gateway() and self.state["devices"][cmd["device_id"]]["connected"], "연결 상태 미확인")
        require(session["current_task"] == task["id"], "현재 작업의 관측이 아닙니다")
        if self.mode == 'hardware' and kind != 'ACCEPTED':
            if kind in {'SUCCEEDED', 'FAILED', 'TRANSFER_READY'}:
                self._execution_result(cmd, task, session, kind, data)
            self.state['results'][key] = fingerprint
            self._log('device_event', {'kind': kind, 'data': data}, command=cmd)
            return {'duplicate': False}
        if kind == "ACCEPTED":
            require(cmd["status"] in {"SENT", "ACCEPTED"}, "전송 후에만 수락할 수 있습니다")
            cmd["status"], cmd["accepted_at"] = "ACCEPTED", self.clock()
        elif kind in {"SUCCEEDED", "FAILED"}:
            require(cmd["status"] == "ACCEPTED", "명령 수락 전에 결과를 확정할 수 없습니다")
            require(not (cmd["kind"] == "HANDOFF" and kind == "SUCCEEDED"),
                    "인계는 담기·비움·복귀 확인 후 정책 중지와 실제 정지를 확인해야 합니다")
            if cmd["kind"] in {"PICK", "HANDOFF"}:
                self._confirm_items(cmd, data, complete=kind == "SUCCEEDED")
            if cmd["kind"] == "STOP" and kind == "SUCCEEDED":
                require(data.get("stopped") is True, "장비 중단 결과에는 정지 확인이 필요합니다")
            if cmd["kind"] == "STOP_POLICY" and kind == "SUCCEEDED":
                require(all(data.get(k) is True for k in ("policy_stopped", "motion_stopped", "hold_confirmed", "torque_enabled")),
                        "정책 출력 중지·실제 정지·토크 유지 확인이 필요합니다")
            cmd["status"], cmd["result"] = kind, result
            if kind == "FAILED":
                if cmd["kind"] != "STOP":
                    self._fault(task, str(data.get("reason", "장비 작업 실패"))[:200])
            elif cmd["kind"] == "NAVIGATE":
                task["state"] = "WAIT_STOP"
            elif cmd["kind"] == "PICK":
                task["state"] = "WAIT_ARM_CLEAR"
            elif cmd["kind"] == "STOP_POLICY":
                handoff = next(c for c in self.state["commands"].values()
                               if c["task_id"] == task["id"] and c["kind"] == "HANDOFF")
                require(handoff["status"] == "TRANSFERRED", "상품 인계 근거가 먼저 필요합니다")
                handoff.update(status="SUCCEEDED", result={"kind": "SUCCEEDED", "data": handoff["transfer"]})
                task["state"] = "WAIT_ARM_CLEAR"
                task["policy_stopped_at"] = self.clock()
                self._complete_shopping(session, task)
            elif cmd["kind"] == "LEAVE":
                task["state"] = "WAIT_EXIT"
        elif kind == "TRANSFER_READY":
            require(cmd["kind"] == "HANDOFF" and cmd["status"] == "ACCEPTED", "실행 중인 인계 작업이 아닙니다")
            require(all(data.get(k) is True for k in ("cart_visible", "cart_empty", "last_item_placed", "standby_reached")),
                    "카트 비움만으로 완료할 수 없습니다. 마지막 담기·복귀·가림 없음 확인이 필요합니다")
            self._confirm_items(cmd, data, complete=True)
            cmd.update(status="TRANSFERRED", transfer=deepcopy(data))
            task["state"] = "WAIT_POLICY_STOP"
            self._command(task, "STOP_POLICY", task["device_id"])
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
                self.state["trips"][task["trip_id"]]["state"] = "DONE"
                session["active_trip"] = None
                if session["state"] == "COMPLETED":
                    self.state["robots"][task["robot_id"]]["session_id"] = None
                else:
                    session["state"] = "CHECKOUT_REQUESTED"
            self._log("zone_released", {"zone_id": task["zone_id"]}, task=task)
        else:
            raise DomainError("지원하지 않는 결과 종류", 422)
        self.state["results"][key] = fingerprint
        self._log("device_event", {"kind": kind, "data": data, "event_id": key}, command=cmd)
        return {"duplicate": False}

    def _execution_result(self, cmd, task, session, kind, data):
        kind = 'SUCCEEDED' if kind == 'TRANSFER_READY' else kind
        cmd.update(status=kind, result={'kind': kind, 'data': data})
        if cmd['kind'] in {'PICK', 'HANDOFF'}:
            executed = data.get('executed_items', data.get('confirmed_items', []))
            self._confirm_items(cmd, {'confirmed_items': executed, 'basket_id': cmd.get('basket_id')},
                                complete=False, physical=False)
        if kind == 'FAILED':
            if cmd['kind'] != 'STOP':
                self._fault(task, str(data.get('reason', '장비 실행 실패'))[:200])
        elif cmd['kind'] == 'NAVIGATE':
            task['state'] = 'ARM_WORK'
            self._command(task, 'PICK' if task['kind'] == 'LOAD' else 'HANDOFF', task['device_id'])
        elif cmd['kind'] in {'PICK', 'HANDOFF'}:
            task['state'] = 'LEAVING'
            self._command(task, 'LEAVE', task['robot_id'])
        elif cmd['kind'] == 'LEAVE':
            self.state['zones'][task['zone_id']]['owner'] = None
            task['state'], session['current_task'] = 'DONE', None
            if task['kind'] == 'HANDOFF':
                self.state['basket'] = None
                self.state['trips'][task['trip_id']]['state'] = 'DONE'
                session['active_trip'] = None
                session['state'] = 'CHECKOUT_REQUESTED'
                if self._complete_shopping(session, task):
                    self.state['robots'][task['robot_id']]['session_id'] = None
            self._log('zone_released', {'zone_id': task['zone_id']}, task=task)

    def _confirm_items(self, cmd, data, *, complete, physical=True):
        confirmed = data.get("confirmed_items", [])
        recorded = self.state.get("operator_observations", {}).get(cmd["id"], {})
        require(isinstance(confirmed, list) and all(isinstance(i, dict) and set(i) == {"sku", "slot", "item_id"}
                and isinstance(i["sku"], str) and isinstance(i["item_id"], str) and type(i["slot"]) is int
                for i in confirmed), "확인 상품 형식 오류", 422)
        canonical = {(i["sku"], i["slot"], i["item_id"]) for i in confirmed}
        expected = {(i["sku"], i["slot"], i["item_id"]) for i in cmd["items"]}
        require(len(canonical) == len(confirmed) and canonical.issubset(expected), "상품·적재 위치·이동 식별값이 명령과 다릅니다")
        require(not complete or canonical == expected, "일부 상품만 확인된 결과는 전체 성공이 아닙니다")
        if cmd["kind"] == "HANDOFF":
            require(data.get("basket_id") == cmd["basket_id"], "다른 고객 장바구니의 인계 결과입니다")
        session = self._session(cmd["session_id"])
        for sku, slot, item_id in sorted(canonical, key=lambda i: i[1]):
            unit = self.state["units"][item_id]
            require(unit["trip_id"] == cmd["trip_id"] and unit["slot"] == slot, "이전 운반 차수의 결과입니다")
            if cmd["kind"] == "PICK":
                require(unit["state"] == "PLANNED", "이미 처리한 상품입니다")
                require(not any(i["slot"] == slot and not i["delivered"] for i in session["inventory"]), "이미 적재된 위치")
                stock = self.state["stock"][sku]
                require(stock["reserved"] > 0 and stock["on_hand"] > 0, "예약 재고 불일치")
                stock["on_hand"] -= 1
                stock["reserved"] -= 1
                unit["state"] = "LOADED"
                session["inventory"].append({"sku": sku, "slot": slot, "item_id": item_id, "trip_id": cmd["trip_id"],
                    "delivered": False, "load_command_id": cmd["id"], "handoff_command_id": None,
                    "physical_loading_confirmed": physical or "pick-"+str(slot) in recorded})
            else:
                require(unit["state"] == "LOADED", "인계할 상품을 확인할 수 없습니다")
                item = next(i for i in session["inventory"] if i["item_id"] == item_id)
                item.update(delivered=True, handoff_command_id=cmd["id"], physical_delivery_confirmed=physical or "delivered" in recorded)
                unit["state"] = "DELIVERED"
            self._log("item_confirmed" if physical else "item_executed", {"sku": sku, "slot": slot, "item_id": item_id, "trip_id": cmd["trip_id"],
                "direction": "LOAD" if cmd["kind"] == "PICK" else "HANDOFF"}, command=cmd)

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
    def mock_steps(self, count):
        require(self.mode == "mock", "실물 모드에서는 모의 실행을 할 수 없습니다")
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
        require(self.mode == "mock", "실물 모드에서는 모의 오류를 주입할 수 없습니다")
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
    def reset_mock(self, acknowledge_unresolved=False):
        require(self.mode == "mock", "실물 모드 재고·작업은 모의 초기화할 수 없습니다")
        unresolved = any(t["state"] not in {"DONE", "CANCELLED"} for t in self.state["tasks"].values())
        require(not unresolved or acknowledge_unresolved is True,
                "진행·불명 작업이 있습니다. 가상 실행 폐기 확인 후 새 모의 시나리오를 시작하세요")
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
            out["products"], out["capacity"] = deepcopy(list(self.products.values())), self.capacity
            out["cart_capacity"] = self.cart_capacity
            out['test_only'] = self.test_only
            out['test_hold'] = self.state['device_tests']['hold']
            out.pop('device_tests', None)
            for product in out["products"]:
                stock = self.state["stock"].get(product["sku"])
                product.update(stock=deepcopy(stock), available=stock["on_hand"] - stock["reserved"] if stock else None)
            for order in out["orders"].values():
                tids = {t["id"] for t in self.state["tasks"].values() if t.get("order_id") == order["id"]}
                order["cancellable"] = order.get("status") == "ACTIVE" and not self._session(order["session_id"])["error"] and not any(
                    c["task_id"] in tids and c["sent_at"] is not None for c in self.state["commands"].values())
            out["server_time"] = self.clock()
            if sid is not None:
                self._session(sid)
                out["sessions"] = {sid: out["sessions"][sid]}
                for field in ["orders", "tasks", "commands", "units", "trips"]:
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
            slots = [item["slot"] for item in session["inventory"] if not item["delivered"]]
            assert len(slots) == len(set(slots))
            if not self.state["catalog_reconciliation_required"]:
                assert len(slots) <= self.cart_capacity
            if session["state"] == "COMPLETED":
                assert session["checkout_requested"]
                assert all(item["delivered"] for item in session["inventory"])
        for sku, stock in self.state["stock"].items():
            assert 0 <= stock["reserved"] <= stock["on_hand"]
            assert stock["reserved"] == sum(u["sku"] == sku and u["state"] in {"RESERVED", "PLANNED"}
                                            for u in self.state["units"].values())
