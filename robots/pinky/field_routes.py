"""Bind the pinned basket-aware v4 geometry to an explicitly registered ROS map.

This does not turn the mock ReferenceEngine into a hardware engine. Physical
execution belongs to the field adapter; route geometry does not prove parking.
"""
import hashlib
import json
import math
from pathlib import Path

from . import compact
from .reference.geometry import footprint


def registration(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    shared = None
    if value.get('shared_goals_file'):
        shared = json.loads(Path(value['shared_goals_file']).read_text(encoding='utf-8'))
        for zone, saved in shared['goals'].items():
            value['goals'][zone]['arrival'] = saved['arrival']
    if 'layout_to_map' in value:
        fixed = value['layout_to_map']
        transform = (fixed['x'], fixed['y'], fixed['yaw'])
        identity = {'map': value['map_sha256'], 'layout_to_map': fixed,
                    'source': compact.bundle()[3]}
        if shared is not None:
            identity['shared_goals'] = shared['goals']
        signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return value, transform, signature
    anchor = value['goals']['load-a']['arrival']
    reference = compact.route('home_to_A').poses[-1]
    yaw = anchor['yaw'] - reference[2]
    c, s = math.cos(yaw), math.sin(yaw)
    transform = (anchor['x']-c*reference[0]+s*reference[1],
                 anchor['y']-s*reference[0]-c*reference[1], yaw)
    signature = hashlib.sha256(json.dumps({'map': value['map_sha256'], 'anchor': anchor,
        'source': compact.bundle()[3]}, sort_keys=True).encode()).hexdigest()
    return value, transform, signature


def plan(path, route_id, *, taught_dock=True):
    if route_id in {'exit_A', 'exit_B'}:
        selected = plan(path, 'home_to_'+route_id[-1], taught_dock=taught_dock)
        dock = selected['segments'][-1]
        selected.update(route_id=route_id, segments=[{'name': 'leave_bay', 'direction': 1,
                                                    'poses': list(reversed(dock['poses']))}])
        return selected
    value, (tx, ty, angle), signature = registration(path)
    route = compact.route(route_id)
    c, s = math.cos(angle), math.sin(angle)
    def convert(pose):
        x, y, yaw = pose
        return [tx+c*x-s*y, ty+s*x+c*y,
                math.atan2(math.sin(yaw+angle), math.cos(yaw+angle))]
    if taught_dock and value.get('shared_goals_file'):
        target = next((entry['arrival'] for entry in value['goals'].values()
                      if entry.get('arrival_route_id') == route_id), None)
    else:
        target = None
    if target is not None:
        end = convert(route.poses[-1])
        correction = target['yaw'] - end[2]
        cc, ss = math.cos(correction), math.sin(correction)
        original_convert = convert
        def convert(pose):
            x, y, yaw = original_convert(pose)
            dx, dy = x-end[0], y-end[1]
            return [target['x']+cc*dx-ss*dy, target['y']+ss*dx+cc*dy,
                    math.atan2(math.sin(yaw+correction), math.cos(yaw+correction))]
    cfg = compact.bundle()[0]
    # Include the configured real body's 6cm front extent as well as the
    # reference's rear basket. These dimensions still require field approval.
    box = footprint(cfg, (0, 0, 0))
    front = max(.06, max(p[0] for p in box))
    rear = min(p[0] for p in box)
    half = max(.06, max(abs(p[1]) for p in box))
    result = {'route_id': route_id, 'route_version': 4, 'source_hash': route.source_hash,
            'registration_sha256': signature, 'map_sha256': value['map_sha256'],
            'frame_id': value['frame_id'], 'robot_id': value['robot_id'],
            'registration_confirmed': value.get('registration_confirmed', False),
            'footprint': [[rear,-half],[front,-half],[front,half],[rear,half]],
            'segments': [{'name': segment.name, 'direction': segment.direction,
                          'poses': [convert(p) for p in segment.poses]}
                         for segment in route.segments]}
    if taught_dock and route_id.startswith('handoff_to_home_'):
        # Join the taught C pose to the existing return lane. Keep the common
        # lane and both waiting spots in the original shared map transform.
        poses = result['segments'][0]['poses']
        taught = value['goals']['handoff']['arrival']
        dx, dy = taught['x']-poses[0][0], taught['y']-poses[0][1]
        da = math.atan2(math.sin(taught['yaw']-poses[0][2]), math.cos(taught['yaw']-poses[0][2]))
        count = max(1, len(poses)-1)
        result['segments'][0]['poses'] = [[x+dx*(1-i/count), y+dy*(1-i/count),
                                         math.atan2(math.sin(a+da*(1-i/count)), math.cos(a+da*(1-i/count)))]
                                        for i, (x,y,a) in enumerate(poses)]
    return result


def command_route(path, command):
    if command.get('route_id'):
        selected = network_plan(path, command['route_id'])
        return {k: selected[k] for k in ('route_id', 'route_version', 'source_hash',
                'registration_sha256', 'map_sha256', 'frame_id', 'robot_id')}
    registry, _, _ = registration(path)
    entry = registry['goals'][command['zone_id']]
    key = 'arrival_route_id' if command['kind'] == 'NAVIGATE' else 'departure_route_id'
    route_id = entry.get(key)
    if not route_id and command['kind'] == 'LEAVE':
        route_id = {'load-a': 'exit_A', 'load-b': 'exit_B',
                    'handoff': 'handoff_to_home_'+command.get('return_slot', 'front')}[command['zone_id']]
    if not route_id:
        raise ValueError('관제 기준 경로 미등록: ' + key)
    selected = plan(path, route_id)
    return {k:selected[k] for k in ('route_id','route_version','source_hash',
        'registration_sha256','map_sha256','frame_id','robot_id')}


def network_plan(path, route_id):
    """Shared waiting/lane coordinates, with the taught straight dock at each bay."""
    from copy import deepcopy
    if route_id.endswith('_exit_to_B') or route_id.endswith('_exit_to_handoff'):
        original = route_id.replace('_exit', '')
        result = network_plan(path, original)
        result['route_id'], result['segments'] = route_id, result['segments'][1:]
        return result
    result = plan(path, route_id, taught_dock=False)
    docks = {zone: plan(path, 'home_to_'+zone)['segments'][-1]
             for zone in ('A', 'B', 'handoff')}
    if route_id.startswith('exit_'):
        dock = docks[route_id[-1]]
        result['segments'] = [dict(name='leave_bay', direction=1, poses=list(reversed(dock['poses'])))]
        return result
    segments = result['segments']
    source, destination = route_id.split('_to_') if '_to_' in route_id else (None, None)
    if source in docks:
        if destination.startswith('home_'):
            # Preserve the return lane; shift only its departure from taught C.
            old = segments[0]['poses']; start = docks[source]['poses'][-1]
            end = old[-1]
            segments[0]['poses'] = [[start[j]+(end[j]-start[j])*i/(len(old)-1)
                                     for j in range(3)] for i in range(len(old))]
        else:
            segments[0] = dict(name='leave_bay', direction=1, poses=list(reversed(docks[source]['poses'])))
    if destination in docks:
        segments[-1] = deepcopy(docks[destination])
        if source == 'home':
            curve = segments[1]['poses']; end = segments[-1]['poses'][0]
            start = curve[0]
            # Clear the waiting row before turning toward a station. Keep the
            # straight and curve in one FollowPath so there is no intermediate stop.
            exit_point = [start[0]-.30*math.cos(start[2]), start[1]-.30*math.sin(start[2])]
            controls = [exit_point,
                        [exit_point[0]-.12*math.cos(start[2]), exit_point[1]-.12*math.sin(start[2])],
                        [end[0]+.12*math.cos(end[2]), end[1]+.12*math.sin(end[2])], end[:2]]
            points = [[start[j]+(exit_point[j]-start[j])*i/60 for j in range(2)]+[start[2]]
                      for i in range(60)]
            for i in range(len(curve)):
                t = i/(len(curve)-1)
                weights = [(1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3]
                points.append([sum(w*p[j] for w,p in zip(weights, controls)) for j in range(2)]+[end[2]])
            segments[1]['poses'] = points
        else:
            start, end = segments[0]['poses'][-1], segments[-1]['poses'][0]
            heading = math.atan2(end[1]-start[1], end[0]-start[0])
            segments[1]['poses'] = [start, [*start[:2], heading]]
            count = len(segments[2]['poses'])
            segments[2]['poses'] = [[start[0]+(end[0]-start[0])*i/(count-1),
                                    start[1]+(end[1]-start[1])*i/(count-1), heading]
                                   for i in range(count)]
            segments[3]['poses'] = [[*end[:2], heading], end]
    # Moving-path heading comes from its travel tangent; preserve dock direction.
    for segment in segments:
        if segment['direction'] and segment['name'] not in ('dock_reverse', 'leave_bay'):
            poses = segment['poses']
            for a, b in zip(poses, poses[1:]):
                yaw = math.atan2(b[1]-a[1], b[0]-a[0]) + (math.pi if segment['direction'] < 0 else 0)
                a[2] = math.atan2(math.sin(yaw), math.cos(yaw))
    # Spin targets match the following path's body heading, including dock entry.
    for i, segment in enumerate(segments[:-1]):
        if segment['direction'] == 0:
            segment['poses'] = [[*segments[i+1]['poses'][0][:2], segment['poses'][0][2]],
                                segments[i+1]['poses'][0][:]]
    if source == 'home' and destination in docks:
        # The curve endpoint is a through-point, not a separate arrival goal.
        segments[1:] = [dict(name='home_to_dock', direction=-1,
                             poses=segments[1]['poses']+segments[-1]['poses'][1:])]
    return result
