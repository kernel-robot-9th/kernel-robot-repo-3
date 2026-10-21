"""Fetch the pinned, hash-checked YOLO artifact; keep weights outside Git."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    meta = json.loads((ROOT / 'integrations/sources.json').read_text(encoding='utf-8'))['yolo']
    target = ROOT / 'integrations/omx_yolo/weights/best.pt'
    if target.exists():
        if target.stat().st_size != meta['model_size'] or hashlib.sha256(target.read_bytes()).hexdigest() != meta['model_sha256']:
            raise RuntimeError('기존 YOLO 모델이 등록 해시와 다릅니다. 덮어쓰지 않습니다')
        print('YOLO 모델 SHA-256 일치')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://raw.githubusercontent.com/rheffi/omxtest/{meta['commit']}/weights/best.pt"
    request = urllib.request.Request(url, headers={'User-Agent': 'cartrina-model-preparation'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(meta['model_size'] + 1)
    if len(data) != meta['model_size'] or hashlib.sha256(data).hexdigest() != meta['model_sha256']:
        raise RuntimeError('YOLO 다운로드 크기·해시 불일치')
    with target.open('xb') as output:
        output.write(data)
    print('YOLO 모델 다운로드·해시 검증 완료')


if __name__ == '__main__':
    main()
