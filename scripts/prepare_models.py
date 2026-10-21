"""Download/verify selected Release assets; does not start ACT or any robot."""
import argparse
import json
from pathlib import Path
import sys
import urllib.error
import zipfile

from model_assets import (AssetError, DEFAULT_MANIFEST, ROOT, download_archive,
                          install_archive, read_json, selected, target_directory, verify_files)


def main(argv=None):
    parser = argparse.ArgumentParser(description="ACT 모델 준비·SHA-256 검증 (로봇 실행 없음)")
    parser.add_argument("action", choices=["list", "download", "verify"])
    parser.add_argument("--model", help="config/model_assets.json의 정확한 모델 ID")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--root", type=Path, default=ROOT / "runtime" / "models")
    parser.add_argument("--cache", type=Path, default=ROOT / "runtime" / "model-cache")
    parser.add_argument("--archive", type=Path, help="USB로 옮긴 ZIP에서 오프라인 설치")
    args = parser.parse_args(argv)
    try:
        manifest = read_json(args.manifest)
        if args.action == "list":
            if args.model or args.archive:
                parser.error("list에는 --model/--archive를 사용하지 않습니다")
            print(json.dumps({"repository": manifest["repository"], "models": {
                name: {"direction": entry["direction"], "selection_status": entry["selection_status"],
                       "checkpoint_steps": entry.get("checkpoint_steps"),
                       "reason": entry.get("reason")}
                for name, entry in manifest["models"].items()}}, ensure_ascii=False, indent=2))
            return 0
        if not args.model:
            parser.error("download/verify에는 --model이 필요합니다")
        entry = selected(manifest, args.model)
        target = target_directory(args.root, entry)
        if args.action == "verify":
            if args.archive:
                parser.error("verify는 설치된 폴더를 검사합니다. --archive는 download에만 사용하세요")
            result = verify_files(target, entry)
        elif target.exists():
            result = verify_files(target, entry)
        else:
            archive = args.archive if args.archive else download_archive(manifest, entry, args.cache)
            result = install_archive(archive, args.root, entry)
        print(json.dumps({"model": args.model, "status": "files_verified", "path": str(result),
                          "robot_started": False, "physical_hardware_verified": False},
                         ensure_ascii=False, indent=2))
        return 0
    except urllib.error.HTTPError as exc:
        print(f"모델 준비 실패: GitHub HTTP {exc.code}. Release와 접근 권한을 확인하세요. "
              "비공개 저장소는 GH_TOKEN 또는 GITHUB_TOKEN을 사용하세요.", file=sys.stderr)
    except (AssetError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(f"모델 준비 실패: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
