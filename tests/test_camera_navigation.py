import json
import math
import socketserver
import sys
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from robot_gateway.hardware import camera_navigation as camera


def test_two_marker_ids_front_directions_and_missing_marker():
    robots = {f'P{i+1}': dict(robot=f'P{i+1}', dictionary='DICT_5X5_1000', marker_id=i, height_m=.143,
                            front_yaw_from_edge=angle, base_to_marker_m=[0, 0])
              for i, angle in enumerate([math.pi, 1.5*math.pi])}
    markers = [dict(dictionary='DICT_5X5_1000', marker_id=i,
                    corners=[[i, 0], [i+.08, 0], [i+.08, -.08], [i, -.08]]) for i in range(2)]
    calibration = dict(image_to_map=np.eye(3).tolist(), plane_height_m=.143)
    result = camera.frame_observation(markers, calibration, robots, dict(x=0, y=0, yaw=math.pi/2), 100)
    assert math.isclose(result['robots']['pinky-1']['layout_pose']['yaw'], math.pi/2)
    assert math.isclose(result['robots']['pinky-2']['map_pose']['yaw'], -math.pi/2)
    result = camera.frame_observation(markers[:1], calibration, robots, dict(x=0, y=0, yaw=0), 101)
    assert result['robots']['pinky-2'] == {'visible': False, 'marker_id': 1}


def test_socket_disconnect_does_not_return_saved_pose(tmp_path):
    path = tmp_path/'test.sock'
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b'{"running":true,"robots":{"pinky-1":{"visible":true}}}\n')
    with socketserver.UnixStreamServer(str(path), Handler) as server:
        worker = threading.Thread(target=server.handle_request); worker.start()
        assert camera.observation(path)['robots']['pinky-1']['visible']
        worker.join()
    assert camera.observation(path) == {'running': False, 'robots': {}}


@pytest.mark.parametrize('acked',[True,False])
def test_correction_publishes_without_service_response_wait(monkeypatch,acked):
    def request():
        return SimpleNamespace(header=SimpleNamespace(), pose=SimpleNamespace(
            covariance=[0.]*36, pose=SimpleNamespace(position=SimpleNamespace(), orientation=SimpleNamespace())))
    monkeypatch.setitem(sys.modules, 'geometry_msgs.msg', SimpleNamespace(PoseWithCovarianceStamped=request))
    monkeypatch.setitem(sys.modules, 'rclpy.duration', SimpleNamespace(Duration=lambda **kwargs: kwargs))
    pose = dict(x=.4, y=.9, yaw=math.pi/2)
    monkeypatch.setattr(camera, 'observation', lambda _: {'running': True, 'observed_at': 100,
        'robots': {'pinky-1': {'visible': True, 'map_pose': pose}}})
    sent = []
    publisher = SimpleNamespace(get_subscription_count=lambda:1,publish=sent.append,
        wait_for_all_acked=lambda **kwargs: acked)
    mobile = SimpleNamespace(profile=dict(camera_socket='unused', robot_id='pinky-1', frame_id='map'),
        camera_initial_pose=publisher, data_lock=threading.Lock(), last_odom=SimpleNamespace(header=SimpleNamespace(stamp=123)))
    result=camera.correct_mobile(mobile)
    assert result['published'] is True and result['transport_acked'] is acked
    assert 'applied' not in result
    assert sent[0].header.stamp == 123
    assert sent[0].pose.pose.position.x == .4
    assert math.isclose(sent[0].pose.pose.orientation.z, math.sqrt(.5))
    monkeypatch.setattr(camera, 'observation', lambda _: {'running': False, 'robots': {}})
    assert not camera.correct_mobile(mobile)['published']
    assert len(sent) == 1


def test_admin_camera_endpoint_auth_and_read_only(rig, monkeypatch):
    from fastapi.testclient import TestClient
    from server.api import create_app
    value = {'running': True, 'robots': {'pinky-1': {'visible': False}}}
    monkeypatch.setattr(camera, 'observation', lambda: value)
    with TestClient(create_app(rig[0], 'test-admin-token-0001', 'test-gateway-token-0002')) as client:
        assert client.get('/api/admin/field/camera-position').status_code == 401
        response = client.get('/api/admin/field/camera-position', headers={
            'Authorization': 'Bearer test-admin-token-0001'}).json()
        assert response['running'] == value['running']
        assert response['robots'] == value['robots']
        assert response['basket_scale'] == .7
        assert response['wait_tolerance'] == {'position_m': .03, 'yaw_deg': 7}
