from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace as Obj
import threading
from unittest.mock import Mock

import pytest

from robot_gateway.hardware.pinky import PinkyMobile


@pytest.mark.parametrize('cancel', [False, True])
def test_start_waits_for_matching_tf_and_uses_that_transform(cancel):
    mobile = PinkyMobile.__new__(PinkyMobile)
    mobile.data_lock = threading.Lock()
    mobile.last_odom, mobile.map_hash = None, 'map'
    mobile.profile = {'frame_id':'map', 'base_frame':'base_footprint'}
    mobile.rclpy = Obj(time=Obj(Time=lambda: 0))
    pending, waiting, cancelled = Future(), threading.Event(), threading.Event()
    def wait(*frames):
        waiting.set()
        return pending
    mobile.buffer = Mock()
    mobile.buffer.wait_for_transform_async.side_effect = wait
    mobile.buffer.lookup_transform.side_effect = RuntimeError('TF timestamps do not overlap yet')
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(mobile.snapshot, wait_for_tf=True, cancelled=cancelled)
        assert waiting.wait(1)
        assert not result.done()
        if cancel:
            cancelled.set()
            with pytest.raises(RuntimeError, match='취소'):
                result.result(timeout=1)
        else:
            pending.set_result(Obj(header=Obj(stamp=Obj(sec=100, nanosec=20_000_000)),
                                   transform=Obj(translation=Obj(x=1., y=2., z=0.),
                                                 rotation=Obj(x=0., y=0., z=0., w=1.))))
            snapshot = result.result(timeout=1)
            assert snapshot['pose'] == {'x':1., 'y':2., 'yaw':0.}
            assert snapshot['observed_at'] == 100.02
    mobile.buffer.lookup_transform.assert_not_called()


def test_trace_uses_same_stamp_for_map_and_odom_instead_of_latest_odom_message():
    mobile = PinkyMobile.__new__(PinkyMobile)
    mobile.data_lock = threading.Lock()
    stamp = Obj(sec=100, nanosec=20_000_000)
    def transform(x):
        return Obj(header=Obj(stamp=stamp), transform=Obj(translation=Obj(x=x, y=0., z=0.),
                   rotation=Obj(x=0., y=0., z=0., w=1.)))
    mobile.last_odom = Obj(header=Obj(frame_id='odom', stamp=Obj(sec=101, nanosec=0)),
                           twist=Obj(twist=Obj(linear=Obj(x=.05), angular=Obj(z=.1))))
    mobile.map_hash = 'map'
    mobile.profile = {'frame_id':'map', 'base_frame':'base_footprint'}
    at = object()
    time_type = Mock(return_value=0)
    time_type.from_msg.return_value = at
    mobile.rclpy = Obj(time=Obj(Time=time_type))
    mobile.buffer = Mock()
    mobile.buffer.lookup_transform.side_effect = [transform(4.), transform(1.), transform(3.)]
    result = mobile.snapshot(include_odometry=True)
    calls = mobile.buffer.lookup_transform.call_args_list
    assert calls[1].args == ('odom', 'base_footprint', at)
    assert calls[2].args == ('map', 'odom', at)
    assert result['observed_at'] == 100.02
    assert result['velocity_observed_at'] == 101.
    assert result['odom_pose']['x'] == 1.
    assert result['map_to_odom']['x'] == 3.


def test_missing_trace_transform_does_not_interrupt_navigation():
    mobile = PinkyMobile.__new__(PinkyMobile)
    mobile.data_lock = threading.Lock()
    mobile.last_odom, mobile.map_hash = None, 'map'
    mobile.profile = {'frame_id':'map', 'base_frame':'base_footprint'}
    mobile.rclpy = Obj(time=Obj(Time=Mock()))
    transform = Obj(header=Obj(stamp=Obj(sec=100, nanosec=0)),
                    transform=Obj(translation=Obj(x=1., y=0., z=0.),
                                  rotation=Obj(x=0., y=0., z=0., w=1.)))
    mobile.buffer = Mock()
    mobile.buffer.lookup_transform.side_effect = [transform, RuntimeError('odom TF not yet available')]
    result = mobile.snapshot(include_odometry=True)
    assert result['pose']['x'] == 1.
    assert result['odometry_error'] == 'odom TF not yet available'
