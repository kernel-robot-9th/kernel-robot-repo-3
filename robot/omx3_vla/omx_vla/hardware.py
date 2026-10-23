"""Inspection commands use only camera reads and Dynamixel PING."""
import importlib
import importlib.metadata
import time
from pathlib import Path

from .common import write_json


def probe_motors():
    from dynamixel_sdk import COMM_SUCCESS, PacketHandler, PortHandler
    results = []
    for path in sorted(Path("/dev/serial/by-id").glob("*ROBOTIS_OpenRB*")):
        entry = {"path": str(path), "device": str(path.resolve()), "motors": {}}
        port = PortHandler(str(path))
        try:
            if not port.openPort() or not port.setBaudRate(1_000_000):
                raise OSError("Could not open port at 1 Mbps")
            packet = PacketHandler(2.0)
            for motor_id in [1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 15, 16]:
                model, result, error = packet.ping(port, motor_id)
                if result == COMM_SUCCESS:
                    entry["motors"][str(motor_id)] = {"model": model, "error": error}
            ids = set(map(int, entry["motors"]))
            entry["role"] = ("leader" if ids == set(range(1, 7)) else
                             "follower" if ids == set(range(11, 17)) else "unknown")
        except Exception as exc:
            entry["error"] = str(exc)
        finally:
            port.closePort()
        results.append(entry)
    return results


def doctor(cfg):
    results = {"packages": {}, "imports": {}, "devices": {}, "ready_for_recording": False}
    for name in ("torch", "torchvision", "lerobot", "transformers", "tokenizers",
                 "num2words", "dynamixel-sdk", "av", "datasets"):
        try:
            results["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            results["packages"][name] = "MISSING"
    for name in ("lerobot.policies.smolvla.modeling_smolvla",
                 "lerobot.policies.smolvla.processor_smolvla", "lerobot.datasets.lerobot_dataset"):
        try:
            importlib.import_module(name)
            results["imports"][name] = "ok"
        except Exception as exc:
            results["imports"][name] = f"{type(exc).__name__}: {exc}"
    try:
        import torch
        x = torch.ones((32, 32), device="cuda")
        assert (x @ x).sum().item() == 32768
        results["gpu"] = {"name": torch.cuda.get_device_name(0),
                          "memory_bytes": torch.cuda.get_device_properties(0).total_memory,
                          "cuda": torch.version.cuda, "matrix_test": "ok"}
    except Exception as exc:
        results["gpu"] = {"error": str(exc)}
    for role in ("robot", "leader"):
        p = Path(cfg[role]["port"])
        results["devices"][role] = {"present": p.exists(), "device": str(p.resolve())}
    for role, cam in cfg["cameras"].items():
        p = Path(cam["path"])
        results["devices"][role] = {"present": p.exists(), "device": str(p.resolve()),
                                    "view_confirmed": cam["view_confirmed"]}
    results["environment_ok"] = (all(v == "ok" for v in results["imports"].values())
                                  and results["gpu"].get("matrix_test") == "ok")
    results["ready_for_recording"] = (results["environment_ok"] and
        all(v["present"] and v.get("view_confirmed", True) for v in results["devices"].values()))
    results["note"] = "No motor movement or pretrained-weight inference tested. Record performs calibration checks."
    return results


def capture(cfg, output):
    import cv2
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, cam in cfg["cameras"].items():
        cap = cv2.VideoCapture(cam["path"], cv2.CAP_V4L2)
        try:
            if not cap.isOpened():
                raise OSError("Camera unavailable. Close ffplay/other camera owners first.")
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, cam["width"])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cam["height"])
            cap.set(cv2.CAP_PROP_FPS, cam["fps"])
            times = []
            for _ in range(35):
                ok, frame = cap.read()
                if not ok:
                    raise OSError("Frame read failed")
                times.append(time.perf_counter())
            path = output / f"{name}.jpg"
            if not cv2.imwrite(str(path), frame):
                raise OSError("Could not save image")
            result[name] = {"path": str(path.resolve()), "shape": list(frame.shape),
                            "measured_fps": 29 / (times[-1] - times[-30])}
        except Exception as exc:
            result[name] = {"error": str(exc)}
        finally:
            cap.release()
    write_json(output / "capture.json", result)
    return result
