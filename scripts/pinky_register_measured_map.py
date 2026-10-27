"""Fit measured layout walls to a saved map; never connects to a robot."""
import argparse
import json
import math
from pathlib import Path
from types import SimpleNamespace as Obj

from robot_gateway.hardware.pinky import atomic_json, map_signature
from robots.pinky import compact
from robots.pinky.reference.geometry import dock_pose


def register(map_file, output):
    import numpy as np
    import yaml
    from PIL import Image
    from scipy.ndimage import binary_dilation
    from scipy.optimize import least_squares
    from scipy.spatial import cKDTree

    cfg = compact.bundle()[0]
    path = Path(map_file)
    meta = yaml.safe_load(path.read_text())
    pixels = np.array(Image.open(path.parent / meta['image']).convert('L'))[::-1]
    occupied = pixels / 255 if meta.get('negate') else (255 - pixels) / 255
    cells = np.where(occupied > meta['occupied_thresh'], 100,
                     np.where(occupied < meta['free_thresh'], 0, -1))
    ox, oy, angle = meta['origin']
    resolution = float(np.float32(meta['resolution']))
    origin = Obj(position=Obj(x=ox, y=oy, z=0.0),
                 orientation=Obj(x=0.0, y=0.0, z=math.sin(angle/2), w=math.cos(angle/2)))
    message = Obj(info=Obj(width=cells.shape[1], height=cells.shape[0],
                          resolution=resolution, origin=origin), data=cells.ravel().tolist())
    edges = (cells == 100) & binary_dilation(cells == 0)
    rows, cols = np.where(edges)
    points = np.c_[ox + (cols + .5) * resolution, oy + (rows + .5) * resolution]
    tree = cKDTree(points)
    width, depth = cfg['width'], cfg['depth']
    walls = [((0, 0), (width, 0)), ((0, -depth), (width, -depth)),
             ((0, 0), (0, -depth)), ((width, 0), (width, -depth))]
    for x in np.cumsum(cfg['station_widths'])[:-1]:
        walls.append(((float(x), 0), (float(x), -cfg['station_depth'])))
    samples = np.concatenate([np.linspace(a, b, math.ceil(np.linalg.norm(np.array(b)-a)/.01)+1)
                              for a, b in walls])

    def convert(points, transform):
        x, y, yaw = transform
        c, s = math.cos(yaw), math.sin(yaw)
        return points @ np.array([[c, s], [-s, c]]) + [x, y]

    # This map has the .6/.6/.8m bays top-to-bottom and the back wall on the right.
    # Initialise from the map bounds, independent of a clicked goal or robot pose.
    initial = [float(points[:, 0].max()), float(points[:, 1].max()), -math.pi/2]
    fit = least_squares(lambda t: tree.query(convert(samples, t))[0], initial,
                        loss='soft_l1', f_scale=.015, max_nfev=150)
    distances = tree.query(convert(samples, fit.x))[0]
    fixed = dict(zip(('x', 'y', 'yaw'), fit.x.tolist()))
    result = {
        'schema_version': 2, 'robot_id': 'pinky-1', 'frame_id': 'map',
        'map_sha256': map_signature(message), 'layout_to_map': fixed,
        'registration_method': 'measured_layout_to_saved_map_wall_fit',
        'registration_confirmed': True, 'physical_parking_verified': False,
        'fit': {'median_wall_residual_m': float(np.median(distances)),
                'p90_wall_residual_m': float(np.quantile(distances, .9)),
                'map_file': str(path), 'layout_file': 'robots/pinky/reference/data/v4/layout.json',
                'robot_origin_to_rear_junction_m': cfg['sim_asset']['rear_x'],
                'rear_junction_offset_source': cfg['sim_asset']['notes']},
        'goals': {},
    }
    for index, (zone, station) in enumerate([('load-a', 'A'), ('load-b', 'B'), ('handoff', 'handoff')]):
        x, y, yaw = dock_pose(cfg, index)
        mx, my = convert(np.array([[x, y]]), fit.x)[0]
        myaw = math.atan2(math.sin(yaw+fit.x[2]), math.cos(yaw+fit.x[2]))
        result['goals'][zone] = {
            'arrival': {'x': float(mx), 'y': float(my), 'yaw': float(myaw)},
            'exit': None, 'radius': .15, 'arrival_route_id': 'home_to_'+station,
            'departure_route_id': None,
            'measured': {'bay_center_layout_x_m': x,
                         'rear_junction_to_back_wall_m': cfg['junction_wall_distances'][index]},
        }
    atomic_json(output, result)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from robots.pinky.field_routes import plan
    fig, ax = plt.subplots(figsize=(7, 8))
    ax.imshow(cells, origin='lower', extent=[ox, ox+cells.shape[1]*resolution,
              oy, oy+cells.shape[0]*resolution], cmap='gray_r', vmin=-1, vmax=100)
    for a, b in walls:
        line = convert(np.array([a, b]), fit.x)
        ax.plot(line[:, 0], line[:, 1], color='#ff8c00', lw=1.5)
    colors = ['#1675c1', '#299550', '#a04ab7']
    for (zone, station), color in zip([('load-a', 'A'), ('load-b', 'B'), ('handoff', 'C')], colors):
        goal = result['goals'][zone]['arrival']
        ax.scatter(goal['x'], goal['y'], c=color, s=55)
        ax.text(goal['x']+.04, goal['y']+.035, station, color=color, weight='bold')
        ax.arrow(goal['x'], goal['y'], .13*math.cos(goal['yaw']), .13*math.sin(goal['yaw']),
                 color=color, head_width=.035, length_includes_head=True)
    selected = plan(output, 'home_to_A')
    for segment in selected['segments'][-1:]:
        p = np.array(segment['poses'])
        ax.plot(p[:, 0], p[:, 1], color='#1675c1', alpha=.6, lw=1)
    join = selected['segments'][-1]['poses'][0]
    ax.scatter(join[0], join[1], marker='x', c='red', label='A docking approach / adaptive entry target')
    ax.set(title='Measured bay centres and wall distances / saved ROS map',
           xlabel='map x (m)', ylabel='map y (m)')
    ax.axis('equal'); ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(Path(output).with_suffix('.png'), dpi=130); plt.close(fig)
    print(json.dumps({'output': output, 'layout_to_map': fixed, 'fit': result['fit'],
                      'goals': {k: v['arrival'] for k, v in result['goals'].items()}}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map', default='runtime/field/pinky-map-new.yaml')
    parser.add_argument('--output', default='runtime/field/pinky-p1-measured-goals.json')
    args = parser.parse_args()
    register(args.map, args.output)
