"""Create a Release ZIP and candidate manifest entry from a chosen checkpoint."""
import argparse
import json
from pathlib import Path
import sys

from model_assets import AssetError, ROOT, package_model


def main():
    parser = argparse.ArgumentParser(description="선정한 ACT 모델의 Release ZIP 생성 (업로드·로봇 실행 없음)")
    parser.add_argument("--source", type=Path, required=True, help="실행용 파일 7개의 pretrained_model 폴더")
    parser.add_argument("--model", required=True, help="예: act-left-v2-050000")
    parser.add_argument("--direction", choices=["left", "right"], required=True)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "runtime" / "model-releases")
    args = parser.parse_args()
    try:
        archive, entry = package_model(args.source, args.output, args.model, args.direction, args.steps, args.tag)
        print(json.dumps({"archive": str(archive), "manifest_entry": str(entry),
                          "uploaded": False, "robot_started": False}, ensure_ascii=False, indent=2))
        return 0
    except (AssetError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"모델 패키지 생성 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
