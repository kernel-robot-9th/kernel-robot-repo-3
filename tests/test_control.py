from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import uuid

import pytest

from server.domain import DomainError, Engine
from robot_gateway.mock import make_event
from conftest import command, order, Harness, Clock


def start_order(rig, quantity=1):
    e, h, clock = rig
    sid = e.create_session("고객 A")["session_id"]
    order(e, sid, quantity=quantity)
    return e, h, clock, sid


def test_two_customers_receive_different_robots_and_third_waits(rig):
    e, _, _ = rig
    with ThreadPoolExecutor(max_workers=2) as pool:
        sessions = list(pool.map(e.create_session, ["A", "B"]))
    assert len({s["robot_id"] for s in sessions}) == 2
    with pytest.raises(DomainError):
        e.create_session("C")
    assert e.authenticate_customer(sessions[0]["token"]) == sessions[0]["session_id"]
    snapshot = e.snapshot(sessions[0]["session_id"])
    assert list(snapshot["sessions"]) == [sessions[0]["session_id"]]
    assert "token_hash" not in str(snapshot)


def test_shared_zone_fifo_exclusive_until_exit_observation(rig):
    e, h, _ = rig
    a, b = [e.create_session(name)["session_id"] for name in ["A", "B"]]
    order(e, a)
    order(e, b)
    first = e.snapshot()["zones"]["load-a"]["owner"]
    assert len(e.snapshot()["zones"]["load-a"]["queue"]) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: e.claim(h.gateway_id), range(2)))
    assert sum(c is not None for c in claims) == 1
    h.until(lambda s: command(s, "LEAVE", "SUCCEEDED") is not None)
    assert e.snapshot()["zones"]["load-a"]["owner"] == first
    assert not any(c["session_id"] == b for c in e.snapshot()["commands"].values())
    h.step()  # EXITED, not merely successful navigation
    snapshot = e.snapshot()
    owner = snapshot["zones"]["load-a"]["owner"]
    assert snapshot["tasks"][owner]["session_id"] == b


def test_arrival_success_does_not_start_loading_before_stop(rig):
    e, h, _, _ = start_order(rig)
    h.until(lambda s: command(s, "NAVIGATE", "SUCCEEDED") is not None)
    assert command(e.snapshot(), "PICK") is None
    h.step()
    assert command(e.snapshot(), "PICK", "CREATED")


def test_sending_and_accepting_do_not_change_quantities(rig):
    e, h, _, sid = start_order(rig)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    assert e.snapshot()["sessions"][sid]["inventory"] == []
    assert command(e.snapshot(), "LEAVE") is None


def test_departure_requires_load_result_and_arm_clear(rig):
    e, h, _, _ = start_order(rig)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    pick = command(e.snapshot(), "PICK")
    with pytest.raises(DomainError):
        e.event(make_event(pick, "ARM_CLEAR", {"clear": True}))
    h.step()  # successful simulated item movement
    assert command(e.snapshot(), "LEAVE") is None
    h.step()  # independent arm clearance
    assert command(e.snapshot(), "LEAVE", "CREATED")


def test_handoff_requires_matching_customer_basket(rig):
    e, h, _, sid = start_order(rig)
    other = e.create_session("B")["session_id"]
    e.checkout(sid)
    h.until(lambda s: any(t["kind"] == "HANDOFF" and t["state"] == "WAIT_BASKET" for t in s["tasks"].values()))
    task_id = e.snapshot()["sessions"][sid]["current_task"]
    assert command(e.snapshot(), "HANDOFF") is None
    with pytest.raises(DomainError):
        e.basket_ready(other, task_id, "basket-B")
    with pytest.raises(DomainError):
        e.basket_ready(sid, task_id, "basket-B")
    e.basket_ready(sid, task_id, e.snapshot()["sessions"][sid]["basket_id"])
    h.until(lambda s: command(s, "HANDOFF", "ACCEPTED") is not None)
    cmd = command(e.snapshot(), "HANDOFF")
    with pytest.raises(DomainError):
        e.event(make_event(cmd, "SUCCEEDED", {"confirmed_items": cmd["items"], "basket_id": "basket-B"}))
    assert not any(i["delivered"] for i in e.snapshot()["sessions"][sid]["inventory"])


def test_duplicate_event_and_new_id_repeated_result_count_once(rig):
    e, h, _, sid = start_order(rig, quantity=2)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    cmd = command(e.snapshot(), "PICK")
    result = h.world.execute(cmd)
    e.event(result)
    assert e.event(result)["duplicate"]
    repeat = {**result, "event_id": str(uuid.uuid4())}
    assert e.event(repeat)["duplicate"]
    assert len(e.snapshot()["sessions"][sid]["inventory"]) == 2
    movements = e.store.db.execute("SELECT count(*) FROM movements").fetchone()[0]
    assert movements == 2


def test_partial_failure_records_only_confirmed_items_and_blocks_departure(rig):
    e, h, _, sid = start_order(rig, quantity=2)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    cmd = command(e.snapshot(), "PICK")
    data = {"confirmed_items": cmd["items"][:1], "reason": "두 번째 상품 집기 실패"}
    e.event(make_event(cmd, "FAILED", data))
    snapshot = e.snapshot()
    assert len(snapshot["sessions"][sid]["inventory"]) == 1
    assert snapshot["sessions"][sid]["state"] == "ERROR"
    assert command(snapshot, "LEAVE") is None
    assert snapshot["zones"]["load-a"]["owner"]


def test_incomplete_success_is_rejected_atomically(rig):
    e, h, _, sid = start_order(rig, quantity=2)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    cmd = command(e.snapshot(), "PICK")
    with pytest.raises(DomainError):
        e.event(make_event(cmd, "SUCCEEDED", {"confirmed_items": cmd["items"][:1]}))
    assert e.snapshot()["sessions"][sid]["inventory"] == []
    assert command(e.snapshot(), "PICK")["status"] == "ACCEPTED"


@pytest.mark.parametrize("field,value", [("session_id", "other-customer"), ("device_id", "omx-b"),
                                         ("task_id", "old-task"), ("run_id", "old-run"), ("mode", "real")])
def test_wrong_result_correlation_rejected(rig, field, value):
    e, h, _, sid = start_order(rig)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    cmd = command(e.snapshot(), "PICK")
    event = make_event(cmd, "SUCCEEDED", {"confirmed_items": cmd["items"]})
    event[field] = value
    with pytest.raises(DomainError):
        e.event(event)
    assert e.snapshot()["sessions"][sid]["inventory"] == []


def test_disconnect_retains_zone_and_rejects_late_success(rig):
    e, h, _, sid = start_order(rig)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    cmd = command(e.snapshot(), "PICK")
    e.inject_failure("omx-a", "DISCONNECT")
    e.heartbeat(h.gateway_id)
    snapshot = e.snapshot()
    assert snapshot["sessions"][sid]["state"] == "ERROR"
    assert snapshot["zones"]["load-a"]["owner"] == cmd["task_id"]
    assert snapshot["devices"]["omx-a"]["connected"] is False
    assert command(snapshot, "STOP")
    with pytest.raises(DomainError):
        e.event(make_event(cmd, "SUCCEEDED", {"confirmed_items": cmd["items"]}))
    assert not e.snapshot()["sessions"][sid]["inventory"]


def test_heartbeat_timeout_never_releases_zone(rig):
    e, h, clock, sid = start_order(rig)
    h.step()
    clock.now += 11
    e.watchdog()
    snapshot = e.snapshot()
    assert snapshot["sessions"][sid]["state"] == "ERROR"
    assert snapshot["zones"]["load-a"]["owner"]
    e.heartbeat(h.gateway_id)
    assert e.snapshot()["sessions"][sid]["state"] == "ERROR"


def test_command_timeout_is_unknown_not_success(rig):
    e, h, clock, sid = start_order(rig)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    clock.now += 121
    e.heartbeat(h.gateway_id)
    e.watchdog()
    assert command(e.snapshot(), "PICK")["status"] == "UNCERTAIN"
    assert not e.snapshot()["sessions"][sid]["inventory"]


def test_stale_stop_blocks_arm_dispatch(rig):
    e, h, clock, sid = start_order(rig)
    h.until(lambda s: command(s, "PICK", "CREATED") is not None)
    clock.now += 301
    e.heartbeat(h.gateway_id)
    assert e.claim(h.gateway_id) is None
    assert e.snapshot()["sessions"][sid]["state"] == "ERROR"
    assert command(e.snapshot(), "PICK")["status"] == "CANCELLED"


def test_order_retry_idempotence_and_checkout_closes_new_orders(rig):
    e, _, _, sid = start_order(rig)
    before = len(e.snapshot()["tasks"])
    e.checkout(sid)
    order(e, sid)  # same request ID after a lost response is still readable
    assert len(e.snapshot()["tasks"]) == before
    with pytest.raises(DomainError):
        order(e, sid, request_id="new-order-002")
    with pytest.raises(DomainError):
        order(e, sid, quantity=2)


def test_pick_failure_injection_does_not_add_items(rig):
    e, h, _, sid = start_order(rig)
    e.inject_failure("omx-a", "PICK_FAIL")
    h.until(lambda s: s["sessions"][sid]["state"] == "ERROR")
    assert e.snapshot()["sessions"][sid]["inventory"] == []


def test_server_restart_retains_ownership_without_replay(tmp_path):
    path = str(tmp_path / "restart.db")
    clock = Clock()
    e = Engine(path, clock)
    h = Harness(e)
    sid = e.create_session("A")["session_id"]
    order(e, sid)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    owner = e.snapshot()["zones"]["load-a"]["owner"]
    e.store.close()
    restarted = Engine(path, clock)
    try:
        restarted.heartbeat("new-gateway-id")
        snapshot = restarted.snapshot()
        assert snapshot["sessions"][sid]["state"] == "RECOVERY_REQUIRED"
        assert snapshot["zones"]["load-a"]["owner"] == owner
        assert restarted.claim("new-gateway-id") is None
        assert snapshot["sessions"][sid]["inventory"] == []
    finally:
        restarted.store.close()


def test_gateway_restart_blocks_active_work(rig):
    e, h, _, sid = start_order(rig)
    h.step()
    e.heartbeat("replacement-gateway")
    assert e.snapshot()["sessions"][sid]["state"] == "ERROR"
    assert e.snapshot()["zones"]["load-a"]["owner"]


def test_full_two_customer_flow_and_robot_release(rig):
    e, h, _ = rig
    a, b = [e.create_session(name)["session_id"] for name in ["A", "B"]]
    order(e, a, quantity=2)
    order(e, b, request_id="B-order-001")
    order(e, b, sku="DEMO-SNACK", request_id="B-order-002")
    e.checkout(a)
    e.checkout(b)
    observed_wait = False
    for _ in range(200):
        snapshot = e.snapshot()
        observed_wait |= bool(snapshot["zones"]["load-a"]["queue"])
        for sid in [a, b]:
            session = snapshot["sessions"][sid]
            if session["current_task"]:
                task = snapshot["tasks"][session["current_task"]]
                if task["state"] == "WAIT_BASKET":
                    e.basket_ready(sid, task["id"], session["basket_id"])
        if all(s["state"] == "COMPLETED" and s["current_task"] is None for s in e.snapshot()["sessions"].values()):
            break
        assert h.step()
    else:
        pytest.fail("full scenario exceeded step budget")
    snapshot = e.snapshot()
    assert observed_wait
    assert all(z["owner"] is None for z in snapshot["zones"].values())
    for sid in [a, b]:
        assert len(snapshot["sessions"][sid]["inventory"]) == 2
        assert all(i["delivered"] for i in snapshot["sessions"][sid]["inventory"])
        assert len(h.world.data["delivered"][snapshot["sessions"][sid]["basket_id"]]) == 2
    assert all(r["session_id"] is None for r in snapshot["robots"].values())


def test_conflicting_duplicate_cannot_rewrite_result(rig):
    e, h, _, _ = start_order(rig)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    cmd = command(e.snapshot(), "PICK")
    event = h.world.execute(cmd)
    e.event(event)
    altered = deepcopy(event)
    altered["data"] = {"confirmed_items": []}
    with pytest.raises(DomainError):
        e.event(altered)
    altered["event_id"] = str(uuid.uuid4())
    with pytest.raises(DomainError):
        e.event(altered)


def test_new_mock_run_archives_old_data_and_invalidates_customers(rig):
    e, _, _ = rig
    customer = e.create_session("A")
    old_run = e.snapshot()["run_id"]
    e.reset_mock()
    assert e.snapshot()["run_id"] != old_run
    assert e.store.db.execute("SELECT count(*) FROM archived_runs WHERE run_id=?", (old_run,)).fetchone()[0] == 1
    with pytest.raises(DomainError):
        e.authenticate_customer(customer["token"])


@pytest.mark.parametrize("offset", [-301, 10])
def test_old_or_future_stop_observation_is_rejected(rig, offset):
    e, h, clock, _ = start_order(rig)
    h.until(lambda s: command(s, "NAVIGATE", "SUCCEEDED") is not None)
    cmd = command(e.snapshot(), "NAVIGATE")
    event = make_event(cmd, "STOPPED", {"stopped": True, "zone_id": "load-a"}, observed_at=clock() + offset)
    with pytest.raises(DomainError):
        e.event(event)
    assert command(e.snapshot(), "PICK") is None


def test_partial_handoff_failure_never_completes_shopping(rig):
    e, h, _, sid = start_order(rig, quantity=2)
    e.checkout(sid)
    h.until(lambda s: any(t["state"] == "WAIT_BASKET" for t in s["tasks"].values()))
    session = e.snapshot()["sessions"][sid]
    e.basket_ready(sid, session["current_task"], session["basket_id"])
    h.until(lambda s: command(s, "HANDOFF", "ACCEPTED") is not None)
    cmd = command(e.snapshot(), "HANDOFF")
    event = make_event(cmd, "FAILED", {"confirmed_items": cmd["items"][:1], "basket_id": cmd["basket_id"], "reason": "부분 인계 실패"})
    e.event(event)
    assert e.event({**event, "event_id": str(uuid.uuid4())})["duplicate"]
    session = e.snapshot()["sessions"][sid]
    assert session["state"] == "ERROR" and session["completed_at"] is None
    assert sum(i["delivered"] for i in session["inventory"]) == 1
    assert e.snapshot()["zones"]["handoff"]["owner"] == cmd["task_id"]


def test_transaction_failure_rolls_back_memory_and_quantity(rig, monkeypatch):
    e, h, _, sid = start_order(rig)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    cmd = command(e.snapshot(), "PICK")
    def disk_failure(*_):
        raise OSError("simulated disk error")
    monkeypatch.setattr(e.store, "save", disk_failure)
    with pytest.raises(OSError):
        e.event(make_event(cmd, "SUCCEEDED", {"confirmed_items": cmd["items"]}))
    assert e.snapshot()["sessions"][sid]["inventory"] == []
    assert command(e.snapshot(), "PICK")["status"] == "ACCEPTED"


def test_sqlite_failure_rolls_back_ledger_audit_and_checkpoint(rig):
    import sqlite3
    e, h, _, sid = start_order(rig)
    h.until(lambda s: command(s, "PICK", "ACCEPTED") is not None)
    cmd = command(e.snapshot(), "PICK")
    persisted = e.store.load()
    audits = e.store.db.execute("SELECT count(*) FROM audit").fetchone()[0]
    e.store.db.execute("CREATE TRIGGER reject_movement BEFORE INSERT ON movements "
                       "BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END")
    result = make_event(cmd, "SUCCEEDED", {"confirmed_items": cmd["items"]})
    with pytest.raises(sqlite3.IntegrityError):
        e.event(result)
    assert e.store.load() == persisted
    assert e.store.db.execute("SELECT count(*) FROM audit").fetchone()[0] == audits
    assert e.store.db.execute("SELECT count(*) FROM movements").fetchone()[0] == 0
    assert e.snapshot()["sessions"][sid]["inventory"] == []
    e.store.db.execute("DROP TRIGGER reject_movement")
    assert not e.event(result)["duplicate"]
    assert len(e.snapshot()["sessions"][sid]["inventory"]) == 1
