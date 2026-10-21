import pytest
import time
from server.domain import Engine
from robot_gateway.mock import MockWorld, make_event, next_action


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


class Harness:
    def __init__(self, engine):
        self.engine, self.world = engine, MockWorld()
        self.gateway_id = "test-gateway-001"
        engine.heartbeat(self.gateway_id)

    def step(self):
        e = self.engine
        e.heartbeat(self.gateway_id)
        choice = next_action(e.snapshot())
        if not choice:
            return False
        action, cmd = choice
        if action == "CLAIM":
            e.claim(self.gateway_id)
        elif action == "ACCEPTED":
            e.event(make_event(cmd, "ACCEPTED"))
        elif action == "EXECUTE":
            fail = cmd["kind"] in {"PICK", "HANDOFF"} and e.consume_failure(cmd["device_id"])
            e.event(self.world.execute(cmd, fail))
        else:
            e.event(self.world.observe(cmd, action, observed_at=e.clock()))
        return True

    def until(self, predicate, max_steps=250):
        for _ in range(max_steps):
            if predicate(self.engine.snapshot()):
                return
            assert self.step(), "Scenario reached a wait condition before the expected state"
        raise AssertionError("Scenario exceeded its deterministic step budget")


@pytest.fixture
def rig():
    clock = Clock()
    engine = Engine(clock=clock)
    harness = Harness(engine)
    yield engine, harness, clock
    engine.store.close()


def order(engine, sid, sku="SKU-JIN-RAMEN", quantity=1, request_id="order-request-001"):
    return engine.submit_order(sid, [{"sku": sku, "quantity": quantity}], request_id)


def command(snapshot, kind, status=None):
    return next((c for c in snapshot["commands"].values()
                 if c["kind"] == kind and (status is None or c["status"] == status)), None)
