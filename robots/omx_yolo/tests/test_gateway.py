"""Exercise the central adapter against real planning code and fake devices."""
from contextlib import ExitStack, nullcontext
import copy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
sys.path.insert(0, str(ROOT / 'tools/picking'))
import omx_pick
from pick_core import Detection
from omx_tool_direction import pulse_to_q
from robot_gateway.hardware.yolo import YoloArm


class GatewayTests(unittest.TestCase):
    def setUp(self):
        fixtures = ROOT / 'tests/fixtures'
        self.job = json.loads((fixtures / 'omx_pick.json').read_text())
        self.job['stage_pause_seconds'] = 0
        self.saved = json.loads((fixtures / 'omx_saved_poses.json').read_text())['poses']
        reference = self.job['setup_measurements']['pick_arm_pulses']
        fk = omx_pick.legacy('02_omx_xyz_offline.py', 'gateway_test_fk')
        x, y, _ = (fk.forward(pulse_to_q(reference))[0] * 1000).tolist()
        self.cal = dict(width=100, height=100, matrix_3x3=[[0, 0, x], [0, 0, y], [0, 0, 1]],
                        regions_uv=[[[0, 0], [99, 0], [99, 99], [0, 99]]])
        self.job['regions_source'] = 'calibration'
        self.cfg = dict(arm_name='test', serial_by_id='/dev/fake', camera_by_id='/dev/fake-camera',
                        width=100, height=100, fps=30, calibration_file='unused.json',
                        poses_file='unused.json', pick_config='unused.json',
                        drop_slots={'pinky-1': {'0': {'approach': 'drop_approach', 'release': 'drop_release'}}})
        self.item = dict(sku='TEST', slot=0)
        self.command = dict(zone_id='load-a', robot_id='pinky-1', items=[self.item], scope='device_test')
        self.arm = YoloArm(self.cfg, Mock(), Mock(), {'TEST': {'detector_class': 'jin_ramen'}})
        self.cancelled = threading.Event()
        self.bus = Mock()
        self.bus.read.return_value = 26

    def run_fake(self, execute):
        with ExitStack() as stack:
            for name, value in {
                'pick_core.load_config': self.job,
                'omx_pick.require_job_arm': None,
                'omx_pick.calibration_for': (self.cal, None),
                'omx_pick.legacy': SimpleNamespace(load_pose=lambda name, _: self.saved[name]),
                'pick_vision.Detector': SimpleNamespace(model=SimpleNamespace(names={0: 'jin_ramen'}),
                    predict=lambda _: [Detection('jin_ramen', .99, (40, 40, 60, 60))]),
                'pick_vision.Camera': nullcontext(Mock()),
                'pick_robot.DynamixelBus': nullcontext(self.bus),
                'pick_robot.MotionController.prepare': None,
                'pick_robot.MotionController.enable': None,
                'pick_robot.MotionController.hold': None,
                'robot_gateway.hardware.yolo.SharedCamera': SimpleNamespace(
                    read=lambda: (np.zeros((100, 100, 3)), 0), close=lambda: None),
            }.items():
                stack.enter_context(patch(name, return_value=value))
            # Keep the real FK loader for solver_for, replacing only pose recording.
            real_legacy = self.legacy
            stack.enter_context(patch('omx_pick.legacy', side_effect=lambda name, key:
                SimpleNamespace(load_pose=lambda n, _: self.saved[n]) if name.startswith('07_')
                else real_legacy(name, key)))
            stack.enter_context(patch('pick_core.execute', side_effect=execute))
            return self.arm.execute(self.command, self.cancelled)

    legacy = staticmethod(omx_pick.legacy)

    def test_real_planner_and_short_wrist_move_do_not_claim_loading_success(self):
        plans = []
        def execute(plan, driver):
            plans.append(plan)
            driver.ramp({15: 4069}, seconds=0)
        result = self.run_fake(execute)
        self.assertEqual(len(plans), 1)
        self.assertTrue(any(stage['name'] == 'DROP_RELEASE' for stage in plans[0]['stages']))
        self.bus.write.assert_called_once_with(15, 116, 4, -27)
        self.assertEqual(result, {'attempted_items': [self.item], 'operator_review_required': True})
        self.assertEqual(self.arm.confirmed, [])
        self.arm.evidence.wait.assert_not_called()

    def test_cancelled_ramp_writes_no_target(self):
        def execute(_plan, driver):
            self.cancelled.set()
            driver.ramp({15: 4069}, seconds=0)
        with self.assertRaisesRegex(RuntimeError, '중단'):
            self.run_fake(execute)
        self.bus.write.assert_not_called()

    def test_missing_grasp_reference_fails_before_camera_or_motor(self):
        job = copy.deepcopy(self.job)
        job.pop('setup_measurements', None)
        for rule in job['classes'].values():
            rule.pop('grasp_reference_pulses', None)
        with patch('pick_core.load_config', return_value=job), patch('omx_pick.require_job_arm'), \
                patch('pick_vision.Camera') as camera, patch('pick_robot.DynamixelBus') as bus:
            with self.assertRaisesRegex(ValueError, '집기 방향 기록'):
                self.arm.execute(self.command, self.cancelled)
            camera.assert_not_called()
            bus.assert_not_called()


if __name__ == '__main__':
    unittest.main()
