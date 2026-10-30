"""Prepare reviewed Labelme data and train original/augmented C detectors offline."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import time
import traceback

CLASSES = ['shin_ramen', 'jin_ramen', 'rice_chip', 'cheetos']


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def prepare(args):
    import cv2
    import numpy as np
    source, root = args.source.resolve(), args.output.resolve()
    dataset = root / 'dataset'
    dataset.mkdir(exist_ok=False)
    hardware = json.loads(args.hardware.read_text())
    cfg = hardware['yolo_unload']
    job = json.loads(Path(cfg['pick_config']).read_text())
    points = job['pickup_regions_uv']['pinky-1']
    pad = job.get('roi_padding_px', 64)
    # Match BasketDetector's crop exactly, retaining original-image annotations.
    x0 = max(0, math.floor(min(p[0] for p in points)) - pad)
    y0 = max(0, math.floor(min(p[1] for p in points)) - pad)
    x1 = min(cfg['width'], math.ceil(max(p[0] for p in points)) + 1 + pad)
    y1 = min(cfg['height'], math.ceil(max(p[1] for p in points)) + 1 + pad)
    width, height = x1 - x0, y1 - y0
    if width <= 0 or height <= 0:
        raise ValueError('ROI crop dimensions must be positive')
    reviewed_empty = set(args.empty_indices)
    excluded = set(args.exclude_indices)
    records, skipped, clipped = [], [], []
    thumbs = {}
    for image_path in sorted((source / 'images').glob('*.jpg')):
        sequence = int(image_path.stem.split('_')[-2])
        if sequence in excluded:
            skipped.append({'image': image_path.name, 'reason': 'operator_excluded'})
            continue
        annotation = source / 'annotations' / (image_path.stem + '.json')
        if annotation.exists():
            data = json.loads(annotation.read_text())
            if (data['imageWidth'], data['imageHeight']) != (cfg['width'], cfg['height']):
                raise ValueError(f'Annotation resolution mismatch: {annotation}')
            shapes = data['shapes']
        elif sequence in reviewed_empty:
            shapes = []
        else:
            skipped.append({'image': image_path.name, 'reason': 'unreviewed_missing_annotation'})
            continue
        image = cv2.imread(str(image_path))
        if image is None or image.shape[:2] != (cfg['height'], cfg['width']):
            raise ValueError(f'Cannot decode expected image: {image_path}')
        crop = image[y0:y1, x0:x1]
        labels = []
        for shape in shapes:
            name = shape['label']
            if name not in CLASSES or shape.get('shape_type') not in ('polygon', 'rectangle'):
                raise ValueError(f'Unexpected label/shape: {annotation}: {name}')
            xy = np.asarray(shape['points'], dtype=float)
            if xy.ndim != 2 or xy.shape[1] != 2 or len(xy) < 2 or not np.isfinite(xy).all():
                raise ValueError(f'Invalid annotation points: {annotation}')
            a, b = xy.min(axis=0)
            c, d = xy.max(axis=0)
            left, top = max(a, x0), max(b, y0)
            right, bottom = min(c, x1), min(d, y1)
            if right <= left or bottom <= top:
                clipped.append({'image': image_path.name, 'class': name, 'reason': 'outside_crop'})
                continue
            if (left, top, right, bottom) != (a, b, c, d):
                clipped.append({'image': image_path.name, 'class': name, 'reason': 'clipped_to_crop'})
            labels.append([CLASSES.index(name),
                ((left + right) / 2 - x0) / width, ((top + bottom) / 2 - y0) / height,
                (right - left) / width, (bottom - top) / height])
        thumb = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (33, 32))
        thumbs[image_path.name] = thumb
        records.append({'name': image_path.name, 'source': str(image_path), 'sequence': sequence,
            'labels': labels, 'image_sha256': hashlib.sha256(image_path.read_bytes()).hexdigest(),
            'annotation_sha256': hashlib.sha256(annotation.read_bytes()).hexdigest() if annotation.exists() else None,
            'empty_review': 'visually_reviewed_roi' if sequence in reviewed_empty else None})

    # Keep capture bursts and visually near-identical labeled views on one side.
    parents = list(range(len(records)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    def union(a, b):
        parents[find(b)] = find(a)
    for i, left in enumerate(records):
        for j in range(i):
            right = records[j]
            if (left['sequence'] - 1) // 5 == (right['sequence'] - 1) // 5:
                union(i, j)
            elif sorted(x[0] for x in left['labels']) == sorted(x[0] for x in right['labels']):
                difference = np.abs(thumbs[left['name']].astype(float) - thumbs[right['name']]).mean()
                if difference < 1.5:
                    union(i, j)
    groups = {}
    for i, record in enumerate(records):
        groups.setdefault(find(i), []).append(record)
    totals = Counter(label[0] for row in records for label in row['labels'])
    best = None
    rng = random.Random(20261030)
    keys = list(groups)
    if len(keys) < 2 or set(totals) != set(range(4)):
        raise ValueError('Need independent groups and all four classes')
    for _ in range(2000):
        rng.shuffle(keys)
        chosen, count = set(), 0
        for key in keys:
            if count >= len(records) * .2:
                break
            chosen.add(key)
            count += len(groups[key])
        rows = [r for key in chosen for r in groups[key]]
        val_counts = Counter(label[0] for r in rows for label in r['labels'])
        if any(val_counts[c] < 5 or totals[c] - val_counts[c] < 10 for c in range(4)):
            continue
        score = abs(count - len(records) * .2) + sum(abs(val_counts[c] - totals[c] * .2) for c in range(4))
        if not any(not r['labels'] for r in rows):
            score += 5
        if best is None or score < best[0]:
            best = score, chosen.copy()
    if best is None:
        raise ValueError('Could not create a class-balanced grouped split')
    for key, rows in groups.items():
        split = 'val' if key in best[1] else 'train'
        for row in rows:
            row.update(split=split, capture_group=key)
            image = cv2.imread(row['source'])[y0:y1, x0:x1]
            output = dataset / 'images' / split / row['name']
            label_path = dataset / 'labels' / split / (Path(row['name']).stem + '.txt')
            output.parent.mkdir(parents=True, exist_ok=True)
            label_path.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(output), image, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                raise RuntimeError(f'Image write failed: {output}')
            label_path.write_text(''.join(str(int(v[0])) + ' ' + ' '.join(f'{x:.8f}' for x in v[1:]) + '\n' for v in row['labels']))
    data_file = dataset / 'data.yaml'
    data_file.write_text(f'path: {dataset}\ntrain: images/train\nval: images/val\nnames:\n' + ''.join(f'  {i}: {name}\n' for i, name in enumerate(CLASSES)))
    summary = {split: {'images': sum(r['split'] == split for r in records),
        'empty': sum(r['split'] == split and not r['labels'] for r in records),
        'objects': dict(Counter(CLASSES[label[0]] for r in records if r['split'] == split for label in r['labels']))}
        for split in ('train', 'val')}
    save(root / 'dataset-manifest.json', {'classes': CLASSES, 'crop_xyxy': [x0, y0, x1, y1],
        'crop_size': [width, height], 'hardware_source': str(args.hardware.resolve()),
        'job_snapshot': job, 'summary': summary, 'records': records, 'excluded': skipped,
        'clipped_annotations': clipped, 'grouping': 'capture bursts of 5 plus ROI gray-thumbnail MAE < 1.5',
        'limitation': 'Single recording session holdout; not independent field performance.'})
    save(root / 'hardware-snapshot.json', hardware)
    print(json.dumps({'summary': summary, 'excluded': skipped, 'clipped': len(clipped)}, ensure_ascii=False))


def train(args):
    root = args.output.resolve()
    status = root / 'training-status.json'
    state = {'state': 'starting', 'models': {}, 'started_at_unix': time.time()}
    save(status, state)
    try:
        import torch
        from ultralytics import YOLO
        from ultralytics.utils import LOGGER
        if not torch.cuda.is_available():
            raise RuntimeError('GPU is unavailable; refusing silent CPU training')
        LOGGER.setLevel('WARNING')
        manifest = json.loads((root / 'dataset-manifest.json').read_text())
        initial = root / 'initial.pt'
        if not initial.exists():
            shutil.copy2(args.weights, initial)
        state['initial_sha256'] = hashlib.sha256(initial.read_bytes()).hexdigest()
        state['device'] = torch.cuda.get_device_name(0)
        common = dict(data=str(root / 'dataset/data.yaml'), imgsz=640, epochs=100, patience=25,
            batch=16, device=0, workers=2, seed=20261030, deterministic=True,
            amp=False, cache=False, plots=False, verbose=False, project=str(root / 'runs'),
            optimizer='AdamW', lr0=.001, lrf=.01, warmup_epochs=3, weight_decay=.0005,
            save=True, exist_ok=False, hsv_h=0., hsv_s=0., hsv_v=0., degrees=0.,
            translate=0., scale=0., shear=0., perspective=0., flipud=0., fliplr=0.,
            mosaic=0., mixup=0., cutmix=0., copy_paste=0., close_mosaic=0, multi_scale=0.)
        variants = {'original': {}, 'augmented': dict(hsv_h=.005, hsv_s=.15, hsv_v=.25,
            degrees=25., translate=.08, scale=.2, mosaic=.3, close_mosaic=15)}
        save(root / 'training-settings.json', {'common': common, 'variants': variants,
            'classes': CLASSES, 'initial_weights': str(args.weights.resolve())})
        for name, aug in variants.items():
            state.update(state='training', active_model=name, epoch=0)
            save(status, state)
            model = YOLO(str(initial))
            def on_epoch(trainer):
                state.update(epoch=int(trainer.epoch) + 1,
                    latest_metrics={k: float(v) for k, v in trainer.metrics.items()})
                save(status, state)
            model.add_callback('on_fit_epoch_end', on_epoch)
            print('Training:', name, flush=True)
            model.train(**dict(common, **aug, name=name))
            best = Path(model.trainer.best)
            if not best.is_file():
                raise RuntimeError(f'No best checkpoint: {name}')
            ready = root / 'prepared_models'
            ready.mkdir(exist_ok=True)
            output = ready / f'best_{name}.pt'
            shutil.copy2(best, output)
            candidate = YOLO(str(output))
            if list(candidate.names.values()) != CLASSES:
                raise RuntimeError('Trained checkpoint label mapping mismatch')
            metrics = candidate.val(data=common['data'], imgsz=640, batch=16, device=0,
                workers=2, plots=False, verbose=False, project=str(root / 'evaluation'), name=name)
            result = {'weights': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                'metrics': {k: float(v) for k, v in metrics.results_dict.items()},
                'classes': candidate.names, 'epochs': int(model.trainer.epoch) + 1}
            hardware = json.loads((root / 'hardware-snapshot.json').read_text())
            hardware['yolo_unload'].update(weights=str(output), model_classes=CLASSES)
            hardware_file = ready / f'gateway-c.{name}.hardware.json'
            save(hardware_file, hardware)
            result['hardware_config'] = str(hardware_file)
            state['models'][name] = result
            save(status, state)
            del model, candidate
            torch.cuda.empty_cache()
        state.update(state='complete', active_model=None, completed_at_unix=time.time(),
            dataset=manifest['summary'], physical_hardware_executed=False)
        save(status, state)
        save(root / 'prepared_models/results.json', state)
        if args.deliverables:
            args.deliverables.mkdir(parents=True, exist_ok=True)
            for path in (root / 'prepared_models').iterdir():
                shutil.copy2(path, args.deliverables / path.name)
        print('Both models prepared:', root / 'prepared_models', flush=True)
    except BaseException as exc:
        state.update(state='failed', error=str(exc), traceback=traceback.format_exc())
        save(status, state)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'train'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--hardware', type=Path)
    parser.add_argument('--weights', type=Path)
    parser.add_argument('--empty-indices', nargs='*', type=int, default=[])
    parser.add_argument('--exclude-indices', nargs='*', type=int, default=[])
    parser.add_argument('--deliverables', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        if args.source is None or args.hardware is None:
            parser.error('prepare requires --source and --hardware')
        prepare(args)
    else:
        if args.weights is None:
            parser.error('train requires --weights')
        train(args)


if __name__ == '__main__':
    main()
