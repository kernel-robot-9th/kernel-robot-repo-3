"""Overview-camera geometry only: no ROS, camera opening or motor commands."""
import math

import cv2
import numpy as np

from .aruco_parking import wrap


def project(points, matrix):
    return cv2.perspectiveTransform(np.float64([points]), np.float64(matrix))[0]


def layout_to_map(points, transform):
    c, s = math.cos(transform['yaw']), math.sin(transform['yaw'])
    return np.asarray(points) @ np.array([[c, s], [-s, c]]) + [transform['x'], transform['y']]


def map_pixel(points, metadata, height, inverse=False):
    """ROS map image cell centres, including non-zero YAML origin rotation."""
    x, y, yaw = metadata['origin']
    c, s = math.cos(yaw), math.sin(yaw)
    rotation = np.array([[c, -s], [s, c]])
    if inverse:
        local = (np.asarray(points)-[x, y]) @ rotation / metadata['resolution']
        return np.column_stack((local[:, 0]-.5, height-.5-local[:, 1]))
    pixels = np.asarray(points)
    local = np.column_stack((pixels[:, 0]+.5, height-.5-pixels[:, 1]))
    return local * metadata['resolution'] @ rotation.T + [x, y]


def fit_plane(points):
    source = np.float64([p['pixel'] for p in points])
    target = np.float64([p['map_xy'] for p in points])
    if len(points) < 4:
        raise ValueError('평면 대응점 4개 이상이 필요합니다.')
    matrix, _ = cv2.findHomography(source, target, method=0)
    if matrix is None or np.linalg.matrix_rank(matrix) < 3:
        raise ValueError('일직선이 아닌 넓게 분포한 대응점을 선택하세요.')
    errors = np.linalg.norm(project(source, matrix)-target, axis=1)
    return matrix.tolist(), {'fit_rms_m': float(np.sqrt(np.mean(errors**2))),
                             'fit_max_m': float(errors.max()), 'point_errors_m': errors.tolist()}


def marker_pose(marker, calibration, robot=None):
    corners = project(marker['corners'], calibration['image_to_map'])
    center = corners.mean(axis=0)
    edge = corners[1]-corners[0]
    result = {'dictionary': marker['dictionary'], 'marker_id': marker['marker_id'],
              'marker_xy': center.tolist(), 'marker_edge_yaw': math.atan2(edge[1], edge[0]),
              'measured_marker_size_m': float(np.mean(np.linalg.norm(
                  np.roll(corners, -1, axis=0)-corners, axis=1))), 'base_pose': None}
    if robot:
        result['robot'] = robot['robot']
        result['yaw'] = wrap(result['marker_edge_yaw']+robot['front_yaw_from_edge'])
        # A different roof height needs its own plane; do not label a wrong plane as map pose.
        result['height_matches_plane'] = math.isclose(
            robot['height_m'], calibration['plane_height_m'], abs_tol=1e-6)
        offset = robot.get('base_to_marker_m')
        if offset is not None and result['height_matches_plane']:
            c, s = math.cos(result['yaw']), math.sin(result['yaw'])
            delta = np.array([[c, -s], [s, c]]) @ np.array(offset)
            result['base_pose'] = dict(zip(('x', 'y', 'yaw'), [*(center-delta), result['yaw']]))
    return result
