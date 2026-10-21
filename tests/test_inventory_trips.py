from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import uuid

import pytest

from conftest import Harness, command, order
from robot_gateway.mock import make_event
from server.domain import DomainError, Engine


def finish(engine, harness, *, bound=450):
    for _ in range(bound):
        snapshot = engine.snapshot()
        for s in snapshot['sessions'].values():
            t = snapshot['tasks'].get(s['current_task'])
            if t and t['state'] == 'WAIT_BASKET':
                engine.basket_ready(s['id'], t['id'], s['basket_id'])
        if all(s['state'] == 'COMPLETED' and s['current_task'] is None for s in engine.snapshot()['sessions'].values()):
            return
        assert harness.step(), 'unexpected wait'
    pytest.fail('scenario did not finish')


def test_concurrent_last_item_reservation_and_cancellation(rig):
    e, _, _ = rig
    customers = [e.create_session(n)['session_id'] for n in ['A', 'B']]
    def submit(sid):
        try:
            return order(e, sid)
        except DomainError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, customers))
    winner = next(o for o in results if o)
    assert sum(o is not None for o in results) == 1
    assert e.snapshot()['stock']['SKU-JIN-RAMEN'] == {'on_hand': 1, 'reserved': 1}
    e.cancel_order(winner['session_id'], winner['id'])
    e.cancel_order(winner['session_id'], winner['id'])
    assert e.snapshot()['stock']['SKU-JIN-RAMEN'] == {'on_hand': 1, 'reserved': 0}
    loser = next(s for s in customers if s != winner['session_id'])
    assert order(e, loser)['items'] == {'SKU-JIN-RAMEN': 1}


def test_cancellation_after_navigation_dispatch_preserves_reservation(rig):
    e, h, _ = rig
    sid = e.create_session('A')['session_id']
    placed = order(e, sid)
    h.step()
    with pytest.raises(DomainError):
        e.cancel_order(sid, placed['id'])
    assert e.snapshot()['stock']['SKU-JIN-RAMEN']['reserved'] == 1


@pytest.mark.parametrize('quantity', [4, 5, 6])
def test_same_robot_multitrip_reuses_three_slots_with_unique_items(rig, quantity):
    e, h, _ = rig
    sid = e.create_session('A')['session_id']
    robot = e.snapshot()['sessions'][sid]['robot_id']
    order(e, sid, 'SKU-RICE-CHIP', quantity)
    assert e.snapshot()['stock']['SKU-RICE-CHIP'] == {'on_hand': 8, 'reserved': quantity}
    h.until(lambda s: len(s['sessions'][sid]['inventory']) == 3 and s['sessions'][sid]['current_task'] is None)
    assert not h.step()  # Customer has not closed shopping; no automatic intermediate handoff.
    e.checkout(sid)
    finish(e, h)
    snapshot = e.snapshot()
    assert len(snapshot['trips']) == 2
    assert {t['robot_id'] for t in snapshot['tasks'].values()} == {robot}
    assert all(t['state'] == 'DONE' for t in snapshot['trips'].values())
    items = snapshot['sessions'][sid]['inventory']
    assert len(items) == len({i['item_id'] for i in items}) == quantity
    assert {i['slot'] for i in items} == {0, 1, 2}
    assert all(i['delivered'] for i in items)
    assert snapshot['stock']['SKU-RICE-CHIP'] == {'on_hand': 8 - quantity, 'reserved': 0}
    assert snapshot['sessions'][sid]['receipt_confirmed_at'] is None


def test_total_shopping_can_exceed_six_but_each_order_cannot(rig):
    e, h, _ = rig
    sid = e.create_session('A')['session_id']
    with pytest.raises(DomainError):
        order(e, sid, 'SKU-RICE-CHIP', 7)
    order(e, sid, 'SKU-RICE-CHIP', 6)
    order(e, sid, 'SKU-RICE-CHIP', 2, request_id='additional-order')
    e.checkout(sid)
    finish(e, h)
    assert len(e.snapshot()['sessions'][sid]['inventory']) == 8
    assert len(e.snapshot()['trips']) == 3


@pytest.mark.parametrize('missing', ['cart_visible', 'cart_empty', 'last_item_placed', 'standby_reached'])
def test_missing_handoff_evidence_and_stop_ack_never_allow_departure(rig, missing):
    e, h, _ = rig
    sid = e.create_session('A')['session_id']
    order(e, sid)
    e.checkout(sid)
    h.until(lambda s: any(t['state'] == 'WAIT_BASKET' for t in s['tasks'].values()))
    session = e.snapshot()['sessions'][sid]
    e.basket_ready(sid, session['current_task'], session['basket_id'])
    h.until(lambda s: command(s, 'HANDOFF', 'ACCEPTED') is not None)
    handoff = command(e.snapshot(), 'HANDOFF')
    ready = h.world.execute(handoff)
    with pytest.raises(DomainError):
        e.event(make_event(handoff, 'SUCCEEDED', ready['data']))
    incomplete = deepcopy(ready)
    incomplete['data'][missing] = False
    with pytest.raises(DomainError):
        e.event(incomplete)
    assert not e.snapshot()['sessions'][sid]['inventory'][0]['delivered']
    e.event(ready)
    assert e.event(ready)['duplicate']
    assert e.snapshot()['sessions'][sid]['completed_at'] is None
    with pytest.raises(DomainError):
        e.event(make_event(handoff, 'ARM_CLEAR', {'clear': True}))
    h.until(lambda s: command(s, 'STOP_POLICY', 'ACCEPTED') is not None)
    stop = command(e.snapshot(), 'STOP_POLICY')
    for data in [{'policy_stopped': True}, {'policy_stopped': True, 'motion_stopped': True,
                 'hold_confirmed': True, 'torque_enabled': False}]:
        with pytest.raises(DomainError):
            e.event(make_event(stop, 'SUCCEEDED', data))
    assert e.snapshot()['sessions'][sid]['completed_at'] is None
    finish(e, h)


def test_reserving_six_rice_chips_leaves_two_and_other_products_for_second_customer(rig):
    e, _, _ = rig
    first = e.create_session('A')['session_id']
    second = e.create_session('B')['session_id']
    order(e, first, 'SKU-RICE-CHIP', 6)
    with pytest.raises(DomainError):
        order(e, second, 'SKU-RICE-CHIP', 3)
    order(e, second, 'SKU-RICE-CHIP', 2)
    order(e, second, 'SKU-JIN-RAMEN', 1, request_id='other-product')
    assert e.snapshot()['stock']['SKU-RICE-CHIP'] == {'on_hand': 8, 'reserved': 8}
    assert e.snapshot()['stock']['SKU-JIN-RAMEN'] == {'on_hand': 1, 'reserved': 1}


def test_replayed_old_trip_item_cannot_occupy_reused_slot(rig):
    e, h, _ = rig
    sid = e.create_session('A')['session_id']
    order(e, sid, 'SKU-RICE-CHIP', 4)
    e.checkout(sid)
    h.until(lambda s: command(s, 'PICK', 'ACCEPTED') is not None)
    old = command(e.snapshot(), 'PICK')
    # Advance until the second trip reaches its PICK command.
    for _ in range(200):
        snapshot = e.snapshot()
        session = snapshot['sessions'][sid]
        task = snapshot['tasks'].get(session['current_task'])
        if task and task['state'] == 'WAIT_BASKET':
            e.basket_ready(sid, task['id'], session['basket_id'])
        new = next((c for c in snapshot['commands'].values() if c['kind'] == 'PICK'
                    and c['status'] == 'ACCEPTED' and c['id'] != old['id']), None)
        if new:
            break
        assert h.step()
    else:
        pytest.fail('second trip missing')
    with pytest.raises(DomainError):
        e.event(make_event(new, 'SUCCEEDED', {'confirmed_items': old['items'][:1]}))
    assert e.snapshot()['stock']['SKU-RICE-CHIP']['on_hand'] == 5
    finish(e, h)


def test_restart_preserves_reservations_and_blocks_automatic_reset(tmp_path):
    path = str(tmp_path / 'stock.db')
    e = Engine(path)
    sid = e.create_session('A')['session_id']
    order(e, sid, 'SKU-RICE-CHIP', 5)
    before = deepcopy(e.state['stock'])
    e.store.close()
    e = Engine(path)
    try:
        assert e.state['stock'] == before
        with pytest.raises(DomainError):
            e.reset_mock()
        e.reset_mock(acknowledge_unresolved=True)
        assert e.state['stock']['SKU-RICE-CHIP'] == {'on_hand': 8, 'reserved': 0}
    finally:
        e.store.close()
