import json
import threading
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from robots.omx_yolo_unload.core import basket_job, corrected_job, correction_sample, plan, POSES
from robots.omx_yolo_unload.runtime import YoloUnloadArm, create_arm
from robot_gateway.hardware.yolo import YoloArm
from pick_core import Detection, choose, pick_point


@pytest.fixture
def setup():
    region = [[10, 10], [90, 10], [90, 90], [10, 90]]
    job = {'schema_version': 1, 'confidence': .5, 'stage_seconds': 6,
           'pickup_regions_uv': {'pinky-1': region, 'pinky-2': region},
           'gripper': {'open_pulse': 2000, 'close_pulse': 2200, 'current_limit_raw': 100, 'settle_s': .3},
           'classes': {'rice_chip': {'grasp_fraction': [.5, .5], 'xy_offset_mm': [2, 3],
                 'pick_z_mm': 30, 'hover_clearance_mm': 50, 'approach_extra_mm': 40}}}
    cal = {'width': 200, 'height': 200, 'matrix_3x3': [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
           'pixel_hull': [[0, 0], [199, 0], [199, 199], [0, 199]]}
    det = Detection('rice_chip', .9, (20, 20, 40, 40))
    return job, cal, det


def test_large_calibration_does_not_expand_pickup_region(setup):
    job, cal, det = setup
    outside = Detection('rice_chip', .99, (100, 100, 140, 140))
    assert choose([outside, det], basket_job(job, 'pinky-1'), 'rice_chip', 200, 200) == det
    with pytest.raises(ValueError):
        choose([outside], basket_job(job, 'pinky-1'), 'rice_chip', 200, 200)


@pytest.mark.parametrize('side', ['left', 'right'])
def test_order_side_controls_drop_and_release_order(setup, side):
    job, cal, det = setup
    saved = {name: [2000 + i] * 5 for i, name in enumerate(POSES)}
    trajectory = plan(job, cal, det, saved, lambda xyz: [2048]*5, 'pinky-2', side)
    stages = trajectory['stages']
    i = next(i for i, s in enumerate(stages) if s['name'] == 'DROP_RELEASE')
    assert list(stages[i]['target']) == saved[f'drop_{side}_release']
    assert [s['name'] for s in stages[i:i+4]] == ['DROP_RELEASE', 'RELEASE', 'DROP_RETREAT', 'RETURN_HIGH']
    assert list(stages[i+2]['target']) == saved[f'drop_{side}_approach']


def test_interpolation_adds_xy_once_and_uses_absolute_z(setup):
    job, cal, det = setup
    rule = job['classes']['rice_chip']
    rule['spatial_adjustments_by_robot'] = {'pinky-1': {
        'points': [{'xy_mm': p, 'correction_xyz_mm': [5, -7, 12]} for p in [[0, 0], [90, 0], [0, 90]]],
        'triangles': [[0, 1, 2]]}}
    before = deepcopy(job)
    for _ in range(2):
        cfg = corrected_job(job, cal, det, 'pinky-1')
        assert pick_point(cfg, cal, det) == (37, 26, 12)
    assert job == before
    assert pick_point(corrected_job(job, cal, det, 'pinky-2'), cal, det) == (32, 33, 30)
    sample = correction_sample(cal, det, rule, [37, 26, 12])
    assert sample['correction_xyz_mm'] == [5, -7, 12]
    outside = Detection('rice_chip', .9, (140, 140, 160, 160))
    assert pick_point(corrected_job(job, cal, outside, 'pinky-1'), cal, outside) == (157, 146, 12)


def test_partial_result_restart_skips_only_completed_items(tmp_path, monkeypatch):
    command = dict(id='job-1', kind='HANDOFF', robot_id='pinky-1', basket_side='right', basket_id='customer-1',
                   items=[dict(sku='SKU-RICE-CHIP', slot=i, item_id=str(i)) for i in range(3)])
    calls = []
    fail = [True]
    def execute(self, cmd, cancelled):
        self.executed = []
        for item in cmd['items']:
            if item['slot'] == 1 and fail[0]:
                fail[0] = False
                raise RuntimeError('camera disconnected')
            calls.append(item['slot'])
            self.executed.append(item.copy())
            self.item_done(cmd, item, {'stages': []})
    monkeypatch.setattr(YoloArm, 'execute', execute)
    arm = YoloUnloadArm({'journal_directory': str(tmp_path)}, None, None, {})
    with pytest.raises(RuntimeError): arm.execute(command, threading.Event())
    assert arm.executed == command['items'][:1]
    arm = YoloUnloadArm({'journal_directory': str(tmp_path)}, None, None, {})
    result = arm.execute(command, threading.Event())
    assert calls == [0, 1, 2]
    assert result['executed_items'] == command['items']
    assert result['physical_delivery_confirmed'] is False
    arm.execute(command, threading.Event())
    assert calls == [0, 1, 2]
    with pytest.raises(ValueError): arm.execute(dict(command, basket_side='left'), threading.Event())


def test_c_backend_selection_does_not_require_act_for_yolo():
    assert isinstance(create_arm({'unload_engine': 'yolo', 'yolo_unload': {}}, None, None), YoloUnloadArm)
    from robot_gateway.hardware.act import ActArm
    assert isinstance(create_arm({'act': {}}, None, None), ActArm)


def test_remote_handoff_failure_keeps_completed_items(monkeypatch):
    from robot_gateway.hardware import station_remote as remote
    item = {'sku': 'SKU-RICE-CHIP', 'slot': 0, 'item_id': 'first'}
    monkeypatch.setattr(remote, 'run_station', Mock(side_effect=remote.StationError('C',
                        {'reason': 'camera', 'executed_items': [item]})))
    arm = remote.RemoteArm('C')
    with pytest.raises(remote.StationError): arm.execute({'kind': 'HANDOFF'}, threading.Event())
    assert arm.executed == [item]


def test_field_init_is_offline_and_activation_preserves_act(tmp_path):
    from robots.omx_yolo_unload.field import main
    main(['init', '--directory', str(tmp_path), '--serial', '/dev/serial/by-id/C',
          '--camera', '/dev/v4l/by-id/C'])
    hardware = tmp_path / 'gateway-c.yolo.hardware.json'
    target = tmp_path / 'existing.json'
    target.write_text(json.dumps({'node_id': 'gateway-c', 'act': {'models': {'left': 'keep'}}, 'other': 42}))
    main(['--hardware', str(hardware), 'activate', '--target', str(target)])
    assert json.loads(target.read_text())['act'] == {'models': {'left': 'keep'}}
    assert json.loads(target.read_text())['other'] == 42
    assert list(tmp_path.glob('existing.json.*.bak'))


def test_all_cli_dry_run_needs_no_sku_or_devices(tmp_path, capsys):
    from robots.omx_yolo_unload.field import main
    main(['init', '--directory', str(tmp_path), '--serial', '/dev/nonexistent',
          '--camera', '/dev/nonexistent'])
    capsys.readouterr()
    main(['--hardware', str(tmp_path / 'gateway-c.yolo.hardware.json'), 'run',
          '--robot', 'P2', '--side', 'left', '--max-picks', '1'])
    output = capsys.readouterr().out
    payload = json.loads(output[output.index('{'):])
    assert payload['hardware_executed'] is False
    assert payload['command']['items'] == []
    assert payload['command']['selection_mode'] == 'all'
    assert payload['command']['max_picks'] == 1
    assert payload['command']['basket_side'] == 'left'


def test_spatial_fit_roundtrip_and_reteach_do_not_accumulate(tmp_path, setup, monkeypatch):
    pytest.importorskip('cv2')
    from robots.omx_yolo_unload import field
    job, calibration, _ = setup
    cfg = {'samples_file': str(tmp_path/'xy.csv'), 'pick_config': str(tmp_path/'job.json')}
    for name, x, y in [('a', 20, 20), ('b', 70, 20), ('c', 20, 70), ('d', 70, 70), ('center', 45, 45)]:
        det = Detection('rice_chip', .9, (x-1, y-1, x+1, y+1))
        field.record_sample(cfg, job, calibration, det, 'pinky-1', name, [x+7, y-4, 12])
    monkeypatch.setattr(field, 'calibration_for', lambda *a: (calibration, None))
    args = SimpleNamespace(label='rice_chip', robot='pinky-1')
    field.spatial_fit(cfg, job, None, args)
    det = Detection('rice_chip', .9, (44, 44, 46, 46))
    assert pick_point(corrected_job(job, calibration, det, 'pinky-1'), calibration, det) == (52, 41, 12)
    # Re-teach the same center after interpolation: replace sample, never add old correction.
    field.record_sample(cfg, job, calibration, det, 'pinky-1', 'center', [53, 42, 13])
    field.spatial_fit(cfg, job, None, args)
    assert pick_point(corrected_job(job, calibration, det, 'pinky-1'), calibration, det) == (53, 42, 13)
    assert len(job['classes']['rice_chip']['spatial_adjustments_by_robot']['pinky-1']['points']) == 5


def test_shared_pick_loop_dispatches_c_plan_for_each_fresh_item(tmp_path, monkeypatch, setup):
    """Run the real shared loop with fake devices; no SDK, camera or motion."""
    from robot_gateway.hardware import yolo
    import omx_pick
    import pick_robot
    import pick_vision
    job, calibration, det = setup
    job.update(wrist_policy='fixed')
    jobfile = tmp_path/'job.json'
    jobfile.write_text(json.dumps(job))
    cfg = {'arm_name': 'single', 'serial_by_id': '/dev/C', 'camera_by_id': '/dev/camera',
           'width': 200, 'height': 200, 'fps': 30, 'calibration_file': 'unused',
           'poses_file': 'unused', 'pick_config': str(jobfile)}
    class Context:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, *a): return 2048
    camera = Mock(read=Mock(return_value=(SimpleNamespace(shape=(200, 200, 3)), 0)))
    monkeypatch.setattr(pick_vision, 'Camera', Context)
    monkeypatch.setattr(pick_robot, 'DynamixelBus', Context)
    monkeypatch.setattr(pick_vision, 'Detector', lambda *a: SimpleNamespace(
        model=SimpleNamespace(names={0: 'rice_chip'}), predict=lambda f: [det]))
    monkeypatch.setattr(yolo, 'SharedCamera', lambda *a: camera)
    monkeypatch.setattr(omx_pick, 'calibration_for', lambda *a: (calibration, None))
    monkeypatch.setattr(pick_robot.MotionController, 'prepare', lambda self: None)
    monkeypatch.setattr(pick_robot.MotionController, 'enable', lambda self: None)
    monkeypatch.setattr(pick_robot.MotionController, 'hold', lambda self: None)
    # Hooks remove C pose file/IK dependencies while preserving the actual selection loop.
    arm = YoloArm(cfg, None, Mock(), {'rice': {'detector_class': 'rice_chip'}})
    arm.prepare_job = lambda job, cmd, profile: basket_job(job, cmd['robot_id'])
    arm.references = lambda *a: {'rice': [2048]*5}
    calls = []
    def build(job, cal, target, ref, profile, cmd, item, index, wrist):
        calls.append((item['slot'], cmd['basket_side'], wrist))
        return {'stages': []}
    arm.build_item_plan = build
    result = arm.execute({'id': 'test', 'kind': 'HANDOFF', 'zone_id': 'handoff',
        'robot_id': 'pinky-1', 'basket_side': 'right', 'items':
        [{'sku': 'rice', 'slot': i, 'item_id': str(i)} for i in range(3)]}, threading.Event())
    assert calls == [(0, 'right', 2048), (1, 'right', 2048), (2, 'right', 2048)]
    assert camera.read.call_count == 3
    assert len(result['executed_items']) == 3


def test_roi_detector_restores_original_coordinates_and_filters_polygon(setup):
    import numpy as np
    from robots.omx_yolo_unload.vision import BasketDetector
    job, _, _ = setup
    job['pickup_regions_uv']['pinky-1'] = [[10, 10], [90, 10], [10, 90]]
    detector = BasketDetector.__new__(BasketDetector)
    detector.cfg, detector.imgsz = basket_job(job, 'pinky-1'), 640
    detector.cfg['roi_padding_px'] = 0
    def tensor(data):
        return SimpleNamespace(cpu=lambda: SimpleNamespace(tolist=lambda: data))
    boxes = SimpleNamespace(xyxy=tensor([[10, 10, 30, 30], [60, 60, 75, 75], [0, 0, 10, 10]]),
                            conf=tensor([.8, .99, .2]), cls=tensor([0, 0, 0]))
    detector.model = Mock()
    detector.model.predict.return_value = [SimpleNamespace(orig_shape=(81, 81), boxes=boxes,
                                                          names={0: 'rice_chip'})]
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    result = detector.predict(frame)
    assert result == [Detection('rice_chip', .8, (20, 20, 40, 40))]
    kwargs = detector.model.predict.call_args.kwargs
    assert kwargs['source'].shape == (81, 81, 3)
    assert kwargs['agnostic_nms'] is True
    assert kwargs['conf'] == .5
    # Padding clamps at the image boundary without broadening selection ROI.
    detector.cfg['roi_padding_px'] = 64
    detector.model.predict.return_value = [SimpleNamespace(orig_shape=(155, 155), boxes=boxes,
                                                          names={0: 'rice_chip'})]
    assert detector.predict(frame) == [Detection('rice_chip', .8, (10, 10, 30, 30))]
    assert detector.model.predict.call_args.kwargs['source'].shape == (155, 155, 3)
    detector.cfg['regions_uv'] = [[[0, 0], [201, 0], [0, 100]]]
    with pytest.raises(ValueError, match='ROI'):
        detector.predict(frame)


@pytest.fixture
def all_loop(tmp_path, monkeypatch, setup):
    """Real C journal + shared loop, with every device boundary replaced."""
    from robot_gateway.hardware import yolo
    import omx_pick
    import pick_robot
    import pick_vision
    job, calibration, det = setup
    job['wrist_policy'] = 'fixed'
    jobfile = tmp_path / 'job.json'
    jobfile.write_text(json.dumps(job))
    cfg = {'arm_name': 'single', 'serial_by_id': '/dev/C', 'camera_by_id': '/dev/camera',
           'width': 200, 'height': 200, 'fps': 30, 'calibration_file': 'unused',
           'poses_file': 'unused', 'pick_config': str(jobfile), 'selection_mode': 'all',
           'journal_directory': str(tmp_path / 'runs')}
    openings = []
    class Context:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, *a): return 2048
    def bus(*args, **kwargs):
        openings.append(True)
        return Context()
    camera = Mock(read=Mock(return_value=(SimpleNamespace(shape=(200, 200, 3)), 0)))
    monkeypatch.setattr(pick_vision, 'Camera', Context)
    monkeypatch.setattr(pick_robot, 'DynamixelBus', bus)
    monkeypatch.setattr(yolo, 'SharedCamera', lambda *a: camera)
    monkeypatch.setattr(omx_pick, 'calibration_for', lambda *a: (calibration, None))
    for method in ('prepare', 'enable', 'hold'):
        monkeypatch.setattr(pick_robot.MotionController, method, lambda self: None)
    arm = YoloUnloadArm(cfg, None, Mock(), {'rice': {'detector_class': 'rice_chip'}})
    arm.saved = {'pickup_approach': [2048] * 5}
    arm.prepare_job = lambda job, cmd, profile: basket_job(job, cmd['robot_id'])
    detector = SimpleNamespace(model=SimpleNamespace(names={0: 'rice_chip'}), predict=Mock())
    arm.detector_for = lambda *a: detector
    arm.build_item_plan = Mock(return_value={'stages': []})
    command = {'id': 'all-test', 'kind': 'HANDOFF', 'zone_id': 'handoff', 'robot_id': 'pinky-1',
               'basket_side': 'right', 'items': [{'sku': 'not-detected', 'slot': 0}]}
    # Exercise cancellation checks without sleeping in offline tests.
    cancelled = Mock(is_set=Mock(return_value=False), wait=Mock(return_value=False))
    return arm, command, detector, camera, openings, cancelled, det, calibration, jobfile


def test_all_mode_rescans_and_does_not_credit_order_items(all_loop):
    arm, command, detector, camera, openings, cancelled, det, _, _ = all_loop
    detector.predict.side_effect = [[det], [], [det], [], [], []]
    result = arm.execute(command, cancelled)
    assert camera.read.call_count == 6
    assert len(openings) == 1
    assert arm.build_item_plan.call_count == 2
    assert result['executed_items'] == []
    assert len(result['attempted_items']) == 2
    assert result['stop_reason'] == 'no_detections_rechecked'
    assert result['empty_scene_candidate'] is True
    assert result['physical_delivery_confirmed'] is False
    assert result['operator_review_required'] is True
    assert result['basket_side'] == 'right'
    assert json.loads(arm.journal.read_text())['status'] == 'awaiting_operator_review'
    # The same job must look again, not assume previous non-detection meant empty.
    detector.predict.side_effect = [[det], [], [], []]
    result = arm.execute(command, cancelled)
    assert len(result['attempted_items']) == 3
    assert len({i['attempt_id'] for i in result['attempted_items']}) == 3
    assert arm.executed == []


def test_all_mode_empty_scene_never_opens_motors(all_loop):
    arm, command, detector, camera, openings, cancelled, *_ = all_loop
    detector.predict.return_value = []
    result = arm.execute(dict(command, items=[]), cancelled)
    assert camera.read.call_count == 3
    assert openings == []
    assert result['attempted_items'] == []
    assert result['physical_delivery_confirmed'] is False


def test_all_mode_bounds_repeated_missed_grasps(all_loop):
    arm, command, detector, camera, _, cancelled, det, *_ = all_loop
    detector.predict.return_value = [det]
    result = arm.execute(dict(command, max_picks=2), cancelled)
    assert camera.read.call_count == 2
    assert len(result['attempted_items']) == 2
    assert result['stop_reason'] == 'pick_limit_reached'
    assert result['empty_scene_candidate'] is False


@pytest.mark.parametrize('failure', ['missing_z', 'wrong_resolution', 'cancelled'])
def test_all_mode_preflight_failures_do_not_open_motors(all_loop, failure):
    arm, command, detector, _, openings, cancelled, det, calibration, jobfile = all_loop
    detector.predict.return_value = [det]
    if failure == 'missing_z':
        job = json.loads(jobfile.read_text())
        job['classes']['rice_chip']['pick_z_mm'] = None
        jobfile.write_text(json.dumps(job))
    elif failure == 'wrong_resolution':
        calibration['width'] = 201
    else:
        cancelled.is_set.return_value = True
    with pytest.raises((ValueError, RuntimeError)):
        arm.execute(command, cancelled)
    assert openings == []
    assert json.loads(arm.journal.read_text())['status'] == 'interrupted'


def test_all_mode_partial_failure_records_attempts_without_sku_completion(all_loop):
    arm, command, detector, _, _, cancelled, det, *_ = all_loop
    detector.predict.side_effect = [[det], RuntimeError('camera disconnected')]
    with pytest.raises(RuntimeError, match='camera disconnected'):
        arm.execute(command, cancelled)
    history = json.loads(arm.journal.read_text())
    assert len(history['attempted_items']) == 1
    assert history['executed_items'] == arm.executed == []
    assert history['status'] == 'interrupted'


def test_single_plane_calibration_wrapper_writes_c_paths(tmp_path):
    pytest.importorskip('cv2')
    import csv
    import subprocess
    import sys
    from robots.omx_yolo_unload.field import main, profile_for
    from omx_pick import legacy, calibration_for
    main(['init', '--directory', str(tmp_path), '--serial', '/dev/serial/by-id/C', '--camera', '/dev/v4l/by-id/C'])
    hardware = tmp_path/'gateway-c.yolo.hardware.json'
    cfg = json.loads(hardware.read_text())['yolo_unload']
    helper = legacy('05_omx_xy_calibration.py', 'c_calibration_test')
    with (tmp_path/'xy_samples.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=helper.ARM_CSV_FIELDS)
        writer.writeheader()
        for i, (x, y) in enumerate(( (x, y) for x in (100, 300, 500) for y in (100, 300, 500))):
            row = dict.fromkeys(helper.ARM_CSV_FIELDS, '')
            row.update(purpose='train', point_name=str(i), camera=cfg['camera_by_id'], width=1920, height=1080,
                plane_height_mm='unknown', zero_pulses='[2048,2048,2048,2048,2048]', joint_signs='[1,1,1,1,1]',
                u=x, v=y, x_mm=x/2, y_mm=y/2, z_mm=10, tool_axis_x=0, tool_axis_y=0, tool_axis_z=-1,
                arm='single', serial_port=cfg['serial_by_id'])
            writer.writerow(row)
    subprocess.run([sys.executable, '-m', 'robots.omx_yolo_unload', '--hardware', str(hardware),
                    'calibrate', 'fit', '--layout', 'single-plane'], check=True, capture_output=True, text=True)
    data, path = calibration_for(profile_for(cfg), {}, {})
    assert path == tmp_path/'xy_calibration.json'
    assert data['robot_motion_verified'] is False
    assert data['train_error']['max_mm'] < .001
