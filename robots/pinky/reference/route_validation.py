"""Conservative checks for the defined piecewise SE(2) paths, not real tracking.

Between endpoint poses, displacement + bounding-radius * angular displacement
bounds every footprint point's motion. Expanding the starting rectangle by that
amount conservatively encloses the interpolated sweep. This can reject safe
motions; acceptance concerns the mathematical reference and stated obstacles.
"""
import math
from .geometry import footprint, obstacles, overlaps, rectangle
from .route_paths import angle_delta


def scene_obstacles(config):
    result=obstacles(config)
    w,d=config['assumptions']['shelf_width_depth']
    for i in range(3):
        x=sum(config['station_widths'][:i])+config['station_widths'][i]/2
        y=-config['arm_wall_distance']
        result.append(rectangle(x-w/2,y-d/2,x+w/2,y+d/2))
    return result


def motion_bound(config,a,b,margin):
    radius=max(math.hypot(x,y) for x,y in footprint(config,(0,0,0),margin))
    return math.dist(a[:2],b[:2])+radius*abs(angle_delta(a[2],b[2]))


def swept_box(config,a,b,margin=.02):
    return footprint(config,a,margin+motion_bound(config,a,b,margin))


def valid_polygon(config,polygon):
    return (all(0<=x<=config['width'] and -config['depth']<=y<=0 for x,y in polygon)
            and not any(overlaps(polygon,o) for o in scene_obstacles(config)))


def check_path(config,poses,margin=.02):
    if not poses: raise ValueError('Empty path')
    if not math.isfinite(margin) or margin<0: raise ValueError('Invalid margin')
    if any(len(p)!=3 or not all(math.isfinite(v) for v in p) for p in poses):
        raise ValueError('Invalid pose')
    bad=[]
    for i,(a,b) in enumerate(zip(poses,poses[1:])):
        if not valid_polygon(config,swept_box(config,a,b,margin)): bad.append(i)
    if not valid_polygon(config,footprint(config,poses[-1],margin)): bad.append(len(poses)-1)
    return {'valid':not bad,'invalid_intervals':bad[:20],'invalid_count':len(bad),
            'interval_count':max(0,len(poses)-1),'margin_m':margin}


def pair_step_clear(config,a0,a1,b0,b1,margin=.02):
    return not overlaps(swept_box(config,a0,a1,margin),swept_box(config,b0,b1,margin))
