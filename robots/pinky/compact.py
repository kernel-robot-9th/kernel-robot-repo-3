"""Pinned v4 geometry; mathematical references, not measured robot positions."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json

from .catalog import ROOT, BACKEND, Route
from .reference.compact_routes import route_set

VERSION = 4
FRAME = 'layout-v4'


@lru_cache(maxsize=1)
def bundle():
    raw = (ROOT / 'source-v4.json').read_bytes()
    manifest = json.loads(raw)
    for info in manifest['files']:
        path = ROOT / info['path']
        if not path.resolve().is_relative_to(ROOT.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
            raise ValueError('v4 기준 파일 해시 불일치: ' + info['path'])
    config = json.loads((ROOT / 'data/v4/layout.json').read_text(encoding='utf-8'))
    routes = {k: [dict(name=s.name, poses=s.poses, direction=s.direction) for s in v]
              for k, v in route_set(config).items()}
    return config, routes, {}, hashlib.sha256(raw).hexdigest()


@lru_cache(maxsize=16)
def route(key):
    return Route(key, bundle)


@lru_cache(maxsize=1)
def map_data():
    cfg, paths, _, source_hash = bundle()
    return dict(backend=BACKEND, route_version=VERSION, frame_id=FRAME, source_hash=source_hash,
        physical_hardware_verified=False, physics_tracking=False, movement_limit=1,
        layout={k: cfg[k] for k in ('width','depth','station_depth','station_widths','basket_width','basket_length','basket_height','arm_wall_distance')},
        body_front=cfg['sim_asset']['front_x'], body_rear=cfg['sim_asset']['rear_x'], body_width=.1101,
        routes={k: dict(duration=route(k).duration, start=route(k).poses[0], end=route(k).poses[-1],
            poses=route(k).poses[::8] + [route(k).poses[-1]]) for k in paths})


def public_map():
    return deepcopy(map_data())
