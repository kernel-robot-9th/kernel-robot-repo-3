"""Check recorded data and decode frames; never command a robot."""
import json
import os
from pathlib import Path

from .common import JOINTS, task_text, write_json


def validate_dataset(root, require_both=False, output=None):
    import numpy as np
    import pyarrow.parquet as pq
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    root = Path(root).resolve()
    result = {"root": str(root), "errors": [], "warnings": [], "episodes": []}
    errors = result["errors"]
    for path in ("meta/info.json", "meta/omx_contract.json", "meta/omx_reviews.jsonl"):
        if not (root / path).is_file():
            errors.append(f"Missing {path}")
    if errors:
        result["ok"] = False
        if output:
            write_json(output, result)
        return result
    info = json.loads((root / "meta/info.json").read_text())
    acquisition = json.loads((root / "meta/omx_contract.json").read_text())
    reviews = [json.loads(line) for line in (root / "meta/omx_reviews.jsonl").read_text().splitlines() if line]
    review_by_ep = {r["episode_index"]: r for r in reviews}
    if len(review_by_ep) != len(reviews):
        errors.append("Duplicate episode reviews")
    for key in ("observation.state", "action"):
        ft = info["features"].get(key, {})
        if ft.get("shape") != [6] or ft.get("names") != JOINTS:
            errors.append(f"Wrong dimensions/joint order: {key}")
    if info["fps"] != acquisition["fps"] or info["robot_type"] != "omx_follower":
        errors.append("Wrong FPS/robot type")
    datafiles = sorted((root / "data").rglob("*.parquet"))
    if not datafiles:
        errors.append("No frame parquet files")
    else:
        import pyarrow as pa
        table = pa.concat_tables([pq.read_table(p) for p in datafiles]).to_pandas()
        if len(table) != info["total_frames"]:
            errors.append("Frame count differs from metadata")
        for key in ("observation.state", "action"):
            array = np.stack(table[key].to_numpy())
            if array.shape != (len(table), 6) or not np.isfinite(array).all():
                errors.append(f"Invalid/non-finite values: {key}")
        observed_eps = set(map(int, table["episode_index"].unique()))
        if observed_eps != set(range(info["total_episodes"])):
            errors.append("Episode index/count mismatch")
        if observed_eps != set(review_by_ep):
            errors.append("Missing/orphan success reviews")
        # LeRobot uses uniform frame timestamps. Actual capture intervals are
        # retained independently in human review records.
        for ep, group in table.groupby("episode_index", sort=True):
            ep = int(ep)
            if not np.array_equal(group["frame_index"], np.arange(len(group))):
                errors.append(f"Episode {ep}: noncontiguous frame indices")
            if not np.allclose(group["timestamp"], np.arange(len(group)) / info["fps"], atol=1e-4):
                errors.append(f"Episode {ep}: timestamp mismatch")
            review = review_by_ep.get(ep, {})
            if review.get("success") is not True or review.get("verification") != "human":
                errors.append(f"Episode {ep}: success not reviewed")
            basket = review.get("basket_id")
            if type(basket) is not int or basket not in (0, 1):
                errors.append(f"Episode {ep}: invalid basket ID")
            elif review.get("task") != task_text(basket):
                errors.append(f"Episode {ep}: basket/task mismatch")
            times = review.get("capture_times_s", [])
            if len(times) != len(group) or len(times) < 2 or not np.isfinite(times).all() or (np.diff(times) <= 0).any():
                errors.append(f"Episode {ep}: invalid actual capture timing")
            result["episodes"].append({"episode_index": ep, "frames": len(group),
                "basket_id": basket, "session": review.get("session"), "timing": review.get("timing")})
        # Decode first/middle/last frames of EVERY episode, including offset video
        # chunks, via the same dataset access used by the trainer.
        previous = os.environ.get("HF_HUB_OFFLINE")
        os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            ds = LeRobotDataset("local/omx3_pinky_all", root=root)
            for ep, group in table.groupby("episode_index", sort=True):
                review = review_by_ep.get(int(ep), {})
                for global_index in group["index"].iloc[[0, len(group)//2, -1]].unique():
                    sample = ds[int(global_index)]
                    if sample["task"] != review.get("task"):
                        errors.append(f"Episode {ep}: recorded task differs from reviewed basket")
                    for camera in ("front", "wrist"):
                        key = f"observation.images.{camera}"
                        frame = sample[key]
                        h, w, _ = info["features"][key]["shape"]
                        if tuple(frame.shape) != (3, h, w) or not frame.isfinite().all():
                            errors.append(f"Episode {ep}: invalid {camera} image")
            result["video_decode"] = "first/middle/last frame of every episode passed"
        except Exception as exc:
            errors.append(f"Dataset/video decode: {type(exc).__name__}: {exc}")
        finally:
            if previous is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = previous
    baskets = {r.get("basket_id") for r in reviews}
    if baskets != {0, 1}:
        (errors if require_both else result["warnings"]).append("Both basket 0 and 1 demonstrations are required before training")
    result["warnings"].append("Schema/video checks do not certify grasp success. Review videos and split by capture session.")
    result["ok"] = not errors
    if output:
        write_json(output, result)
    return result
