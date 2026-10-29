import io
import json
import threading
import time
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

from robot_gateway.frames import SharedCamera
from robot_gateway.hardware import station_remote
from robot_gateway.hardware.worker import claim_command


def test_camera_reconnect_returns_new_frames_once():
    old, fresh = Mock(), Mock()
    disconnected = threading.Event()
    class Camera:
        recovered = False
        def read(self):
            time.sleep(.005)
            if disconnected.is_set() and not self.recovered:
                raise RuntimeError('USB disconnected')
            return (fresh if self.recovered else old), time.monotonic()
        def reopen(self):
            self.recovered = True
    camera = Camera()
    shared = SharedCamera(camera, Mock(), 'load-a')
    try:
        assert shared.read()[0] == old.copy.return_value
        disconnected.set()
        deadline = time.monotonic()+1
        while not camera.recovered and time.monotonic() < deadline:
            time.sleep(.01)
        assert shared.read()[0] == fresh.copy.return_value
        assert shared.reconnected
        camera.recovered = False
        shared.thread.join(timeout=1)
        with pytest.raises(RuntimeError, match='카메라 수신 실패'):
            shared.read()
    finally:
        shared.close()


def test_camera_recovery_deadline_preserves_error(monkeypatch):
    from robot_gateway import frames
    camera = Mock()
    camera.read.side_effect = RuntimeError('disconnected')
    camera.reopen.side_effect = OSError('absent')
    # One failed reopen already consumes the recovery window.
    clock = iter([10.,16.])
    monkeypatch.setattr(frames, 'time', Mock(monotonic=lambda:next(clock)))
    shared = SharedCamera(camera, Mock(), 'load-a')
    try:
        with pytest.raises(RuntimeError, match='카메라 수신 실패'):
            shared.read()
        assert camera.reopen.call_count == 1
    finally:
        shared.close()


def test_remote_failure_keeps_completed_item_and_reason(monkeypatch):
    item = {'sku':'SKU-JIN-RAMEN','slot':0,'item_id':'first'}
    failure = {'reason':'작업대 카메라 수신 실패','executed_items':[item]}
    process = Mock(stdout=io.StringIO('CARTRINA_ERROR='+json.dumps(failure)+'\n'))
    process.wait.return_value = 1
    monkeypatch.setattr(station_remote.subprocess, 'Popen', Mock(return_value=process))
    monkeypatch.setattr(station_remote, 'station_command', lambda *a:['unused'])
    monkeypatch.setattr(station_remote, 'configuration', lambda:{'stations':{}})
    arm = station_remote.RemoteArm('B')
    with pytest.raises(station_remote.StationError, match='작업대 카메라 수신 실패') as error:
        arm.execute({'kind':'PICK'}, threading.Event())
    assert error.value.executed_items == arm.executed == [item]


@pytest.mark.parametrize('status,detail,ignored', [
    (409,'중단된 작업입니다',True), (409,'현재 중개 인스턴스 연결 미확인',False),
    (403,'인증 실패',False)])
def test_only_order_claim_rejection_is_idle(status, detail, ignored):
    error = HTTPError('http://local/claim',status,'rejected',{},
                      io.BytesIO(json.dumps({'detail':detail}).encode()))
    client = Mock(); client.call.side_effect = error
    if ignored:
        assert claim_command(client, {}) is None
        client.call.side_effect = None; client.call.return_value = {'command':{'kind':'STOP'}}
        assert claim_command(client, {}) == {'kind':'STOP'}
    else:
        with pytest.raises(HTTPError):
            claim_command(client, {})
