"""C basket geometry and left/right drop planning, without hardware I/O."""
from copy import deepcopy
from pathlib import Path
import sys

PICKING = Path(__file__).resolve().parents[1] / 'omx_yolo' / 'tools' / 'picking'
if str(PICKING) not in sys.path:
    sys.path.insert(0, str(PICKING))

from pick_core import build_plan, get_rule, polygon, to_xy, vector
from omx_spatial_correction import interpolate

POSES = ('wait', 'pickup_approach', 'drop_left_approach', 'drop_left_release',
         'drop_right_approach', 'drop_right_release')


def basket_job(job, robot):
    """Selection ROI is independent of the larger calibration hull."""
    region = job['pickup_regions_uv'][robot]
    polygon(region, 'pickup_regions_uv.' + robot)
    return dict(job, regions_source='manual', regions_uv=[region])


def corrected_job(job, calibration, detection, robot):
    cfg = deepcopy(job)
    rule = get_rule(cfg, detection.label)
    base = to_xy(calibration, detection.point(rule))
    mesh = rule.get('spatial_adjustments_by_robot', {}).get(robot) or rule.get('spatial_adjustments')
    if mesh:
        dx, dy, z = interpolate(mesh, base)
        offset = vector(rule.get('xy_offset_mm', [0, 0]), 'xy_offset_mm', 2)
        rule.update(xy_offset_mm=[offset[0] + dx, offset[1] + dy], pick_z_mm=z)
    return cfg


def correction_sample(calibration, detection, rule, actual_xyz):
    """Rebuild from raw calibration + static class offset, never old interpolation."""
    raw_xy = to_xy(calibration, detection.point(rule))
    x, y, z = vector(actual_xyz, 'actual_xyz_mm', 3)
    offset = vector(rule.get('xy_offset_mm', [0, 0]), 'xy_offset_mm', 2)
    return {'xy_mm': list(raw_xy), 'correction_xyz_mm':
            [x - raw_xy[0] - offset[0], y - raw_xy[1] - offset[1], z]}


def plan(job, calibration, detection, saved, solver, robot, side, **options):
    if side not in ('left', 'right'):
        raise ValueError('주문의 basket_side는 left 또는 right여야 합니다')
    poses = {'hover_high': saved['wait'], 'shelf_approach': saved['pickup_approach'],
             'drop_approach': saved[f'drop_{side}_approach'],
             'drop_release': saved[f'drop_{side}_release']}
    result = build_plan(corrected_job(basket_job(job, robot), calibration, detection, robot),
                        calibration, detection, poses, solver, **options)
    result.update(operation='yolo_unload', robot_id=robot, basket_side=side)
    return result
