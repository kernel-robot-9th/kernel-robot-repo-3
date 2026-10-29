import json
import math
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from scripts.pinky_wait_record import run, save_target


def args(robot='P1', slot='front', **extra):
    return SimpleNamespace(**({'mode': 'wait', 'robot': robot, 'slot': slot,
        'marker_id': 0 if robot == 'P1' else 1, 'size_mm': 80., 'height_mm': None,
        'front_angle_deg': 180. if robot == 'P1' else 270.,
        'marker_forward_mm': 0., 'marker_left_mm': 0.,
        'image': None, 'headless': False, 'frames': 1} | extra))


def config(root):
    return {'output_directory': str(root), 'calibration_file': str(root/'calibration.json'),
            'camera': {'width': 400, 'height': 300, 'fps': 30, 'camera_by_id': '/unused'}}


def marker(identity=0):
    return {'dictionary': 'DICT_5X5_1000', 'marker_id': identity,
            'corners': [[100., 100.], [180., 100.], [180., 180.], [100., 180.]]}


def test_four_targets_and_reteach_preserve_other_slots(tmp_path):
    frame = np.full((300, 400, 3), 255, np.uint8)
    for slot in ['front', 'back']:
        for robot in ['P1', 'P2']:
            a = args(robot, slot)
            save_target(config(tmp_path), a, marker(a.marker_id), frame, frame)
    path = tmp_path/'wait-targets.json'
    before = json.loads(path.read_text())
    assert set(before) == {'front/P1', 'front/P2', 'back/P1', 'back/P2'}
    assert all(v['map_pose'] is None and v['frame_id'] is None for v in before.values())
    save_target(config(tmp_path), args(), marker(), frame, frame)
    after = json.loads(path.read_text())
    assert all(after[k] == before[k] for k in ['front/P2', 'back/P1', 'back/P2'])
    assert json.loads((tmp_path/'wait-targets.previous.json').read_text()) == before
    assert len(list(tmp_path.glob('*-target.png'))) == 4


def test_map_pose_requires_matching_height_and_capture_mode(tmp_path):
    frame = np.full((300, 400, 3), 255, np.uint8)
    calibration = {'image_size': [400, 300], 'plane_height_m': .18,
                   'image_to_map': [[.001, 0, 0], [0, -.001, .3], [0, 0, 1]]}
    a = args('P2', height_mm=180.)
    result = save_target(config(tmp_path), a, marker(1), frame, frame, calibration)
    assert result['map_pose']['x'] == pytest.approx(.14)
    assert result['map_pose']['y'] == pytest.approx(.16)
    assert result['map_pose']['yaw'] == pytest.approx(-math.pi/2)
    for height, size in [(None, [400, 300]), (190., [400, 300]), (180., [800, 600])]:
        a.height_mm = height
        calibration['image_size'] = size
        result = save_target(config(tmp_path), a, marker(1), frame, frame, calibration)
        assert result['map_pose'] is None


def test_terminal_enter_records_requested_id_from_two_markers(tmp_path, monkeypatch):
    book = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_1000)
    image = np.full((300, 500), 255, np.uint8)
    for identity, x in [(0, 40), (1, 300)]:
        image[100:200, x:x+100] = (cv2.aruco.generateImageMarker(book, identity, 100)
                                  if hasattr(cv2.aruco, 'generateImageMarker')
                                  else cv2.aruco.drawMarker(book, identity, 100))
    source = tmp_path/'source.png'
    cv2.imwrite(str(source), image)
    for name in ['namedWindow', 'imshow', 'destroyAllWindows']:
        monkeypatch.setattr(cv2, name, lambda *a, **k: None)
    monkeypatch.setattr(cv2, 'waitKey', lambda *_: 255)
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *_: pytest.fail('camera must remain unopened'))
    monkeypatch.setattr('scripts.pinky_wait_record.TerminalKeys.read', lambda _: 13)
    run(args('P2', image=str(source)), config(tmp_path))
    target = json.loads((tmp_path/'wait-targets.json').read_text())['front/P2']
    assert target['marker_id'] == 1
    assert np.asarray(target['corners'])[:, 0].mean() > 300
    assert math.degrees(target['geometry']['front_yaw_from_edge']) == pytest.approx(270)
