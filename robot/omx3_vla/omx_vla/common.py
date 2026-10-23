import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Keep derived dataset caches writable in this project; model cache remains unchanged.
os.environ.setdefault("HF_DATASETS_CACHE", str(ROOT / ".cache/huggingface/datasets"))
JOINTS = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos",
          "wrist_flex.pos", "wrist_roll.pos", "gripper.pos"]


def task_text(basket):
    if type(basket) is not int or basket not in (0, 1):
        raise ValueError("basket must be 0 or 1")
    return f"Move all items from the Pinky tray into basket {basket}."


def local_path(value):
    p = Path(value).expanduser()
    return p if p.is_absolute() else ROOT / p


def load_config(path=None):
    cfg = json.loads(local_path(path or "configs/omx_vla.json").read_text())
    if cfg["schema_version"] != 1 or set(cfg["baskets"]) != {"0", "1"}:
        raise ValueError("Unsupported config or basket IDs")
    if set(cfg["cameras"]) != {"front", "wrist"}:
        raise ValueError("Both front and wrist cameras are required")
    if cfg["robot"]["port"] == cfg["leader"]["port"]:
        raise ValueError("Leader and follower ports must differ")
    if cfg["robot"]["max_relative_target"] <= 0:
        raise ValueError("max_relative_target must be positive")
    if cfg["recording"]["fps"] <= 0 or cfg["recording"]["episode_time_s"] <= 0:
        raise ValueError("Recording rate and duration must be positive")
    for cam in cfg["cameras"].values():
        if min(cam["width"], cam["height"], cam["fps"]) <= 0:
            raise ValueError("Invalid camera dimensions/rate")
        if cam["fps"] != cfg["recording"]["fps"]:
            raise ValueError("Camera and recording FPS must agree")
    return cfg


def features(cfg):
    result = {key: {"dtype": "float32", "shape": (6,), "names": JOINTS}
              for key in ("observation.state", "action")}
    for name, cam in cfg["cameras"].items():
        result[f"observation.images.{name}"] = {
            "dtype": "video", "shape": (cam["height"], cam["width"], 3),
            "names": ["height", "width", "channels"]}
    return result


def make_frame(observation, sent_action, task):
    """Use send_action's result, including any clipping, as the training target."""
    import numpy as np
    frame = {
        "observation.state": np.array([observation[k] for k in JOINTS], dtype=np.float32),
        "action": np.array([sent_action[k] for k in JOINTS], dtype=np.float32),
        "task": task,
    }
    if not all(np.isfinite(frame[k]).all() for k in ("observation.state", "action")):
        raise ValueError("Non-finite robot data")
    for name in ("front", "wrist"):
        frame[f"observation.images.{name}"] = observation[name]
    return frame


def contract(cfg):
    """Immutable acquisition settings: reject incompatible dataset appends."""
    return {
        "schema_version": 1, "fps": cfg["recording"]["fps"],
        "features": json.loads(json.dumps(features(cfg))),
        "tasks": [task_text(0), task_text(1)], "baskets": cfg["baskets"],
        "units": {"arm": "LeRobot RANGE_M100_100", "gripper": "LeRobot RANGE_0_100"},
        "ports": {r: cfg[r]["port"] for r in ("robot", "leader")},
        "cameras": {k: {a: v[a] for a in ("path", "width", "height", "fps")}
                    for k, v in cfg["cameras"].items()},
        "calibration_sha256": {
            r: hashlib.sha256((local_path(cfg[r]["calibration_dir"]) /
                               (cfg[r]["id"] + ".json")).read_bytes()).hexdigest()
            for r in ("robot", "leader")},
        "action_source": "robot.send_action return value",
        "episode_unit": "one item placed, then return to observation pose",
    }


def check_session_name(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name):
        raise ValueError("session must use letters, numbers, '_' or '-' (max 80)")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
