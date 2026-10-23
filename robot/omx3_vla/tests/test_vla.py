import copy
import json
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from omx_vla.common import JOINTS, ROOT, contract, features, load_config, make_frame, task_text, write_json
from omx_vla.recording import check_resume, check_timing, finish_dataset, record_step, run_record, verify_calibration
from omx_vla.validation import validate_dataset


class RecordingTests(unittest.TestCase):
    def test_interrupted_review_discards_unsaved_images(self):
        calls = []
        ds = SimpleNamespace(episode_buffer={"size": 10},
            clear_episode_buffer=lambda: calls.append("discard"),
            finalize=lambda: calls.append("finalize"),
            stop_image_writer=lambda: calls.append("stop"))
        finish_dataset(ds)
        self.assertEqual(calls, ["discard", "finalize", "stop"])

    def test_sent_action_is_saved_and_stale_camera_blocks_motion(self):
        obs = {k: 0. for k in JOINTS}
        obs.update(front=np.zeros((48, 64, 3), np.uint8), wrist=np.zeros((48, 64, 3), np.uint8))
        frames, calls = [], []
        robot = SimpleNamespace(
            get_observation=lambda: obs,
            cameras={"front": SimpleNamespace(latest_timestamp=time.perf_counter())},
            send_action=lambda action: calls.append(action) or {k: 5. for k in JOINTS})
        leader = SimpleNamespace(get_action=lambda: {k: 100. for k in JOINTS})
        ds = SimpleNamespace(add_frame=frames.append)
        record_step(robot, leader, ds, task_text(0))
        self.assertTrue(np.array_equal(frames[0]["action"], np.full(6, 5.)))
        self.assertEqual(len(calls), 1)
        robot.cameras["front"].latest_timestamp -= 1
        with self.assertRaises(TimeoutError):
            record_step(robot, leader, ds, task_text(0))
        self.assertEqual(len(calls), 1)

    def test_nan_command_never_reaches_motor(self):
        robot = SimpleNamespace(get_observation=lambda: {k: 0. for k in JOINTS}, cameras={},
                                send_action=lambda _: self.fail("Should not send NaN"))
        leader = SimpleNamespace(get_action=lambda: {k: float("nan") for k in JOINTS})
        with self.assertRaises(ValueError):
            record_step(robot, leader, None, task_text(1))

    def test_calibration_mismatch_closes_without_torque_write(self):
        disconnected = []
        device = SimpleNamespace(calibration={"present": True}, is_calibrated=False,
            bus=SimpleNamespace(is_connected=True, connect=lambda: None,
                                disconnect=lambda disable_torque: disconnected.append(disable_torque)))
        with self.assertRaises(ValueError):
            verify_calibration(device)
        self.assertEqual(disconnected, [False])

    def test_timing_drop_is_rejected(self):
        cfg = load_config()["recording"]
        self.assertAlmostEqual(check_timing([0, 1/30, 2/30], cfg)["actual_fps"], 30)
        for bad in ([0, .3], [0, .05, .10], [0, 0]):
            with self.assertRaises((ValueError, ZeroDivisionError)):
                check_timing(bad, cfg)

    def test_dry_run_and_invalid_basket(self):
        result = subprocess.run([sys.executable, "-m", "omx_vla", "record", "--basket", "1",
                                 "--session", "test"], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertFalse(plan["hardware_opened"])
        self.assertFalse(plan["push_to_hub"])
        self.assertEqual(plan["task"], task_text(1))
        for value in ("0", -1, 2, True):
            with self.assertRaises(ValueError):
                task_text(value)


class DatasetIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
        cls.temp = tempfile.TemporaryDirectory(prefix="omx-vla-test-")
        cls.root = Path(cls.temp.name) / "dataset"
        cls.cfg = copy.deepcopy(load_config())
        for cam in cls.cfg["cameras"].values():
            cam.update(height=48, width=64)
        ds = LeRobotDataset.create("local/omx3_pinky_all", 30, features=features(cls.cfg),
            root=cls.root, robot_type="omx_follower", vcodec="h264", metadata_buffer_size=1)
        reviews = []
        try:
            for basket in (0, 1):
                for i in range(12):
                    obs = {k: float(i) for k in JOINTS}
                    obs.update(front=np.full((48, 64, 3), i*10, np.uint8),
                               wrist=np.full((48, 64, 3), 255-i*10, np.uint8))
                    ds.add_frame(make_frame(obs, {k: float(i+1) for k in JOINTS}, task_text(basket)))
                ds.save_episode()
                times = [i/30 for i in range(12)]
                reviews.append({"episode_index": basket, "basket_id": basket, "session": "synthetic_test",
                    "task": task_text(basket), "success": True, "verification": "human",
                    "frames": 12, "capture_times_s": times,
                    "timing": check_timing(times, cls.cfg["recording"])})
        finally:
            ds.finalize()
            ds.stop_image_writer()
        write_json(cls.root / "meta/omx_contract.json", contract(cls.cfg))
        cls.reviews_path = cls.root / "meta/omx_reviews.jsonl"
        cls.original_reviews = "".join(json.dumps(r)+"\n" for r in reviews)
        cls.reviews_path.write_text(cls.original_reviews)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def tearDown(self):
        self.reviews_path.write_text(self.original_reviews)

    def test_real_parquet_and_two_camera_videos_decode(self):
        result = validate_dataset(self.root, require_both=True)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(len(result["episodes"]), 2)
        self.assertIn("passed", result["video_decode"])

    def test_wrong_basket_label_is_rejected(self):
        reviews = [json.loads(x) for x in self.original_reviews.splitlines()]
        reviews[0]["basket_id"] = 1
        self.reviews_path.write_text("".join(json.dumps(r)+"\n" for r in reviews))
        result = validate_dataset(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(any("basket/task" in e for e in result["errors"]))

    def test_resume_rejects_camera_or_calibration_change(self):
        check_resume(self.root, self.cfg)
        bad = copy.deepcopy(self.cfg)
        bad["cameras"]["front"]["width"] += 2
        with self.assertRaises(ValueError):
            check_resume(self.root, bad)

    def test_record_flow_saves_only_human_accepted_episode(self):
        for accepted in (True, False):
            with self.subTest(accepted=accepted):
                cfg = copy.deepcopy(self.cfg)
                cfg["recording"]["episode_time_s"] = .15
                for cam in cfg["cameras"].values():
                    cam["view_confirmed"] = True
                root = Path(self.temp.name) / ("accepted" if accepted else "discarded")
                camera = SimpleNamespace(latest_timestamp=time.perf_counter())
                def observation():
                    camera.latest_timestamp = time.perf_counter()
                    return {**{k: 0. for k in JOINTS},
                            "front": np.zeros((48, 64, 3), np.uint8),
                            "wrist": np.zeros((48, 64, 3), np.uint8)}
                robot = SimpleNamespace(get_observation=observation, cameras={"front": camera},
                    connect=lambda **_: None, send_action=lambda _: {k: 5. for k in JOINTS})
                leader = SimpleNamespace(connect=lambda **_: None,
                                         get_action=lambda: {k: 0. for k in JOINTS})
                events = dict(exit_early=False, rerecord_episode=False, stop_recording=False)
                answers = ["", "", "y"] if accepted else ["", "", "n", "q"]
                with patch("sys.stdin.isatty", return_value=True), \
                     patch("builtins.input", side_effect=answers), \
                     patch("omx_vla.recording.make_devices", return_value=(robot, leader)), \
                     patch("omx_vla.recording.verify_calibration"), \
                     patch("omx_vla.recording.close_device"), \
                     patch("lerobot.utils.control_utils.init_keyboard_listener", return_value=(SimpleNamespace(stop=lambda: None), events)):
                    run_record(cfg, 0, "flow_test", 1, root, display=False)
                info = json.loads((root / "meta/info.json").read_text())
                self.assertEqual(info["total_episodes"], int(accepted))
                if accepted:
                    result = validate_dataset(root)
                    self.assertTrue(result["ok"], result["errors"])
                else:
                    self.assertFalse((root / "meta/omx_reviews.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
