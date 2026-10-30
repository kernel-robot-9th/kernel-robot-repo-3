"""Prepare a C handoff archive; no network, deployment, or device execution."""
import argparse
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def source_files():
    files = set()
    for directory in ('robots/omx_yolo/tools', 'robots/omx_yolo_unload', 'robot_gateway'):
        for path in (ROOT / directory).rglob('*'):
            if path.is_file() and path.suffix in ('.py', '.md', '.txt', '.json') and '__pycache__' not in path.parts:
                files.add(path.relative_to(ROOT))
    for name in ('robots/omx_yolo/__init__.py', 'robots/omx_yolo/requirements-pick.txt',
                 'robots/omx_yolo/requirements-pick-core.txt', 'scripts/pinky_station.py',
                 'scripts/run_pinky_station.sh', 'robots/omx_act/runtime.py',
                 'robot_gateway/hardware/act.py', 'server/catalog.py', 'config/products.json'):
        files.add(Path(name))
    return sorted(files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime/field/c-yolo-code.tar.gz')
    args = parser.parse_args()
    files = source_files()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, 'w:gz') as archive:
        for path in files: archive.add(ROOT / path, arcname=path, recursive=False)
    print(f'{args.output}: {len(files)} files; 현장 JSON·모델 가중치·가상환경 제외')


if __name__ == '__main__':
    main()
