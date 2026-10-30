"""Enter-to-save overhead photos; no model inference or motor connection."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import select
import sys
import time
import uuid

from .field import ROOT, profile_for
from pick_vision import Camera
from robot_gateway.station_video import camera_job


CATEGORIES = {
    '1': ('rice_chip', '라이스칩'),
    '2': ('shin_ramen', '신라면'),
    '3': ('jin_ramen', '진라면'),
    '4': ('shrimp_cracker', '새우깡'),
    '5': ('cheetos', '치토스'),
    '6': ('seoul_milk', '서울우유'),
    '8': ('mixed', '여러 품목 혼합'),
    '0': ('empty', '빈 바구니'),
}


def terminal_command():
    """Accept terminal Enter too, without blocking the live preview."""
    if not sys.stdin.isatty():
        return None
    if not select.select([sys.stdin], [], [], 0)[0]:
        return None
    line = sys.stdin.readline()
    if not line:
        return None
    return line.strip().lower() or 'save'


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description='C 상단 카메라: Enter 사진 저장 (YOLO·모터 사용 없음)')
    parser.add_argument('--hardware', type=Path,
        default=ROOT / 'runtime/field/c-yolo/gateway-c.yolo.hardware.json')
    parser.add_argument('--output', type=Path,
        default=ROOT / 'runtime/field/c-yolo/dataset_capture')
    parser.add_argument('--category', choices=[v[0] for v in CATEGORIES.values()], default='rice_chip')
    parser.add_argument('--split', choices=('train', 'val'), default='train')
    parser.add_argument('--robot', choices=('P1', 'P2'), default='P1', help='화면 ROI 안내만 선택')
    args = parser.parse_args(argv)

    import cv2
    import numpy as np
    hardware = json.loads(args.hardware.read_text())
    cfg = hardware['yolo_unload']
    profile = profile_for(cfg)
    job = json.loads(Path(cfg['pick_config']).read_text())
    robot = 'pinky-' + args.robot[-1]
    roi = job.get('pickup_regions_uv', {}).get(robot, [])
    session_id = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
    session = args.output.expanduser().resolve() / session_id
    category, split = args.category, args.split
    counts = Counter()
    total = 0
    last_saved = -float('inf')
    status = 'Enter: save original image'
    window = 'C dataset capture - Enter save / 1-6 product / 8 mixed / 0 empty / V split / Q quit'
    try:
        with camera_job(), Camera(profile) as camera:
            session.mkdir(parents=True, exist_ok=False)
            write_json(session / 'session.json', {
                'session_id': session_id,
                'started_at': datetime.now().astimezone().isoformat(),
                'hardware_config': str(args.hardware.resolve()),
                'camera': str(profile.camera), 'width': profile.width,
                'height': profile.height, 'fps': profile.fps,
                'robot_id': robot, 'pickup_roi_uv': roi,
                'inference_roi_padding_px': job.get('roi_padding_px', 64),
                'category_keys': {k: v[0] for k, v in CATEGORIES.items()},
                'bounding_box_annotations_present': False,
                'note': '폴더명은 촬영 분류이며 정답 박스 라벨이 아닙니다. 학습 전 모든 상품의 박스 라벨링이 필요합니다.',
            })
            print('저장 위치:', session, flush=True)
            for key, (name, korean) in CATEGORIES.items():
                print(f'  {key}: {korean} ({name})', flush=True)
            print('Enter: 원본 사진 저장 / V: train·val 전환 / Q 또는 Esc: 종료', flush=True)
            print('미리보기 창에서 키를 누르세요. 터미널에서도 Enter 저장, 숫자+Enter 전환이 됩니다.', flush=True)
            print('위치·각도를 바꾼 뒤 손을 빼고 저장하세요. 사진에 박스 라벨은 아직 없습니다.', flush=True)
            cv2.namedWindow(window, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(window, 1280, 720)
            with (session / 'captures.jsonl').open('x', encoding='utf-8') as log:
                while True:
                    frame, captured_at = camera.read()
                    display = frame.copy()
                    if roi:
                        cv2.polylines(display, [np.asarray(roi, dtype=np.int32)], True, (0, 255, 255), 2)
                    cv2.rectangle(display, (0, 0), (profile.width, 110), (25, 25, 25), -1)
                    lines = [f'{category} | {split} | saved {counts[split, category]} | total {total}',
                             '1 rice  2 shin  3 jin  4 shrimp  5 cheetos  6 milk  8 mixed  0 empty',
                             'ENTER save | V train/val | Q quit | ' + status]
                    for n, line in enumerate(lines):
                        cv2.putText(display, line, (15, 30 + 32 * n), cv2.FONT_HERSHEY_SIMPLEX,
                                    .75, (100, 255, 100), 2, cv2.LINE_AA)
                    cv2.imshow(window, display)
                    code = cv2.waitKey(20)
                    command = None
                    if code >= 0:
                        key = code & 0xff
                        command = 'save' if key in (10, 13) else ('q' if key == 27 else chr(key).lower())
                    # Drain terminal input even when the preview generated an event.
                    typed = terminal_command()
                    command = typed if typed is not None else command
                    if command == 'q' or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                        break
                    if command in CATEGORIES:
                        category = CATEGORIES[command][0]
                        print('촬영 품목:', CATEGORIES[command][1], '|', split, flush=True)
                        status = 'Category changed; reposition product then Enter'
                    elif command == 'v':
                        split = 'val' if split == 'train' else 'train'
                        print('촬영 구분:', split, '(val은 배치를 새로 바꿔 촬영)', flush=True)
                        status = 'Split changed; use a new arrangement'
                    elif command == 'save' and time.monotonic() - last_saved >= .35:
                        directory = session / 'images' / split / category
                        directory.mkdir(parents=True, exist_ok=True)
                        name = f'{session_id}_{total + 1:05d}_{category}.jpg'
                        path = directory / name
                        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                        if not ok:
                            raise RuntimeError('JPEG 변환 실패: 사진을 저장하지 못했습니다')
                        # Save the raw frame, never the display overlay; never overwrite.
                        with path.open('xb') as image_file:
                            image_file.write(encoded.tobytes())
                        log.write(json.dumps({
                            'image': str(path.relative_to(session)), 'category_hint': category,
                            'split': split, 'saved_at': datetime.now().astimezone().isoformat(),
                            'frame_monotonic': captured_at,
                            'width': frame.shape[1], 'height': frame.shape[0],
                            'annotations_status': 'pending',
                        }, ensure_ascii=False) + '\n')
                        log.flush()
                        counts[split, category] += 1
                        total += 1
                        last_saved = time.monotonic()
                        status = f'SAVED #{total}'
                        print(f'저장 {total}: {split}/{category} ({counts[split, category]}장) {path.name}', flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        if session.exists():
            write_json(session / 'summary.json', {
                'total_images': total,
                'counts': {f'{s}/{c}': n for (s, c), n in sorted(counts.items())},
            })
            print(f'촬영 종료: {total}장 / {session}', flush=True)


if __name__ == '__main__':
    main()
