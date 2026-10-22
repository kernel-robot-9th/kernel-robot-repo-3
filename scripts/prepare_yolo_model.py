"""Fetch the pinned team Release asset; no robot imports or execution."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def prepare(meta, target, archive=None):
    target = Path(target)
    def verified(data):
        if len(data) != meta['model_size'] or hashlib.sha256(data).hexdigest() != meta['model_sha256']:
            raise ValueError('YOLO 모델 크기·SHA-256 불일치. 기존 파일을 덮어쓰지 않습니다')
    if target.exists():
        verified(target.read_bytes())
        return target
    if archive:
        with Path(archive).open('rb') as source:
            data = source.read(meta['model_size'] + 1)
    else:
        release = meta['release']
        tag, asset = (urllib.parse.quote(release[key], safe='') for key in ('tag', 'asset'))
        url = f"https://github.com/{release['repository']}/releases/download/{tag}/{asset}"
        request = urllib.request.Request(url, headers={'User-Agent': 'cartrina-model-preparation'})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(meta['model_size'] + 1)
    verified(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Verify before writing; exclusive creation preserves another installation.
    with target.open('xb') as output:
        output.write(data)
    return target


def main():
    parser = argparse.ArgumentParser(description='YOLO 모델 준비 (로봇 실행 없음)')
    parser.add_argument('--archive', type=Path, help='USB로 옮긴 .pt 파일에서 오프라인 설치')
    parser.add_argument('--target', type=Path, default=ROOT / 'robots/omx_yolo/weights/best.pt')
    args = parser.parse_args()
    meta = json.loads((ROOT / 'integrations/sources.json').read_text(encoding='utf-8'))['yolo']
    result = prepare(meta, args.target, args.archive)
    print(json.dumps({'status': 'files_verified', 'path': str(result),
                      'robot_started': False, 'physical_hardware_verified': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
