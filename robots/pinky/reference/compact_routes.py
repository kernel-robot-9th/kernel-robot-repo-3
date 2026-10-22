"""Review-only v4 candidate: short station links and a separate return lane.

Geometric references only. No ROS, camera observations or wheel controller.
The existing v3 modules and frozen deliverable deliberately remain unchanged.
"""
import math

from .geometry import dock_pose
from .route_paths import (Segment, arc, bezier, line, join, angle_delta,
                          HOME_BACK, HOME_FRONT, STATIONS)

ROUTE_VERSION = 4
WORK_Y = -.90
RETURN_Y = -1.15


def turn(name, pose, yaw):
    delta = angle_delta(pose[2], yaw)
    n = max(1, math.ceil(abs(delta) / .006))
    return Segment(name, [(pose[0], pose[1], pose[2] + delta*i/n)
                          for i in range(n+1)], 0)


def reverse_curve(name, control):
    forward = bezier(name, control)
    return Segment(name, [(x, y, yaw-math.pi) for x, y, yaw in forward.poses], -1)


def home_paths():
    # Arrive heading west, turn in the free space left of the queue, then east.
    x = HOME_BACK[0]
    y = HOME_BACK[1]
    radius = (RETURN_Y-y)/2
    return {'front': HOME_FRONT, 'back': HOME_BACK,
            'advance': line('queue_advance', HOME_BACK, HOME_FRONT),
            'arrival': [arc('home_return_turn', x, (RETURN_Y+y)/2,
                            radius, math.pi/2, 3*math.pi/2)]}


def home_to_station(config, station):
    i = STATIONS.index(station)
    dock = dock_pose(config, i)
    x = dock[0]
    # At the low home row, face the front towards the floor edge (short front
    # overhang) and reverse away from it. Turning the long rear towards the
    # floor edge would violate the footprint boundary.
    depart = (HOME_FRONT[0], HOME_FRONT[1], -math.pi/2)
    align = (x, WORK_Y, -math.pi/2)
    path = [turn('home_face_aisle', HOME_FRONT, depart[2]),
            reverse_curve('home_short_departure',
                          [(depart[0], depart[1]), (depart[0], -1.13),
                           (x, -1.14), (x, WORK_Y)]),
            line('dock_reverse', align, dock, -1)]
    join(path)
    return path


def transfer(config, source, target):
    a, b = STATIONS.index(source), STATIONS.index(target)
    if a >= b:
        raise ValueError('v4 candidate only supports forward A -> B -> handoff order')
    start, end = dock_pose(config, a), dock_pose(config, b)
    leave = (start[0], WORK_Y, -math.pi/2)
    east = (start[0], WORK_Y, 0.0)
    arrival = (end[0], WORK_Y, 0.0)
    reverse = (end[0], WORK_Y, -math.pi/2)
    path = [line('leave_bay', start, leave),
            turn('face_next_station', leave, 0.0),
            line('short_station_link', east, arrival),
            turn('face_docking_direction', arrival, -math.pi/2),
            line('dock_reverse', reverse, end, -1)]
    join(path)
    return path


def station_to_home(config, station, slot='back'):
    if slot not in ('front', 'back'):
        raise ValueError('Unknown home slot')
    dock = dock_pose(config, STATIONS.index(station))
    leave = (dock[0], RETURN_Y, -math.pi/2)
    west = (dock[0], RETURN_Y, -math.pi)
    home = home_paths()
    # Returns in the review scenario always originate at handoff; reverse
    # ordering / abandoned-order returns are intentionally not implemented.
    if station != 'handoff':
        raise ValueError('Only completed handoff returns are in the review scope')
    path = [line('leave_handoff', dock, leave),
            turn('face_return_lane', leave, -math.pi),
            line('return_west', west, (HOME_BACK[0], RETURN_Y, -math.pi))]
    path += home['arrival']
    if slot == 'front':
        path.append(home['advance'])
    join(path)
    return path


def route_set(config):
    paths = {'queue_advance': [home_paths()['advance']]}
    for station in STATIONS:
        paths['home_to_'+station] = home_to_station(config, station)
    for source, target in [('A', 'B'), ('A', 'handoff'), ('B', 'handoff')]:
        paths[source+'_to_'+target] = transfer(config, source, target)
    for slot in ('front', 'back'):
        paths['handoff_to_home_'+slot] = station_to_home(config, 'handoff', slot)
    return paths
