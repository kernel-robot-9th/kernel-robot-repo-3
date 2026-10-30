"""C-only ROI inference. All returned coordinates remain in the original image."""
import math

from .core import basket_job  # Initializes the shared picking module path.
from pick_core import Detection, get_rule, inside, integer, polygon
from pick_vision import Detector


def eligible(detections, job, width, height):
    regions = [polygon(r, 'regions_uv') for r in job.get('regions_uv', [])]
    if not regions or any(not (0 <= x < width and 0 <= y < height)
                          for r in regions for x, y in r):
        raise ValueError('C 집기 ROI가 없거나 영상 범위를 벗어났습니다')
    selected = []
    for det in detections:
        det.validate(width, height)
        if det.confidence < job['confidence']:
            continue
        point = det.point(get_rule(job, det.label))
        if any(inside(point, r) for r in regions):
            selected.append(det)
    return sorted(selected, key=lambda d: (-d.confidence, d.box, d.label))


class BasketDetector(Detector):
    def predict(self, frame):
        height, width = frame.shape[:2]
        eligible([], self.cfg, width, height)  # Validate even on an empty scene.
        points = [p for r in self.cfg['regions_uv'] for p in r]
        # Keep packaging context at the edge; selection still uses the exact ROI.
        padding = integer(self.cfg.get('roi_padding_px', 64), 'roi_padding_px', 0, 512)
        x0 = max(0, math.floor(min(p[0] for p in points)) - padding)
        y0 = max(0, math.floor(min(p[1] for p in points)) - padding)
        x1 = min(width, math.ceil(max(p[0] for p in points)) + 1 + padding)
        y1 = min(height, math.ceil(max(p[1] for p in points)) + 1 + padding)
        crop = frame[y0:y1, x0:x1]
        result = self.model.predict(source=crop, conf=self.cfg['confidence'],
            imgsz=self.imgsz, device=self.cfg.get('device', 'cpu'),
            agnostic_nms=True, verbose=False, save=False)[0]
        if tuple(result.orig_shape) != crop.shape[:2]:
            raise ValueError('YOLO 결과 원본 해상도가 ROI 입력과 다릅니다')
        if result.boxes is None:
            return []
        detections = []
        for box, score, cls in zip(result.boxes.xyxy.cpu().tolist(),
                result.boxes.conf.cpu().tolist(), result.boxes.cls.cpu().tolist()):
            a, b, c, d = box
            local = Detection(result.names[int(cls)], float(score), tuple(box), int(cls))
            local.validate(x1 - x0, y1 - y0)
            detections.append(Detection(local.label, local.confidence,
                (a + x0, b + y0, c + x0, d + y0), local.class_id))
        return eligible(detections, self.cfg, width, height)
