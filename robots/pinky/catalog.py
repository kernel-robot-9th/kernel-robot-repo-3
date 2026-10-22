"""Pinned layout-frame reference routes. No ROS names or simulator dependency."""
from bisect import bisect_right
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

from .reference.route_paths import Segment, join, angle_delta, interpolate
from .reference.route_validation import check_path

ROOT = Path(__file__).resolve().parent / 'reference'
BACKEND = 'reference_path'
FRAME = 'layout-v3'
VERSION = 3


@lru_cache(maxsize=1)
def bundle():
    raw = (ROOT / 'source.json').read_bytes()
    manifest = json.loads(raw)
    for info in manifest['files']:
        path = ROOT / info['path']
        if not path.resolve().is_relative_to(ROOT.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
            raise ValueError('도로 기준 파일 해시 불일치: ' + info['path'])
    load = lambda name: json.loads((ROOT / 'data/v3' / name).read_text(encoding='utf-8'))
    graph = load('route-graph.json')
    if graph['route_version'] != VERSION or graph['schema_version'] != 2:
        raise ValueError('도로 버전/형식 불일치')
    return load('layout.json'), load('routes.json'), graph, hashlib.sha256(raw).hexdigest()


class Route:
    def __init__(self, route_id, loader=bundle):
        config, routes, _, self.source_hash = loader()
        if route_id not in routes:
            raise ValueError('등록되지 않은 기준 경로')
        self.id, self.config = route_id, config
        self.segments = [Segment(s['name'], s['poses'], s['direction']) for s in routes[route_id]]
        self.poses = join(self.segments)
        self.times = [0.]
        for a, b in zip(self.poses, self.poses[1:]):
            dt = max(math.dist(a[:2], b[:2]) / .08, abs(angle_delta(a[2], b[2])) / .5)
            self.times.append(self.times[-1] + dt)
        self.duration = self.times[-1]

    def sample(self, elapsed):
        if elapsed <= 0:
            return list(self.poses[0]), 0.
        if elapsed >= self.duration:
            return list(self.poses[-1]), 0.
        i = min(bisect_right(self.times, elapsed) - 1, len(self.poses) - 2)
        dt = self.times[i + 1] - self.times[i]
        pose = interpolate(self.poses[i], self.poses[i + 1], (elapsed - self.times[i]) / dt)
        return list(pose), math.dist(self.poses[i][:2], self.poses[i + 1][:2]) / dt

    def check(self):
        if not check_path(self.config, self.poses)['valid']:
            raise ValueError('기준 경로의 바구니 외곽 검사 실패')


@lru_cache(maxsize=32)
def route(route_id):
    return Route(route_id)


@lru_cache(maxsize=1)
def map_data():
    cfg, routes, graph, source_hash = bundle()
    result = dict(backend=BACKEND, route_version=VERSION, frame_id=FRAME, source_hash=source_hash,
                  physical_hardware_verified=False, physics_tracking=False,
                  layout={k: cfg[k] for k in ['width', 'depth', 'station_depth', 'station_widths',
                          'basket_width', 'basket_length', 'basket_height', 'arm_wall_distance']},
                  body_front=cfg['sim_asset']['front_x'], body_rear=cfg['sim_asset']['rear_x'],
                  body_width=.1101, nodes=graph['nodes'], routes={},
                  edges=[e['reference_poses'][::12] + [e['reference_poses'][-1]] for e in graph['edges']])
    for key in routes:
        r = route(key)
        result['routes'][key] = dict(duration=r.duration, start=r.poses[0], end=r.poses[-1],
            segments=[dict(name=s.name, direction=s.direction, poses=s.poses[::8] + [s.poses[-1]]) for s in r.segments])
    return result


def public_map():
    return deepcopy(map_data())
