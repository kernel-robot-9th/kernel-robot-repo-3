"""Perspective, ROS map rotation and real OpenCV detector compatibility checks."""
import math
import unittest

import cv2
import numpy as np

from robot_gateway.hardware.aruco_parking import detect_markers, front_angle
from robot_gateway.hardware.overhead import fit_plane, map_pixel, marker_pose, project


class OverheadGeometryTest(unittest.TestCase):
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
