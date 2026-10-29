"""Perspective, ROS map rotation and real OpenCV detector compatibility checks."""
import math
import json
from pathlib import Path
import unittest
import sys

import cv2
import numpy as np

from robot_gateway.hardware.aruco_parking import detect_markers, front_angle
from robot_gateway.hardware.overhead import fit_plane, map_pixel, marker_pose, project
from scripts.pinky_overhead import select_anchor


def test_number_keys_record_four_points_and_save_calibration(tmp_path, monkeypatch):
    from scripts.pinky_overhead import main
    map_file = tmp_path/'map.png'
    cv2.imwrite(str(map_file), np.full((400, 500, 3), 255, np.uint8))
    (tmp_path/'map.yaml').write_text('image: map.png\nresolution: 0.01\norigin: [-1, -2, 0]\n')
    (tmp_path/'registry.json').write_text(json.dumps({'layout_to_map': {'x': 0, 'y': 0, 'yaw': 0}}))
    config = {'output_directory': str(tmp_path/'out'), 'camera': {},
              'calibration_file': str(tmp_path/'out/calibration.json'),
              'robots_file': str(tmp_path/'out/robots.json'), 'layout_registry': str(tmp_path/'registry.json'),
              'map_yaml': str(tmp_path/'map.yaml'), 'dictionary': 'DICT_5X5_1000'}
    (tmp_path/'config.json').write_text(json.dumps(config))
    book = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_1000)
    code = (cv2.aruco.generateImageMarker(book, 0, 70) if hasattr(cv2.aruco, 'generateImageMarker')
            else cv2.aruco.drawMarker(book, 0, 70))
    images = []
    for x, y in [(60, 60), (360, 60), (60, 260), (360, 260)]:
        frame = np.full((400, 500), 255, np.uint8)
        frame[y:y+70, x:x+70] = code
        images.append(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))
    position = [0]
    original_read = cv2.imread
    monkeypatch.setattr(cv2, 'imread', lambda path: images[position[0]].copy() if path == 'test-camera' else original_read(path))
    keys = iter([ord('1'), 13, ord('2'), 13, ord('3'), 13, ord('4'), 13, ord('s'), ord('q')])
    def keypress(*_):
        key = next(keys)
        if key == 13:
            position[0] = min(position[0]+1, 3)
        return key
    for name in ['namedWindow', 'setMouseCallback', 'imshow', 'destroyAllWindows']:
        monkeypatch.setattr(cv2, name, lambda *a, **k: None)
    monkeypatch.setattr(cv2, 'waitKey', keypress)
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *_: (_ for _ in ()).throw(AssertionError('no live camera')))
    monkeypatch.setattr(sys, 'argv', ['pinky_overhead', 'calibrate', '--config', str(tmp_path/'config.json'),
                        '--anchors-file', 'config/pinky-overhead-anchors.example.json',
                        '--plane-height-mm', '143', '--marker-id', '0', '--image', 'test-camera'])
    main()
    saved = json.loads((tmp_path/'out/calibration.json').read_text())
    assert saved['plane_height_m'] == .143
    assert [p['anchor_id'] for p in saved['points']] == [1, 2, 3, 4]
    assert saved['fit_max_m'] < 1e-5


class OverheadGeometryTest(unittest.TestCase):
    def test_field_anchors_match_tape_distances_and_stay_in_aisle(self):
        config = json.loads(Path('config/pinky-overhead-anchors.example.json').read_text())
        self.assertEqual(config['plane_height_mm'], 143)
        self.assertEqual([a['id'] for a in config['points']], [1, 2, 3, 4])
        for anchor in config['points']:
            x, y = anchor['layout_xy']
            self.assertAlmostEqual(x, anchor['from_left_mm']/1000)
            self.assertAlmostEqual(config['depth_m']+y, anchor['from_waiting_edge_mm']/1000)
            self.assertLess(y, -.75)

    def test_numbered_anchor_uses_perspective_marker_centre_and_registered_map(self):
        h = np.array([[.002, -.0003, -.5], [.0001, -.002, 1.8], [.00005, .0001, 1.]])
        transform = {'x': .1, 'y': .2, 'yaw': -.4}
        anchor = {'id': 3, 'layout_xy': [.3, -1.3]}
        x, y = anchor['layout_xy']
        center = np.array([.1+math.cos(-.4)*x-math.sin(-.4)*y,
                           .2+math.sin(-.4)*x+math.cos(-.4)*y])
        world = np.array([[-.04, .04], [.04, .04], [.04, -.04], [-.04, -.04]])+center
        marker = {'corners': project(world, np.linalg.inv(h)).tolist()}
        selected = select_anchor(anchor, marker, transform)
        np.testing.assert_allclose(selected['map_xy'], center, atol=1e-10)
        np.testing.assert_allclose(project([selected['pixel']], h)[0], center, atol=2e-6)
        self.assertEqual(selected['anchor_id'], 3)

    def test_perspective_fit_at_independent_point(self):
        camera_to_map = np.array([[.002, -.0003, -.5], [.0001, -.002, 1.8], [.00005, .0001, 1.]])
        image = np.array([[90, 80], [900, 100], [1100, 620], [120, 650], [550, 170], [700, 490]])
        world = project(image, camera_to_map)
        matrix, residual = fit_plane([{'pixel': a.tolist(), 'map_xy': b.tolist()} for a, b in zip(image, world)])
        unseen = [[345, 430]]
        np.testing.assert_allclose(project(unseen, matrix), project(unseen, camera_to_map), atol=1e-6)
        self.assertLess(residual['fit_rms_m'], 1e-6)

    def test_rotated_map_origin_and_cell_centre(self):
        metadata = {'origin': [1.2, -.4, math.pi/6], 'resolution': .01}
        points = [[0, 299], [15, 18], [37.5, 213.8]]
        world = map_pixel(points, metadata, 300)
        expected = np.array([1.2, -.4])+.005*np.array([math.cos(math.pi/6)-math.sin(math.pi/6),
                                                                     math.sin(math.pi/6)+math.cos(math.pi/6)])
        np.testing.assert_allclose(world[0], expected)
        np.testing.assert_allclose(map_pixel(world, metadata, 300, inverse=True), points, atol=1e-10)

    def test_roof_marker_front_direction_and_base_offset(self):
        h = np.array([[.002, -.0003, -.5], [.0001, -.002, 1.8], [.00005, .0001, 1.]])
        yaw, front_offset = -.3, .6
        c, s = math.cos(yaw), math.sin(yaw)
        rotation = np.array([[c, -s], [s, c]])
        base = np.array([.7, .5])
        offset = [.04, -.012]
        center = base+rotation@offset
        a = yaw-front_offset
        rotation = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        world = np.array([[-.04, .04], [.04, .04], [.04, -.04], [-.04, -.04]])@rotation.T+center
        marker = {'dictionary': 'DICT_4X4_1000', 'marker_id': 17,
                  'corners': project(world, np.linalg.inv(h)).tolist()}
        robot = {'robot': 'P1', 'height_m': .17, 'base_to_marker_m': offset,
                 'front_yaw_from_edge': front_offset}
        pose = marker_pose(marker, {'image_to_map': h, 'plane_height_m': .17}, robot)
        np.testing.assert_allclose(list(pose['base_pose'].values()), [*base, yaw], atol=1e-9)
        front_pixel = project([center+.1*np.array([c, s])], np.linalg.inv(h))[0]
        self.assertAlmostEqual(front_angle(marker, front_pixel), front_offset, places=5)
        wrong_height = marker_pose(marker, {'image_to_map': h, 'plane_height_m': .12}, robot)
        self.assertIsNone(wrong_height['base_pose'])

    def test_installed_opencv_detects_rotated_marker(self):
        book = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000)
        code = (cv2.aruco.generateImageMarker(book, 17, 160) if hasattr(cv2.aruco, 'generateImageMarker')
                else cv2.aruco.drawMarker(book, 17, 160))
        image = np.full((400, 400), 255, np.uint8)
        image[120:280, 120:280] = code
        rotated = cv2.warpAffine(image, cv2.getRotationMatrix2D((200, 200), 28, 1), (400, 400), borderValue=255)
        markers = detect_markers(cv2.cvtColor(rotated, cv2.COLOR_GRAY2BGR), 'DICT_4X4_1000')
        self.assertEqual([m['marker_id'] for m in markers], [17])


if __name__ == '__main__':
    unittest.main()
