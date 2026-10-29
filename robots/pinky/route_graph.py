"""Export existing directed field curves for Nav2 ComputeRoute."""
import math
from copy import deepcopy


def return_from_current(route, current):
    """Start at the nearest existing return-lane node, keeping directed suffixes."""
    route = deepcopy(route)
    choices = []
    for index, segment in enumerate(route['segments']):
        if not segment['direction'] or segment.get('camera_guided'):
            continue
        points = []
        for point in segment['poses']:
            if not points or math.dist(points[-1][:2], point[:2]) > 1e-8:
                points.append(point)
        segment['poses'] = points
        for offset, point in enumerate(points[:-1]):
            choices.append((math.dist([current['x'], current['y']], point[:2]), index, offset))
    _, index, offset = min(choices)
    route['segments'] = route['segments'][index:]
    first = route['segments'][0]
    first['start_id'] += offset
    first['poses'] = first['poses'][offset:]
    return route


def return_join_segments(segments, current):
    """Face a short curved connection, then follow the computed return route."""
    segments = deepcopy(segments)
    first = segments[0]
    poses = first['poses']
    travelled, join = 0., 0
    for join in range(1, len(poses)):
        travelled += math.dist(poses[join-1][:2], poses[join][:2])
        if travelled >= .15:
            break
    start, end = [current['x'], current['y']], poses[join][:2]
    travel = math.atan2(end[1]-start[1], end[0]-start[0])
    reverse = math.pi if first['direction'] < 0 else 0.
    tangent = poses[join][2]+reverse
    handle = math.dist(start, end)/3
    controls = [start, [start[0]+handle*math.cos(travel), start[1]+handle*math.sin(travel)],
                [end[0]-handle*math.cos(tangent), end[1]-handle*math.sin(tangent)], end]
    count = max(1, math.ceil(sum(math.dist(a,b) for a,b in zip(controls, controls[1:]))/.005))
    path = []
    for i in range(count):
        t = i/count
        weights = [(1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3]
        point = [sum(w*p[j] for w,p in zip(weights, controls)) for j in range(2)]
        derivative = [sum(w*(b[j]-a[j]) for w,a,b in
                          zip([(1-t)**2, 2*(1-t)*t, t*t], controls, controls[1:])) for j in range(2)]
        yaw = math.atan2(derivative[1], derivative[0])+reverse
        path.append(point+[math.atan2(math.sin(yaw), math.cos(yaw))])
    first['poses'] = path+poses[join:]
    initial = [current['x'], current['y'], current['yaw']]
    goal = segments[-1]['poses'][-1][:]
    final = [] if segments[-1]['direction'] == 0 or segments[-1].get('camera_guided') else [
        {'name':'waiting_heading', 'direction':0, 'poses':[goal]}]
    return ([{'name':'face_return_join', 'direction':0, 'poses':[initial, first['poses'][0]]}]
            + segments + final)


def departure_path(poses, current, *, align_heading=False):
    """Join the actual pose to the end of the existing 30cm departure straight."""
    distance, join = 0., 0
    for join in range(1, len(poses)-1):
        distance += math.dist(poses[join-1][:2], poses[join][:2])
        if distance >= .30-1e-6:
            break
    start, end = [current['x'], current['y']], poses[join][:2]
    travel = (math.atan2(end[1]-start[1], end[0]-start[0]) if align_heading
              else current['yaw']+math.pi)
    tangent = math.atan2(poses[join+1][1]-end[1], poses[join+1][0]-end[0])
    handle = math.dist(start, end)/3
    controls = [start, [start[0]+handle*math.cos(travel), start[1]+handle*math.sin(travel)],
                [end[0]-handle*math.cos(tangent), end[1]-handle*math.sin(tangent)], end]
    count = max(1, math.ceil(sum(math.dist(a, b) for a, b in zip(controls, controls[1:]))/.005))
    result = []
    for i in range(count):
        t = i/count
        weights = [(1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3]
        point = [sum(w*p[j] for w, p in zip(weights, controls)) for j in range(2)]
        derivative = [sum(w*(b[j]-a[j]) for w, a, b in
                          zip([(1-t)**2, 2*(1-t)*t, t*t], controls, controls[1:])) for j in range(2)]
        yaw = math.atan2(derivative[1], derivative[0])+math.pi
        result.append(point+[math.atan2(math.sin(yaw), math.cos(yaw))])
    return result+poses[join:]


def observation_arrival(plan, observation):
    """Extend arrival to the taught camera observation offset in parking-goal axes."""
    plan = deepcopy(plan)
    segment = plan['segments'][-1]
    x, y, yaw = segment['poses'][-1]
    forward, left = observation['goal_forward_m'], observation['goal_left_m']
    dx = -math.cos(yaw)*forward + math.sin(yaw)*left
    dy = -math.sin(yaw)*forward - math.cos(yaw)*left
    steps = max(1, math.ceil(math.hypot(dx, dy)/.005))
    segment['poses'] += [[x+dx*i/steps, y+dy*i/steps, yaw] for i in range(1, steps+1)]
    segment['goal_checker_id'] = 'observation_goal_checker'
    plan['parking_start'] = 'observe'
    return plan


def observation_heading(segments):
    """Finish camera-observation arrivals with Spin after position-only FollowPath."""
    if not segments or segments[-1].get('goal_checker_id') != 'observation_goal_checker':
        return segments
    goal = segments[-1]['poses'][-1][:]
    return segments + [{'name': 'observation_heading', 'direction': 0, 'poses': [goal]}]


def path_goal_checker(segment, version):
    """V3 transit points finish by position; turns and camera parking own heading."""
    if version == 3 and segment['direction'] == 1 and not segment.get('camera_guided'):
        return 'observation_goal_checker'  # Existing PositionGoalChecker, 5cm.
    return segment.get('goal_checker_id', 'general_goal_checker')


def build_graph(plans):
    features, routes = [], {}
    node_id, edge_id = 0, 0
    for plan in plans:
        segments = []
        for segment in plan['segments']:
            entry = dict(segment)
            if segment['direction'] != 0:
                points = []
                for pose in segment['poses']:
                    if not points or math.dist(pose[:2], points[-1][:2]) > 1e-8:
                        points.append(pose)
                start_id = node_id
                for i, pose in enumerate(points):
                    features.append({'type': 'Feature', 'properties': {
                        'id': node_id, 'frame': plan['frame_id']},
                        'geometry': {'type': 'Point', 'coordinates': pose[:2]}})
                    if i:
                        features.append({'type': 'Feature', 'properties': {
                            'id': edge_id, 'startid': node_id-1, 'endid': node_id,
                            'cost': math.dist(points[i-1][:2], pose[:2]), 'overridable': False},
                            'geometry': {'type': 'LineString', 'coordinates': [points[i-1][:2], pose[:2]]}})
                        edge_id += 1
                    node_id += 1
                entry.update(start_id=start_id, goal_id=node_id-1)
            segments.append(entry)
        routes[plan['route_id']] = {'segments': segments, 'frame_id': plan['frame_id'],
                                    'registration_sha256': plan['registration_sha256']}
        if plan.get('parking_start'):
            routes[plan['route_id']]['parking_start'] = plan['parking_start']
        if plan.get('waiting_slot'):
            routes[plan['route_id']]['waiting_slot'] = plan['waiting_slot']
    return {'type': 'FeatureCollection', 'features': features}, {'routes': routes}


def directed_path(path, direction, terminal_yaw):
    """ComputeRoute headings follow travel; FollowPath needs the body heading."""
    poses = []
    for point in path.poses:
        p, q = point.pose.position, point.pose.orientation
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        yaw += math.pi if direction < 0 else 0.
        poses.append([p.x, p.y, math.atan2(math.sin(yaw), math.cos(yaw))])
    if poses:
        poses[-1][2] = terminal_yaw
    return poses
