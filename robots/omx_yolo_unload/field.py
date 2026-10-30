"""C-local setup tools. Device access happens only in the selected subcommand."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import runpy
import sys
import threading
import uuid

from .core import POSES, PICKING, basket_job, correction_sample, plan
from .runtime import YoloUnloadArm, write_json
from robot_gateway.station_video import camera_job
from pick_core import choose, get_rule, load_config, read_json, validate_gripper
from omx_pick import calibration_for, legacy, select_grasp_plan
from omx_arm_config import ArmProfile

ROOT = Path(__file__).resolve().parents[2]


def save(path, data):
    path = Path(path)
    if path.exists():
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        path.with_name(path.name + '.' + stamp + '.bak').write_bytes(path.read_bytes())
    write_json(path, data)


def profile_for(cfg):
    return ArmProfile(cfg['arm_name'], Path(cfg['serial_by_id']), cfg['camera_by_id'],
        cfg['width'], cfg['height'], cfg['fps'], Path(cfg['samples_file']),
        Path(cfg['calibration_file']), Path(cfg['poses_file']))


def init(args):
    from server.catalog import load_products
    root = args.directory.expanduser().resolve()
    path = root / 'gateway-c.yolo.hardware.json'
    job_path = root / 'omx_unload.json'
    if path.exists() or job_path.exists():
        raise FileExistsError('C 설정이 이미 있습니다. 새로 초기화하지 말고 기존 파일을 사용하세요.')
    job = read_json(Path(__file__).with_name('config') / 'unload.example.json')
    template = job['classes'].pop('PRODUCT_CLASS')
    job['classes'] = {p['detector_class']: dict(template) for p in load_products().values()}
    cfg = {'arm_name': 'single', 'serial_by_id': args.serial, 'camera_by_id': args.camera,
        'width': args.width, 'height': args.height, 'fps': args.fps,
        'weights': str(args.weights.expanduser().resolve()), 'pick_config': str(job_path),
        'samples_file': str(root / 'xy_samples.csv'), 'calibration_file': str(root / 'xy_calibration.json'),
        'poses_file': str(root / 'poses.json'), 'journal_directory': str(root / 'runs'),
        'video_channel': 'handoff-front', 'from_folded': False}
    hardware = {'node_id': 'gateway-c', 'unload_engine': 'yolo', 'armed': False,
        'video': {'transport': 'jpeg', 'fps': 5}, 'evidence_directory': str(root / 'evidence'),
        'state_directory': str(root / 'worker'), 'yolo_unload': cfg}
    write_json(job_path, job)
    write_json(path, hardware)
    print('C 전용 준비 설정:', path)
    print('현장 기록 전이며 기존 gateway-c.hardware.json은 변경하지 않았습니다.')


def saved(profile):
    recorder = legacy('07_omx_pose_recorder.py', 'c_pose_recorder')
    return {name: recorder.load_pose(name, profile)['raw_pulses'] for name in POSES}


def capture(cfg, profile, job, robot, label, index=0):
    from pick_vision import Camera, Detector
    with camera_job(), Camera(profile) as camera:
        frame, _ = camera.read()
    height, width = frame.shape[:2]
    if (width, height) != (profile.width, profile.height):
        raise ValueError('카메라 실제 해상도가 C 설정과 다릅니다')
    detections = Detector(job, cfg['weights']).predict(frame)
    return frame, choose(detections, basket_job(job, robot), label, width, height, index)


def geometry_hash(calibration):
    return hashlib.sha256(json.dumps(calibration, sort_keys=True).encode()).hexdigest()


def record_sample(cfg, job, calibration, target, robot, name, xyz):
    rule = get_rule(job, target.label)
    row = dict(recorded_at=datetime.now().astimezone().isoformat(), point_name=name,
        robot_id=robot, class_name=target.label, uv=list(target.point(rule)),
        calibration_sha256=geometry_hash(calibration), xy_offset_mm=rule.get('xy_offset_mm', [0, 0]),
        actual_xyz_mm=list(xyz), **correction_sample(calibration, target, rule, xyz))
    path = Path(cfg['samples_file']).with_name('spatial_samples.jsonl')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    print('위치별 보정 원본 저장:', path, name)


def spatial_fit(cfg, job, profile, args):
    import cv2
    import numpy as np
    rule = get_rule(job, args.label)
    calibration, _ = calibration_for(profile, rule, job)
    rows = [json.loads(line) for line in Path(cfg['samples_file']).with_name('spatial_samples.jsonl').read_text().splitlines() if line]
    latest = {r['point_name']: r for r in rows if r['class_name'] == args.label and r['robot_id'] == args.robot}
    nodes = list(latest.values())
    if len(nodes) < 3:
        raise ValueError('삼각형 보간에는 서로 다른 위치의 기록이 최소 3개 필요합니다')
    if any(r['calibration_sha256'] != geometry_hash(calibration) or
           r['xy_offset_mm'] != rule.get('xy_offset_mm', [0, 0]) for r in nodes):
        raise ValueError('기록 후 기본 캘리/상품 XY가 변경됐습니다. 같은 기준의 보정점을 사용하세요.')
    xy = np.array([r['xy_mm'] for r in nodes], dtype=float)
    if len(set(map(tuple, xy))) != len(xy):
        raise ValueError('같은 좌표가 다른 이름으로 중복 기록됐습니다')
    lo = np.floor(xy.min(axis=0)).astype(int) - 1
    hi = np.ceil(xy.max(axis=0)).astype(int) + 1
    subdiv = cv2.Subdiv2D((*map(int, lo), *map(int, hi - lo)))
    for point in xy:
        subdiv.insert(tuple(map(float, point)))
    triangles = []
    for tri in subdiv.getTriangleList():
        indices = []
        for point in tri.reshape(3, 2):
            distances = np.linalg.norm(xy - point, axis=1)
            if distances.min() > .001:
                break
            indices.append(int(distances.argmin()))
        if len(set(indices)) == 3:
            triangles.append(indices)
    if not triangles:
        raise ValueError('보정점이 한 직선입니다. 면적으로 분산해 기록하세요.')
    mesh = {'points': [{k: r[k] for k in ('xy_mm', 'correction_xyz_mm')} for r in nodes],
            'triangles': triangles}
    rule.setdefault('spatial_adjustments_by_robot', {})[args.robot] = mesh
    save(cfg['pick_config'], job)
    print(args.robot, args.label, '보간 저장:', len(nodes), '점 /', len(triangles), '삼각형')


def region(profile, cfg, job, robot):
    import cv2
    import numpy as np
    from pick_vision import Camera
    points = []
    window = 'C basket ROI - click corners / Enter save / R reset / Q quit'
    with camera_job(), Camera(profile) as camera:
        frame, _ = camera.read()
    if (frame.shape[1], frame.shape[0]) != (profile.width, profile.height):
        raise ValueError('카메라 실제 해상도가 C 설정과 다릅니다')
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, lambda event, x, y, flags, param:
                        points.append([x, y]) if event == cv2.EVENT_LBUTTONDOWN else None)
    try:
        while True:
            view = frame.copy()
            if points:
                cv2.polylines(view, [np.array(points)], True, (0, 255, 255), 2)
            cv2.imshow(window, view)
            key = cv2.waitKey(30) & 255
            if key in (27, ord('q')): return
            if key == ord('r'): points.clear()
            if key in (10, 13) and len(points) >= 3:
                job.setdefault('pickup_regions_uv', {})[robot] = points
                basket_job(job, robot)
                save(cfg['pick_config'], job)
                cv2.imwrite(str(Path(cfg['poses_file']).with_name(robot + '-pickup-roi.png')), view)
                print(robot, '실사용 바구니 영역 저장')
                return
    finally:
        cv2.destroyAllWindows()


def jog(cfg, job, profile, args):
    from pick_robot import DynamixelBus, MotionController
    from omx_pick_adjust import jog_keyboard, xy_snapshot
    from omx_jog_keyboard import JogWindow
    from pick_core import execute
    target = calibration = None
    if args.action == 'adjust':
        frame, target = capture(cfg, profile, job, args.robot, args.label, args.index)
        calibration, _ = calibration_for(profile, get_rule(job, args.label), job)
        poses = saved(profile)
    fk = legacy('02_omx_xyz_offline.py', 'c_jog_fk')
    with JogWindow(args.speed) as controls, DynamixelBus(profile.port) as bus:
        driver = MotionController(bus, job)
        driver.prepare(use_gripper=args.action == 'adjust')
        initial = xy_snapshot(bus, fk)
        wrist = initial['raw_pulses'][4]
        try:
            driver.enable()
            if target:
                trajectory = select_grasp_plan(poses['pickup_approach'], poses['pickup_approach'],
                    lambda solve: plan(job, calibration, target, poses, solve, args.robot, 'left',
                        hover_only=True, hover_stop_mm=args.hover_mm),
                    wrist_policy='fixed', fixed_wrist_pulse=wrist)
                execute(trajectory, driver)
                xyz, goal = list(trajectory['low_hover_xyz_mm']), list(trajectory['stages'][-1]['target'])
            else:
                xyz, goal = initial['model_xyz_mm'], initial['raw_pulses']
            result = jog_keyboard(driver, fk, wrist, xyz, goal, controls, args.speed)
            if result and target:
                # Enter means the operator aligned the gripper at the actual contact Z.
                actual = xy_snapshot(bus, fk)
                record_sample(cfg, job, calibration, target, args.robot, args.name, actual['model_xyz_mm'])
                import cv2
                cv2.imwrite(str(Path(cfg['samples_file']).with_name('last-adjust-source.png')), frame)
        finally:
            driver.hold()


def main(argv=None):
    parser = argparse.ArgumentParser(description='C YOLO 하역: 현장 기록·단독 시험')
    parser.add_argument('--hardware', type=Path, default=Path('runtime/field/c-yolo/gateway-c.yolo.hardware.json'))
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('init', help='C 전용 빈 설정 생성; 장비 접근 없음')
    p.add_argument('--directory', type=Path, default=Path('runtime/field/c-yolo'))
    p.add_argument('--serial', required=True); p.add_argument('--camera', required=True)
    p.add_argument('--weights', type=Path, default=ROOT / 'robots/omx_yolo/weights/best.pt')
    for key, value in [('width', 1920), ('height', 1080), ('fps', 30)]:
        p.add_argument('--' + key, type=int, default=value)
    sub.add_parser('status', help='파일·기록 상태; 카메라·모터 접근 없음')
    p = sub.add_parser('activate', help='기록 완료한 C YOLO 설정을 기존 관제 hardware에 병합')
    p.add_argument('--target', type=Path, default=Path('runtime/field/gateway-c.hardware.json'))
    p = sub.add_parser('calibrate', help='기존 단일 평면 캘리 도구를 C 경로로 실행')
    p.add_argument('args', nargs=argparse.REMAINDER)
    p = sub.add_parser('pose', help='현재 모터 자세를 읽고 Enter로 저장')
    p.add_argument('name', choices=POSES)
    p = sub.add_parser('move', help='기록한 자세 이동; 공통 자세 도구 사용')
    p.add_argument('args', nargs=argparse.REMAINDER)
    p = sub.add_parser('gripper', help='현재 그리퍼 열림/닫힘 펄스 또는 전류 설정')
    p.add_argument('--record', choices=('open', 'close'))
    p.add_argument('--current', type=int)
    p.add_argument('--read-current', action='store_true', help='현재 Goal Current를 읽어 설정에 기록')
    p = sub.add_parser('product', help='상품별 기본 집기 높이·여유 설정')
    p.add_argument('--class', dest='label', required=True)
    p.add_argument('--z', type=float); p.add_argument('--read-height', action='store_true')
    p.add_argument('--clearance', type=float, default=50)
    for action in ('region', 'detect', 'preview', 'adjust', 'fit-spatial', 'run'):
        p = sub.add_parser(action)
        p.add_argument('--robot', choices=('P1', 'P2'), required=True)
        if action in ('preview', 'adjust', 'fit-spatial'):
            p.add_argument('--class', dest='label', required=True)
        if action == 'preview':
            p.add_argument('--side', choices=('left', 'right'), required=True)
            p.add_argument('--index', type=int, default=0)
        if action == 'adjust':
            p.add_argument('--name', required=True)
            p.add_argument('--index', type=int, default=0)
            p.add_argument('--hover-mm', type=float, default=5)
            p.add_argument('--speed', type=float, default=10)
        if action == 'run':
            p.add_argument('--side', choices=('left', 'right'), required=True)
            p.add_argument('--skus', nargs='+', required=True)
            p.add_argument('--job-id', default=None, help='같은 ID 재실행은 완료한 동작 제외')
            p.add_argument('--execute', action='store_true', help='실물 하역 실행')
    p = sub.add_parser('jog', help='현재 위치에서 WASD/RF 조절; Enter 종료')
    p.add_argument('--speed', type=float, default=10)
    args = parser.parse_args(argv)
    if args.action == 'init':
        return init(args)
    hardware = read_json(args.hardware)
    cfg = hardware['yolo_unload']
    profile = profile_for(cfg)
    job = load_config(Path(cfg['pick_config']))
    if hasattr(args, 'robot'):
        args.robot = 'pinky-' + args.robot[-1]
    if args.action == 'status':
        from robot_gateway.hardware.config import validate
        issues = validate(dict(hardware, armed=True), require_mobile=False)
        try: validate_gripper(job)
        except ValueError as exc: issues.append(str(exc))
        print(json.dumps({'hardware_executed': False, 'issues': issues,
            'unrecorded_product_z': [k for k, v in job['classes'].items() if v.get('pick_z_mm') is None]}, ensure_ascii=False, indent=2))
    elif args.action in ('calibrate', 'move'):
        import omx_arm_config
        omx_arm_config.load_arm_profile = lambda name: profile
        script = (PICKING.parent / 'measurement/05_omx_xy_calibration.py' if args.action == 'calibrate'
                  else PICKING / 'omx_pose_move.py')
        forwarded = args.args[1:] if args.args[:1] == ['--'] else args.args
        sys.argv = [str(script), *forwarded]
        if args.action == 'calibrate':
            if args.args and args.args[0] == 'fit' and '--overwrite' in args.args and profile.calibration.exists():
                save(profile.calibration, read_json(profile.calibration))
            with camera_job():
                runpy.run_path(str(script), run_name='__main__')
        else:
            runpy.run_path(str(script), run_name='__main__')
    elif args.action == 'activate':
        current = read_json(args.target)
        if current.get('node_id') != 'gateway-c':
            raise ValueError('gateway-c 설정에만 연결할 수 있습니다')
        current.update(unload_engine='yolo', yolo_unload=cfg)
        save(args.target, current)
        print('C 관제 연결 저장:', args.target, '(기존 ACT 설정 보존; worker 재시작은 별도)')
    elif args.action == 'pose':
        recorder = legacy('07_omx_pose_recorder.py', 'c_pose_teach')
        registry = recorder.load_registry(profile)
        state = recorder.snapshot(profile)
        input('현재 자세를 ' + args.name + '으로 저장: Enter (취소 Ctrl+C) ')
        registry['poses'][args.name] = dict(recorded_at=datetime.now().astimezone().isoformat(),
            motor_ids=list(recorder.IDS), motor_models=list(recorder.MODELS),
            operating_modes=[4] * 5, homing_offsets=[0] * 5, raw_pulses=state['positions'])
        save(profile.poses, registry)
        print('저장:', profile.poses, args.name)
    elif args.action == 'gripper':
        if args.record or args.read_current:
            from pick_robot import DynamixelBus
            with DynamixelBus(profile.port) as bus:
                if args.record: pulse = bus.read(16, 132, 4)
                if args.read_current: args.current = bus.read(16, 102, 2)
        if args.record:
            input(f'{args.record} 그리퍼 펄스 {pulse} 저장: Enter ')
            job['gripper'][args.record + '_pulse'] = pulse
        if args.current is not None:
            from pick_core import integer
            integer(args.current, '그리퍼 Goal Current', 1, 1750)
            job['gripper']['current_limit_raw'] = args.current
        save(cfg['pick_config'], job)
    elif args.action == 'product':
        rule = get_rule(job, args.label)
        z = args.z
        if args.read_height:
            from omx_pick_adjust import xy_snapshot
            from pick_robot import DynamixelBus
            with DynamixelBus(profile.port) as bus:
                z = xy_snapshot(bus, legacy('02_omx_xyz_offline.py', 'c_height_fk'))['model_xyz_mm'][2]
        if z is None: parser.error('product: --z 또는 --read-height 필요')
        rule.update(pick_z_mm=z, hover_clearance_mm=args.clearance)
        save(cfg['pick_config'], job)
    elif args.action == 'region': region(profile, cfg, job, args.robot)
    elif args.action == 'preview':
        _, target = capture(cfg, profile, job, args.robot, args.label, args.index)
        calibration, _ = calibration_for(profile, get_rule(job, args.label), job)
        poses = saved(profile)
        trajectory = select_grasp_plan(poses['pickup_approach'], poses['pickup_approach'],
            lambda solve: plan(job, calibration, target, poses, solve, args.robot, args.side),
            wrist_policy='fixed', fixed_wrist_pulse=poses['wait'][4])
        write_json(Path(cfg['samples_file']).with_name('preview-plan.json'), trajectory)
        print(json.dumps({'motors_opened': False, 'pick_model_xyz_mm': trajectory['pick_model_xyz_mm'],
            'basket_side': args.side, 'stages': [s['name'] for s in trajectory['stages']]}, ensure_ascii=False, indent=2))
    elif args.action in ('jog', 'adjust'): jog(cfg, job, profile, args)
    elif args.action == 'fit-spatial': spatial_fit(cfg, job, profile, args)
    elif args.action == 'detect':
        import cv2
        import numpy as np
        from pick_vision import Camera, Detector
        detector = Detector(job, cfg['weights'])
        roi = basket_job(job, args.robot)['regions_uv'][0]
        try:
            with camera_job(), Camera(profile) as camera:
                while True:
                    frame, _ = camera.read()
                    for d in detector.predict(frame):
                        a, b, c, e = map(int, d.box)
                        cv2.rectangle(frame, (a, b), (c, e), (0, 255, 0), 2)
                        cv2.putText(frame, f'{d.label} {d.confidence:.2f}', (a, max(20, b)), 0, .6, (0, 255, 0), 2)
                    cv2.polylines(frame, [np.array(roi, dtype=np.int32)], True, (0, 255, 255), 2)
                    cv2.imshow('C YOLO / yellow = pickup ROI / Q exit', frame)
                    if cv2.waitKey(1) & 255 in (ord('q'), 27): break
        finally: cv2.destroyAllWindows()
    elif args.action == 'run':
        from server.catalog import load_products
        products = load_products()
        if any(s not in products for s in args.skus): parser.error('등록되지 않은 SKU')
        cid = args.job_id or str(uuid.uuid4())
        command = dict(id=cid, kind='HANDOFF', mode='hardware', zone_id='handoff', device_id='omx-c',
            robot_id=args.robot, basket_side=args.side, basket_id='field-' + args.side,
            items=[{'sku': sku, 'slot': i, 'item_id': cid + '-' + str(i)} for i, sku in enumerate(args.skus)])
        print('job-id:', cid, flush=True)
        if not args.execute:
            print(json.dumps({'hardware_executed': False, 'command': command}, ensure_ascii=False, indent=2))
            return
        from scripts.pinky_station import Frames
        cancelled = threading.Event()
        import signal
        signal.signal(signal.SIGINT, lambda *_: cancelled.set())
        with camera_job():
            result = YoloUnloadArm(cfg, None, Frames(False), products).execute(command, cancelled)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
