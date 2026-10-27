from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock
import threading

import pytest

from robot_gateway.hardware.pinky import PinkyMobile


def ready(value):
    future = Future()
    future.set_result(value)
    return future


@pytest.mark.parametrize('lost_phase', ['acceptance', 'result'])
def test_only_missing_route_response_is_retried_once(lost_phase):
    mobile = PinkyMobile.__new__(PinkyMobile)
    result = object()
    good = SimpleNamespace(accepted=True, get_result_async=lambda: ready(result))
    lost = (Future() if lost_phase == 'acceptance' else
            ready(SimpleNamespace(accepted=True, get_result_async=Future)))
    mobile.route_action = Mock()
    mobile.route_action.send_goal_async.side_effect = [lost, ready(good)]
    def wait(future, cancelled, timeout):
        if not future.done():
            raise TimeoutError()
        return future.result()
    mobile._await = wait
    value = mobile._compute_route(SimpleNamespace(start_id=1, goal_id=2),
                                  threading.Event(), lambda future: None, Mock())
    assert value is result
    assert mobile.route_action.send_goal_async.call_count == 2


def test_missing_response_twice_stops_retrying():
    mobile = PinkyMobile.__new__(PinkyMobile)
    mobile.route_action = Mock()
    mobile.route_action.send_goal_async.side_effect = [Future(), Future()]
    mobile._await = Mock(side_effect=TimeoutError)
    with pytest.raises(RuntimeError, match='재요청 1회도 응답 누락'):
        mobile._compute_route(SimpleNamespace(start_id=1, goal_id=2),
                              threading.Event(), lambda future: None, Mock())
    assert mobile.route_action.send_goal_async.call_count == 2


def test_rejected_route_is_not_retried():
    mobile = PinkyMobile.__new__(PinkyMobile)
    mobile.route_action = Mock()
    mobile.route_action.send_goal_async.return_value = ready(SimpleNamespace(accepted=False))
    with pytest.raises(RuntimeError, match='경로 요청 거부'):
        mobile._compute_route(SimpleNamespace(start_id=1, goal_id=2),
                              threading.Event(), lambda future: None, Mock())
    assert mobile.route_action.send_goal_async.call_count == 1


def test_response_wait_can_expire_without_waiting_in_real_time(monkeypatch):
    clock = iter([0., 9.])
    monkeypatch.setattr('robot_gateway.hardware.pinky.time.monotonic', lambda: next(clock))
    with pytest.raises(TimeoutError):
        PinkyMobile._await(Future(), threading.Event(), timeout=8)
