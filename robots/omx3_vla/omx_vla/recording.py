"""Interactive, local-only recording; hardware is opened only by record --run."""
import json
import sys
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from .common import (JOINTS, check_session_name, contract, features, local_path,
                     make_frame, task_text, write_json)


def check_resume(root, cfg):
    saved = json.loads((root / "meta/omx_contract.json").read_text())
    if saved != contract(cfg):
        raise ValueError("Dataset camera, calibration, FPS or action contract differs; use a new root")
    info = json.loads((root / "meta/info.json").read_text())
    review_file = root / "meta/omx_reviews.jsonl"
    rows = [json.loads(s) for s in review_file.read_text().splitlines() if s] if review_file.exists() else []
    if (len(rows) != info["total_episodes"] or
            {r["episode_index"] for r in rows} != set(range(info["total_episodes"])) or
            any(r.get("success") is not True for r in rows)):
        raise ValueError("Unreviewed/incomplete dataset; inspect before resuming")


def check_timing(times, cfg):
    import numpy as np
    if len(times) < 2:
        raise ValueError("Episode is too short")
    gaps = np.diff(times)
    if not np.isfinite(times).all() or (gaps <= 0).any():
        raise ValueError("Capture times must be finite and strictly increasing")
    rate = (len(times) - 1) / (times[-1] - times[0])
    if (not np.isfinite(gaps).all() or (gaps <= 0).any() or
            gaps.max() > cfg["max_frame_gap_s"] or
            rate < cfg["fps"] * cfg["minimum_rate_ratio"]):
        raise ValueError(f"Capture timing failed: {rate:.1f} Hz, max gap {gaps.max():.3f}s")
    return {"actual_fps": float(rate), "max_gap_s": float(gaps.max()),
            "p95_gap_s": float(np.quantile(gaps, .95))}


def record_step(robot, leader, dataset, task, max_camera_age_ms=150):
    observation = robot.get_observation()
    now = time.perf_counter()
    for name, cam in robot.cameras.items():
        if cam.latest_timestamp is None or (now - cam.latest_timestamp) * 1000 > max_camera_age_ms:
            raise TimeoutError(f"Stale {name} camera frame")
    command = leader.get_action()
    import numpy as np
    if not all(np.isfinite(observation[k]) and np.isfinite(command[k]) for k in JOINTS):
        raise ValueError("Non-finite state/action; command not sent")
    sent = robot.send_action(command)
    frame = make_frame(observation, sent, task)
    dataset.add_frame(frame)
    return observation, sent


def make_devices(cfg):
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    from lerobot.motors.dynamixel import OperatingMode
    from lerobot.robots.omx_follower import OmxFollower, OmxFollowerConfig
    from lerobot.teleoperators.omx_leader import OmxLeader, OmxLeaderConfig

    class HoldOnConnectFollower(OmxFollower):
        def configure(self):
            # Local counterpart of OMX configure(): seed ALL targets from measured
            # positions after changing modes, before enabling torque.
            with self.bus.torque_disabled():
                self.bus.configure_motors()
                for motor in self.bus.motors:
                    mode = (OperatingMode.CURRENT_POSITION if motor == "gripper"
                            else OperatingMode.EXTENDED_POSITION)
                    self.bus.write("Operating_Mode", motor, mode.value)
                self.bus.write("Position_P_Gain", "elbow_flex", 1500)
                self.bus.write("Position_I_Gain", "elbow_flex", 0)
                self.bus.write("Position_D_Gain", "elbow_flex", 600)
                current = self.bus.sync_read("Present_Position", normalize=False)
                self.bus.sync_write("Goal_Position", current, normalize=False)

    cams = {name: OpenCVCameraConfig(index_or_path=Path(cam["path"]),
                width=cam["width"], height=cam["height"], fps=cam["fps"], fourcc="MJPG")
            for name, cam in cfg["cameras"].items()}
    follower = HoldOnConnectFollower(OmxFollowerConfig(
        port=cfg["robot"]["port"], id=cfg["robot"]["id"],
        calibration_dir=local_path(cfg["robot"]["calibration_dir"]),
        cameras=cams, max_relative_target=cfg["robot"]["max_relative_target"],
        disable_torque_on_disconnect=False))
    leader = OmxLeader(OmxLeaderConfig(port=cfg["leader"]["port"], id=cfg["leader"]["id"],
                                    calibration_dir=local_path(cfg["leader"]["calibration_dir"])))
    return follower, leader


def verify_calibration(device):
    """Read motor configuration without invoking calibrate/configure/torque writes."""
    if not device.calibration:
        raise ValueError(f"Missing calibration: {device.calibration_fpath}")
    try:
        device.bus.connect()
        if not device.is_calibrated:
            raise ValueError(f"Calibration mismatch: {device}; do not overwrite automatically")
    finally:
        if device.bus.is_connected:
            device.bus.disconnect(disable_torque=False)


def close_device(device, follower=False):
    # Also clean up partial connects, for which Robot.is_connected may be false.
    for cam in getattr(device, "cameras", {}).values():
        if cam.is_connected:
            cam.disconnect()
    if device.bus.is_connected:
        device.bus.disconnect(disable_torque=not follower)


def finish_dataset(dataset):
    # Remove unsaved images even if Ctrl+C happened during the success prompt.
    # Otherwise a shorter re-recording could inherit stale frames on resume.
    try:
        if dataset.episode_buffer and dataset.episode_buffer.get("size", 0):
            dataset.clear_episode_buffer()
    finally:
        try:
            dataset.finalize()
        finally:
            dataset.stop_image_writer()


def run_record(cfg, basket, session, episodes, root, resume=False, display=True):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.utils.control_utils import init_keyboard_listener
    from lerobot.utils.visualization_utils import init_rerun, log_rerun_data

    check_session_name(session)
    task = task_text(basket)
    root = Path(root)
    if not sys.stdin.isatty():
        raise ValueError("Run recording in an interactive desktop terminal")
    if episodes < 1:
        raise ValueError("episodes must be positive")
    if any(not c["view_confirmed"] for c in cfg["cameras"].values()):
        raise ValueError("Confirm both camera views in configs/omx_vla.json before recording")
    if resume:
        check_resume(root, cfg)
    elif root.exists():
        raise ValueError("Dataset already exists; use --resume or a different --root")
    acquisition = contract(cfg)
    print(f"Task: {task}\nRoot: {root}\n"
          "한 번에 상품 하나를 옮기고 관측 대기 자세로 복귀하세요.\n"
          "→ 에피소드 종료 / ← 폐기 / Esc 중단. 성공 확인 후에만 저장됩니다.\n"
          "연결 시 팔로워는 현재 자세를 유지하고 리더 그리퍼는 설정 위치로 움직입니다.\n"
          "종료 후 팔로워 토크는 유지됩니다. 지지한 상태에서 현장 종료 절차를 따르세요.")
    if input("팔을 지지하고 작업 공간을 확인했다면 연결하려면 Enter, 취소는 q: ").lower() == "q":
        return
    robot, leader = make_devices(cfg)
    verify_calibration(robot)
    verify_calibration(leader)
    with ExitStack() as stack:
        stack.callback(close_device, robot, True)
        stack.callback(close_device, leader)
        robot.connect(calibrate=False)
        leader.connect(calibrate=False)
        listener, events = init_keyboard_listener()
        if listener is None:
            raise RuntimeError("Desktop keyboard listener required")
        stack.callback(listener.stop)
        if display:
            init_rerun(session_name="omx_vla_recording")
        if resume:
            ds = LeRobotDataset(cfg["recording"]["repo_id"], root=root, vcodec="h264")
            ds.start_image_writer(num_processes=0, num_threads=8)
        else:
            ds = LeRobotDataset.create(cfg["recording"]["repo_id"], cfg["recording"]["fps"],
                features=features(cfg), root=root, robot_type="omx_follower", vcodec="h264",
                image_writer_threads=8, metadata_buffer_size=1)
            write_json(root / "meta/omx_contract.json", acquisition)
        stack.callback(finish_dataset, ds)
        saved = 0
        while saved < episodes and not events["stop_recording"]:
            answer = input(f"바구니 {basket}, 시연 {saved+1}/{episodes}: 배치 후 Enter / 종료 q: ")
            if answer.lower() == "q" or events["stop_recording"]:
                break
            events.update(exit_early=False, rerecord_episode=False)
            obs, target = robot.get_observation(), leader.get_action()
            if max(abs(target[k] - obs[k]) for k in JOINTS) > cfg["robot"]["max_relative_target"]:
                print("리더와 팔로워 자세 차이가 큽니다. 리더를 팔로워 자세에 맞추고 다시 시작하세요.")
                continue
            start = time.perf_counter()
            times = []
            failure = None
            try:
                while time.perf_counter() - start < cfg["recording"]["episode_time_s"]:
                    if events["exit_early"] or events["stop_recording"]:
                        break
                    tick = time.perf_counter()
                    obs, sent = record_step(robot, leader, ds, task,
                                           cfg["recording"]["max_camera_age_ms"])
                    times.append(tick - start)
                    if display:
                        log_rerun_data(observation=obs, action=sent)
                    elapsed = time.perf_counter() - tick
                    if elapsed > cfg["recording"]["max_frame_gap_s"]:
                        raise TimeoutError(f"Control cycle too slow: {elapsed:.3f}s")
                    time.sleep(max(0, 1 / cfg["recording"]["fps"] - elapsed))
                timing = check_timing(times, cfg["recording"])
            except (Exception, KeyboardInterrupt) as exc:
                failure = f"{type(exc).__name__}: {exc}"
                events["stop_recording"] = True
            if failure or events["stop_recording"] or events["rerecord_episode"]:
                ds.clear_episode_buffer()
                print("시연 폐기:", failure or "사용자 중단/재기록")
                continue
            answer = input("상품 1개가 지정 바구니에 들어갔고 팔이 복귀했나요? [y 저장 / n 폐기 / q 종료]: ")
            if answer.lower() != "y" or events["stop_recording"]:
                ds.clear_episode_buffer()
                if answer.lower() == "q":
                    break
                continue
            episode = ds.num_episodes
            ds.save_episode()
            review = {"episode_index": episode, "session": session, "basket_id": basket,
                "success": True, "verification": "human", "task": task, "frames": len(times),
                "capture_times_s": times, "timing": timing,
                "recorded_at": datetime.now(timezone.utc).isoformat()}
            with (root / "meta/omx_reviews.jsonl").open("a") as file:
                file.write(json.dumps(review) + "\n")
            saved += 1
            print(f"Saved episode {episode} ({timing['actual_fps']:.1f} Hz)")
