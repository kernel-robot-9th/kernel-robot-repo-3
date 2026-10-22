"""Three authenticated gateways and a shared TOY world. No physical drivers.

The shared world exists only to verify interlocks across separate gateway
processes. Its observations are not camera measurements or Gazebo physics.
"""
from copy import deepcopy
import json
from pathlib import Path

from robot_gateway.mock import MockWorld, make_event, next_action
from .domain import Engine, atomic, require

PROFILE_PATH = Path(__file__).resolve().parents[1] / "config" / "gateways.json"


def profiles():
    data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    devices = [d for p in data.values() for d in p["devices"]]
    if len(devices) != len(set(devices)):
        raise ValueError("한 장비를 여러 중개에 배정할 수 없습니다")
    return data


class DistributedEngine(Engine):
    def __init__(self, *args, **kwargs):
        self.profiles = profiles()
        super().__init__(*args, **kwargs)
        require(self.state.get("gateway_mode") == "distributed", "단일 중개 DB와 분산 DB를 구분하세요")
        require(('road' in self.state) == (getattr(self, 'motion_policy', None) == 'reference_v4'),
                '논리 모의 실행과 v4 주문 이동 DB를 분리하세요')

    def _fresh(self):
        state = super()._fresh()
        state.update(gateway_mode="distributed", gateways={
            node: {**deepcopy(profile), "instance_id": None, "heartbeat_at": None, "connected": False, "retired_instances": []}
            for node, profile in self.profiles.items()}, mock_world=MockWorld().data, mock_actions={})
        expected = set(state["devices"])
        actual = {d for p in self.profiles.values() for d in p["devices"]}
        require(actual == expected, "중개 설정과 장비 목록이 일치하지 않습니다")
        for node, profile in self.profiles.items():
            for device in profile["devices"]:
                state["devices"][device]["gateway_id"] = node
        return state

    def _recover(self):
        if ('road' in self.state) != (getattr(self, 'motion_policy', None) == 'reference_v4'):
            self.store.close()
            require(False, '논리 모의 실행과 v4 주문 이동 DB를 분리하세요')
        require(self.state.get("gateway_mode") == "distributed", "단일 중개 DB와 분산 DB를 구분하세요")
        require({n: set(p["devices"]) for n, p in self.state.get("gateways", {}).items()} ==
                {n: set(p["devices"]) for n, p in self.profiles.items()}, "기존 DB와 담당 장비 설정이 다릅니다")
        super()._recover()
        for node in self.state.get("gateways", {}).values():
            node.update(instance_id=None, heartbeat_at=None, connected=False)

    def _node(self, node_id, instance_id):
        require(node_id in self.state["gateways"], "등록되지 않은 중개입니다", 403)
        node = self.state["gateways"][node_id]
        require(node["instance_id"] == instance_id and node["connected"]
                and self._fresh_observation_node(node), "현재 중개 인스턴스 연결 미확인")
        return node

    def _fresh_observation_node(self, node):
        at = node["heartbeat_at"]
        return at is not None and 0 <= self.clock() - at <= self.heartbeat_timeout

    def _fresh_gateway(self):
        # Parent event/claim also checks the command device's connected state.
        return any(n["connected"] and self._fresh_observation_node(n)
                   for n in self.state["gateways"].values())

    def _fault_devices(self, devices, reason):
        for session in self.state["sessions"].values():
            if session["current_task"]:
                task = self.state["tasks"][session["current_task"]]
                if {task["robot_id"], task["device_id"]} & set(devices):
                    self._fault(task, reason)

    @atomic
    def node_heartbeat(self, node_id, instance_id, role='control'):
        require(node_id in self.state["gateways"], "등록되지 않은 중개입니다", 403)
        node = self.state["gateways"][node_id]
        old = node["instance_id"]
        require(role in {'control', 'test'}, '중계 역할 오류')
        require(old != instance_id or node.get('role', role) == role, '같은 실행에서 중계 역할을 바꿀 수 없습니다')
        require(instance_id not in node.setdefault("retired_instances", []), "교체된 중개 실행입니다. 상태 확인이 필요합니다")
        # A live instance cannot be displaced by an accidental second launch.
        require(not old or old == instance_id or not self._fresh_observation_node(node),
                "같은 중개가 이미 실행 중입니다. 기존 프로세스를 종료하고 연결 만료 후 재시작하세요")
        if old and (old != instance_id or not self._fresh_observation_node(node)):
            self._fault_devices(node["devices"], f"중개 재연결: {node_id} · 상태 확인 필요")
            if old != instance_id:
                node["retired_instances"].append(old)
        node.update(instance_id=instance_id, heartbeat_at=self.clock(), connected=True, role=role)
        for device_id in node["devices"]:
            device = self.state["devices"][device_id]
            device["connected"] = role == 'control' and not device["forced_offline"]
        if old != instance_id:
            self._log("gateway_connected", {"gateway_id": node_id, "devices": node["devices"], "mode": self.mode})
        return {"run_id": self.state["run_id"], "mode": self.mode, "devices": node["devices"],
                "heartbeat_timeout": self.heartbeat_timeout}

    @atomic
    def node_claim(self, node_id, instance_id):
        node = self._node(node_id, instance_id)
        require(node.get('role', 'control') == 'control' and not self.test_only, '시험 전용 중계/서버는 주문 명령을 실행하지 않습니다')
        command = Engine.claim.__wrapped__(self, node_id, node["devices"])
        if command:
            actual = self.state["commands"][command["id"]]
            actual.update(gateway_id=node_id, instance_id=instance_id)
            command = deepcopy(actual)
        return command

    def _validate_gateway(self, gateway_id):
        node = self.state["gateways"].get(gateway_id)
        require(node is not None and node["connected"] and self._fresh_observation_node(node), "중개 연결 미확인")

    def _owned_command(self, node_id, instance_id, command_id):
        node = self._node(node_id, instance_id)
        require(command_id in self.state["commands"], "명령을 찾을 수 없습니다", 404)
        command = self.state["commands"][command_id]
        require(command["device_id"] in node["devices"]
                and command.get("gateway_id") == node_id
                and command.get("instance_id") == instance_id, "다른 중개 또는 이전 인스턴스의 명령입니다", 403)
        return command

    @atomic
    def node_event(self, node_id, instance_id, event):
        self._owned_command(node_id, instance_id, event["command_id"])
        return Engine.event.__wrapped__(self, event)

    def node_work(self, node_id, instance_id):
        with self.lock:
            node = self._node(node_id, instance_id)
            snapshot = self.snapshot()
            snapshot["commands"] = {k: c for k, c in snapshot["commands"].items()
                                    if c["device_id"] in node["devices"]
                                    and snapshot["tasks"][c["task_id"]]["state"] != "DONE"
                                    and (c["status"] == "CREATED" or
                                         (c.get("gateway_id") == node_id and c.get("instance_id") == instance_id))}
            task_ids = {c["task_id"] for c in snapshot["commands"].values()}
            snapshot["tasks"] = {k: t for k, t in snapshot["tasks"].items() if k in task_ids}
            session_ids = {c["session_id"] for c in snapshot["commands"].values()}
            snapshot["sessions"] = {k: {"error": s["error"]} for k, s in snapshot["sessions"].items() if k in session_ids}
            snapshot["devices"] = {k: d for k, d in snapshot["devices"].items() if k in node["devices"]}
            return {k: snapshot[k] for k in ["run_id", "server_time", "commands", "tasks", "sessions", "devices"]}

    @atomic
    def mock_action(self, node_id, instance_id, command_id, action):
        require(self.mode == "mock", "실물 모드에 가상 결과를 만들 수 없습니다")
        command = self._owned_command(node_id, instance_id, command_id)
        require(action in {"EXECUTE", "STOPPED", "ARM_CLEAR", "EXITED"}, "지원하지 않는 모의 동작", 422)
        key = command_id + ":" + action
        if key in self.state["mock_actions"]:
            return deepcopy(self.state["mock_actions"][key])
        # The expected next action enforces guards before mutating the toy world.
        snapshot = self.node_work(node_id, instance_id)
        snapshot["commands"] = {command_id: command}
        choice = next_action(snapshot)
        require(choice is not None and choice[0] == action, "현재 명령 단계에서 실행할 수 없습니다")
        world = MockWorld(deepcopy(self.state["mock_world"]))
        if action == "EXECUTE":
            fail = command["device_id"] in self.state["pick_failures"]
            if fail:
                self.state["pick_failures"].remove(command["device_id"])
            event = world.execute(command, fail)
        else:
            event = world.observe(command, action, self.clock())
        event["observed_at"] = self.clock()
        self.state["mock_world"] = world.data
        self.state["mock_actions"][key] = event
        return deepcopy(event)

    @atomic
    def watchdog(self):
        for node_id, node in self.state["gateways"].items():
            if node["connected"] and not self._fresh_observation_node(node):
                node["connected"] = False
                for device in node["devices"]:
                    self.state["devices"][device]["connected"] = False
                self._fault_devices(node["devices"], f"중개 통신 시간 초과: {node_id}")
                self._log("gateway_disconnected", {"gateway_id": node_id})
        for command in list(self.state["commands"].values()):
            if (command["kind"] != "STOP" and command["status"] in {"SENT", "ACCEPTED"}
                    and self.clock() - command["sent_at"] > command.get("timeout_seconds", self.command_timeout)):
                self._fault(self.state["tasks"][command["task_id"]], "명령 결과 시간 초과: 성공 여부 불명")

    def snapshot(self, sid=None):
        out = super().snapshot(sid)
        for key in ["mock_world", "mock_actions"]:
            out.pop(key, None)
        for node in out.get("gateways", {}).values():
            node.pop("retired_instances", None)
            node["connected"] = node["connected"] and self._fresh_observation_node(node)
        if sid is not None:
            out.pop("gateways", None)
            out.pop("gateway_mode", None)
        return out
