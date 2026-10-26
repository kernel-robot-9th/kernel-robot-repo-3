import argparse
import json
import os
import subprocess
import sys

from .common import check_session_name, contract, load_config, local_path, task_text, write_json


def main():
    parser = argparse.ArgumentParser(description="OMX VLA local preparation and recording")
    parser.add_argument("--config", default="configs/omx_vla.json")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Import, CUDA and device-presence checks; no motor writes")
    doctor.add_argument("--output", default="reports/environment.json")
    probe = commands.add_parser("probe", help="Dynamixel PING only; no torque/config/position writes")
    probe.add_argument("--output", default="reports/motor-probe.json")
    capture = commands.add_parser("capture", help="Capture camera samples, no motor access")
    capture.add_argument("--output", default="reports/cameras")
    record = commands.add_parser("record", help="Print a plan; --run explicitly connects and records")
    record.add_argument("--basket", type=int, choices=(0, 1), required=True)
    record.add_argument("--session", required=True, help="Capture session ID, used for later dataset splitting")
    record.add_argument("--episodes", type=int, default=5)
    record.add_argument("--root")
    record.add_argument("--resume", action="store_true")
    record.add_argument("--no-display", action="store_true")
    record.add_argument("--run", action="store_true")
    validate = commands.add_parser("validate", help="Check joint/task/review data and decode both videos")
    validate.add_argument("--root")
    validate.add_argument("--require-both", action="store_true")
    validate.add_argument("--output", default="reports/dataset-validation.json")
    review = commands.add_parser("review", help="Show recorded episode in Rerun; no motor replay")
    review.add_argument("--root")
    review.add_argument("--episode", type=int, default=0)
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.command == "doctor":
        from .hardware import doctor
        result = doctor(cfg)
        write_json(local_path(args.output), result)
        code = 0 if result["environment_ok"] else 1
    elif args.command == "probe":
        from .hardware import probe_motors
        result = probe_motors()
        write_json(local_path(args.output), result)
        code = 0 if len(result) == 2 and {r.get("role") for r in result} == {"follower", "leader"} else 1
    elif args.command == "capture":
        from .hardware import capture
        result = capture(cfg, local_path(args.output))
        code = int(any("error" in r for r in result.values()))
    elif args.command == "record":
        check_session_name(args.session)
        if args.episodes < 1:
            parser.error("--episodes must be positive")
        root = local_path(args.root or cfg["recording"]["root"])
        result = {"task": task_text(args.basket), "basket_id": args.basket,
                  "session": args.session, "episodes": args.episodes, "root": str(root),
                  "resume": args.resume, "push_to_hub": False, "contract": contract(cfg),
                  "unconfirmed_views": [k for k, v in cfg["cameras"].items() if not v["view_confirmed"]],
                  "hardware_opened": False}
        if args.run:
            from .recording import run_record
            run_record(cfg, args.basket, args.session, args.episodes, root, args.resume, not args.no_display)
            return 0
        code = 0
    elif args.command == "validate":
        from .validation import validate_dataset
        result = validate_dataset(local_path(args.root or cfg["recording"]["root"]),
                                  args.require_both, local_path(args.output))
        code = 0 if result["ok"] else 1
    else:
        root = local_path(args.root or cfg["recording"]["root"])
        if not (root / "meta/info.json").exists():
            raise ValueError("Local dataset does not exist")
        os.environ["HF_HUB_OFFLINE"] = "1"
        return subprocess.call([sys.executable, "-m", "lerobot.scripts.lerobot_dataset_viz",
            "--repo-id", cfg["recording"]["repo_id"], "--root", str(root),
            "--episode-index", str(args.episode)])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
