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


def test_connection_uses_hybrid_planner_current_pose_and_body_headings():
    mobile = PinkyMobile.__new__(PinkyMobile)
    mobile.profile = {'frame_id':'map', 'entry_planner_id':'BasketEntry'}
    def goal():
        return SimpleNamespace(goal=SimpleNamespace(header=SimpleNamespace(),
            pose=SimpleNamespace(position=SimpleNamespace(), orientation=SimpleNamespace())))
    mobile.planner_type = SimpleNamespace(Goal=goal)
    # Body heading remains forward even though this piece moves backward.
    points = [SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=x,y=0.),
        orientation=SimpleNamespace(x=0.,y=0.,z=0.,w=1.))) for x in [1.,.9,.8]]
    result = SimpleNamespace(status=4,result=SimpleNamespace(error_code=0,error_msg='',
        path=SimpleNamespace(poses=points)))
    handle = SimpleNamespace(accepted=True,get_result_async=lambda:ready(result))
    mobile.planner_action = Mock()
    mobile.planner_action.send_goal_async.return_value = ready(handle)
    poses = mobile._plan_connection([.8,0.,0.],threading.Event(),lambda _:None,Mock())
    request = mobile.planner_action.send_goal_async.call_args.args[0]
    assert request.planner_id == 'BasketEntry' and request.use_start is False
    assert request.goal.header.frame_id == 'map'
    assert poses == [[1.,0.,0.],[.9,0.,0.],[.8,0.,0.]]


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
