"""Planar footprint utilities, independent of Isaac and ROS."""
import math


def transform(points, pose):
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    return [(x + c*a - s*b, y + s*a + c*b) for a, b in points]


def footprint(config, pose, margin=0.0):
    # Conservative rectangle includes robot AND the rigid rear basket.
    front = config['sim_asset']['front_x'] + margin
    rear = config['sim_asset']['rear_x'] - config['basket_length'] - margin
    half = max(0.1101, config['basket_width']) / 2 + margin
    return transform([(rear, -half), (front, -half), (front, half), (rear, half)], pose)


def overlaps(a, b):
    """SAT for convex polygons; touching counts as conflict."""
    for polygon in (a, b):
        for p, q in zip(polygon, polygon[1:] + polygon[:1]):
            axis = (p[1]-q[1], q[0]-p[0])
            pa = [x*axis[0] + y*axis[1] for x, y in a]
            pb = [x*axis[0] + y*axis[1] for x, y in b]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True


def rectangle(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def obstacles(config):
    t = config['assumptions']['partition_thickness'] / 2
    return [rectangle(x-t, -config['station_depth'], x+t, 0) for x in (.6, 1.2)]


def valid_pose(config, pose, margin=0.0):
    polygon = footprint(config, pose, margin)
    return (all(0 <= x <= config['width'] and -config['depth'] <= y <= 0 for x, y in polygon)
            and not any(overlaps(polygon, wall) for wall in obstacles(config)))


def dock_pose(config, station):
    """Robot faces aisle (-Y); rear junction is at wall distance, not robot origin."""
    x = sum(config['station_widths'][:station]) + config['station_widths'][station] / 2
    y = -config['junction_wall_distances'][station] + config['sim_asset']['rear_x']
    return x, y, -math.pi/2
