"""Remote station endpoint; imports alone never touch hardware."""
import base64
import json
from pathlib import Path
import sys
import threading
import time


class Frames:
    def __init__(self, enabled):
        self.enabled, self.last = enabled, 0.

    def offer(self, channel, frame, color='BGR'):
        from robot_gateway.station_video import cache_frame
        cache_frame(channel, frame, color)
        if not self.enabled or time.monotonic()-self.last < .2:
            return
        import cv2
        self.last = time.monotonic()
        if color == 'RGB': frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        height,width = frame.shape[:2]
        frame = cv2.resize(frame,(640,round(height*640/width)))
        ok, encoded = cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,65])
        if ok:
            print('CARTRINA_FRAME='+json.dumps([channel,base64.b64encode(encoded).decode()]),flush=True)


def execute(request):
    zone = request['zone']
    frames = Frames(request.get('stream_frames', False))
    cancelled, done = threading.Event(), threading.Event()
    def cancellation():
        path = Path('runtime/field/station-jobs')/(request['job_id']+'.cancel')
        while not done.wait(.1):
            if path.exists():
                cancelled.set(); path.unlink(); return
    if request.get('job_id'):
        threading.Thread(target=cancellation, daemon=True).start()
    if request['operation'] == 'parking':
        from scripts.pinky_parking import run_parking
        return run_parking(request['mode'], request['robot'], zone,
                           headless=not request.get('interactive', False),
                           terminal=request.get('interactive', False), cancelled=cancelled, frames=frames,
                           **request.get('options', {}))
    if request['operation'] == 'inventory':
        config = json.loads(Path('runtime/field/pinky-parking.json').read_text())
        result = {}
        for key, filename in [('targets_file', 'targets.json'), ('geometry_file', 'geometry.json'),
                              ('observation_file', 'observations.json')]:
            path = Path(config.get(key, str(Path(config['targets_file']).with_name(filename))))
            data = json.loads(path.read_text()) if path.exists() else {}
            result[key] = list(data.get('targets', data))
        return result
    from robot_gateway.hardware.evidence import EvidenceFiles
    from server.catalog import load_products
    config = json.loads(Path(f'runtime/field/gateway-{zone.lower()}.hardware.json').read_text())
    evidence = EvidenceFiles(config['evidence_directory'])
    if zone == 'C':
        from robot_gateway.hardware.act import ActArm
        arm = ActArm(config['act'], evidence, frames)
    else:
        from robot_gateway.hardware.yolo import YoloArm
        arm = YoloArm(config['yolo'], evidence, frames, load_products())
    command = request['command']
    if zone == 'C' and command['kind'] == 'HANDOFF':
        command['model_id'] = config['act']['models'][command['basket_side']]['id']
    if request.get('interactive') and command['kind'] == 'HANDOFF':
        original_read = evidence.read
        finished = threading.Event()
        def finish():
            input('하역 완료 후 Enter: ')
            finished.set()
        threading.Thread(target=finish, daemon=True).start()
        evidence.read = lambda cmd, kind: ({'source': 'operator'} if finished.is_set()
                                          else original_read(cmd, kind))
    method = getattr(arm, {'STOP': 'stop', 'STOP_POLICY': 'stopped'}.get(command['kind'], 'execute'))
    try:
        return method(command, cancelled)
    except Exception as exc:
        print('CARTRINA_ERROR='+json.dumps({'reason': str(exc),
            'executed_items': getattr(arm, 'executed', []) if command['kind'] == 'PICK' else [],
            'physical_loading_confirmed': False}, ensure_ascii=False), flush=True)
        raise
    finally:
        done.set()


if __name__ == '__main__':
    from robot_gateway.station_video import camera_job
    with camera_job():
        result = execute(json.loads(base64.urlsafe_b64decode(sys.argv[1])))
    print('CARTRINA_RESULT='+json.dumps(result, ensure_ascii=False), flush=True)
