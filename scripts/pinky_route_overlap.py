"""Compare recorded P1 runs without starting ROS, cameras, or robot motion."""
import argparse
import json
import math
from pathlib import Path

import numpy as np

from robot_gateway.hardware.wait_parking import to_layout


LEGS = [('전열 → A', 'front-to-A', 'home_to_A'),
        ('A → B', 'A-to-B', 'A_to_B'),
        ('B → C', 'B-to-C', 'B_to_handoff'),
        ('C → 전열', 'C-to-front', 'handoff_to_home_back')]
COLORS = {3: '#176ac6', 4: '#e37b18'}


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def recorded(folder):
    traces = []
    for line in (folder/'command.log').read_text().splitlines():
        if line.startswith('주행 기록: '):
            path = Path(line.split(': ', 1)[1])
            traces.extend(lines(folder/path.name if (folder/path.name).exists() else path))
    return traces


def camera_path(folder, robot):
    points, visible, total, last = [], 0, 0, None
    for row in lines(folder/'camera.jsonl'):
        obs = row['observation']; timestamp = obs.get('observed_at')
        if timestamp == last:
            continue
        last = timestamp; total += 1
        value = obs.get('robots', {}).get(robot, {})
        if value.get('visible') and value.get('layout_pose'):
            pose = value['layout_pose']; visible += 1
            points.append([pose['x'], pose['y']])
        else:
            points.append([math.nan, math.nan])
    return points, visible, total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--v3', type=Path, required=True)
    parser.add_argument('--v4', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.transforms import Affine2D
    import cv2
    import yaml
    font = Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams['font.family'] = font_manager.FontProperties(fname=font).get_name()
    plt.rcParams['axes.unicode_minus'] = False
    def asset(path):
        saved = args.output/Path(path).name
        return saved if saved.exists() else Path(path)
    camera = read('runtime/field/pinky-camera-navigation.json')
    transform = read(asset(camera['layout_registry']))['layout_to_map']
    index = read(asset('runtime/field/pinky-route-network-p1.json'))
    map_path = asset(camera['map_yaml']); metadata = yaml.safe_load(map_path.read_text())
    image = cv2.imread(str(map_path.parent/metadata['image']), cv2.IMREAD_GRAYSCALE)
    resolution = metadata['resolution']; ox, oy, angle = metadata['origin']
    # Occupancy pixels -> ROS map -> common layout, preserving map orientation.
    background = (Affine2D().rotate(angle).translate(ox, oy)
                  .translate(-transform['x'], -transform['y']).rotate(-transform['yaw']))
    def layout(pose):
        value = to_layout(pose, transform)
        return [value['x'], value['y']]
    def setup(ax, title):
        ax.imshow(image, cmap='gray', origin='upper', alpha=.38,
                  extent=(0, image.shape[1]*resolution, 0, image.shape[0]*resolution),
                  transform=background+ax.transData)
        ax.plot([0, 2, 2, 0, 0], [0, 0, -1.5, -1.5, 0], c='#777', lw=.7)
        ax.set(xlim=(-.12, 2.12), ylim=(-1.62, .12), aspect='equal', title=title,
               xlabel='가로 (m)', ylabel='세로 (m)')
        ax.grid(alpha=.15)
    manifests = []; data = {}
    for version, root in [(3, args.v3), (4, args.v4)]:
        for title, suffix, route in LEGS:
            matches = sorted(root.glob('*'+suffix))
            if not matches:
                continue
            folder = matches[-1]; status = read(folder/'status.json')
            traces = recorded(folder)
            identities = [v for v in traces if v.get('event') == 'route_identity']
            poses = [layout(v['pose']) for v in traces if v.get('event') == 'pose']
            points, visible, total = camera_path(folder, 'pinky-1')
            data[version, suffix] = {'camera': points, 'nav2': poses,
                                     'exit_code': status.get('exit_code')}
            manifests.append(dict(version=version, leg=title, folder=str(folder.resolve()),
                exit_code=status.get('exit_code'), elapsed_s=status.get('ended_at', status['started_at'])-status['started_at'],
                camera_visible=visible, camera_samples=total, nav2_samples=len(poses),
                route_identity=identities))
    (args.output/'comparison.json').write_text(json.dumps(manifests, ensure_ascii=False, indent=2))
    for kind, label in [('camera', '전체 카메라 관측 궤적'), ('nav2', 'Nav2 지도 추정 궤적'),
                        ('planned', '배포된 계획 경로')]:
        fig, axes = plt.subplots(2, 2, figsize=(12, 9), layout='constrained')
        for ax, (title, suffix, route) in zip(axes.flat, LEGS):
            setup(ax, title)
            for version in (3, 4):
                chunks = []
                if kind == 'planned':
                    route_names = [route, 'queue_advance'] if suffix == 'C-to-front' else [route]
                    for name in route_names:
                        for segment in index['routes'][f'v{version}/{name}']['segments']:
                            chunks.append([layout(dict(zip(('x', 'y', 'yaw'), p))) for p in segment['poses']])
                elif (version, suffix) in data:
                    chunks = [data[version, suffix][kind]]
                for i, chunk in enumerate(chunks):
                    if not chunk:
                        continue
                    values = np.asarray(chunk)
                    failed = kind != 'planned' and data[version, suffix]['exit_code'] not in (None, 0)
                    legend_label = f'v{version}' + (' (중단)' if failed else '')
                    ax.plot(values[:, 0], values[:, 1], color=COLORS[version], lw=1.6,
                            alpha=.85, label=legend_label if i == 0 else None)
                    if failed:
                        valid = values[np.isfinite(values).all(axis=1)]
                        if len(valid):
                            ax.scatter(*valid[-1], marker='x', color='#b51d27', s=65, zorder=5)
            ax.legend(loc='lower right')
        fig.suptitle(f'P1 v3 · v4 비교 — {label}', fontsize=17)
        if kind == 'camera':
            fig.supxlabel('미검출 구간은 연결하지 않음 · 기존 카메라 캘리 사용 · 버전별 1회 시험')
        elif kind == 'nav2':
            fig.supxlabel('위치 보정 시 추정 좌표가 바뀔 수 있음 · 카메라 주차는 별도 제어')
        else:
            fig.supxlabel('계획선은 실제 주행 궤적과 구분 · 현장 도착 목표 포함')
        fig.savefig(args.output/f'{kind}-overlap.png', dpi=180)
        fig.savefig(args.output/f'{kind}-overlap.svg')
        plt.close(fig)
    print(args.output.resolve())


if __name__ == '__main__':
    main()
