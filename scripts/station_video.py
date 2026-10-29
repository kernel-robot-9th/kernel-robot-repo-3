"""Camera-only station preview. Never opens a motor or executes a robot job."""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

import cv2
from robot_gateway.station_video import ROOT, job_requested


def emit(channel, frame):
    h, w = frame.shape[:2]
    frame = cv2.resize(frame, (960, round(h*960/w)))
    ok, data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if ok:
        print('CARTRINA_FRAME='+json.dumps([channel, base64.b64encode(data).decode()]), flush=True)


def run(zone):
    ROOT.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    singleton = (ROOT/'preview.lock').open('a')
    fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (ROOT/'preview.pid').write_text(str(os.getpid()))
    (ROOT/'enabled').touch()
    config = json.loads(Path(f'runtime/field/gateway-{zone.lower()}.hardware.json').read_text())
    detector = None
    if zone in ('A', 'B'):
        from robot_gateway.hardware.yolo import ROOT as YOLO_ROOT
        sys.path.insert(0, str(YOLO_ROOT/'tools/picking'))
        from pick_core import load_config
        from pick_vision import Detector
        cfg = config['yolo']
        detector = Detector(load_config(Path(cfg['pick_config'])), str(YOLO_ROOT/'weights/best.pt'))
        sources = {'load-'+zone.lower(): (cfg['camera_by_id'], cfg['width'], cfg['height'], cfg['fps'])}
    else:
        sources = {'handoff-'+name: (config['act'][name+'_by_id'], 640, 480, 30) for name in ('front', 'wrist')}
    cameras, modified, failed = {}, {}, set()
    lock = (ROOT/'camera.lock').open('a')
    owns = False
    try:
        while not stop.is_set():
            if job_requested():
                for cap in cameras.values(): cap.release()
                cameras.clear()
                if owns:
                    fcntl.flock(lock, fcntl.LOCK_UN); owns = False
                for channel in sources:
                    path = ROOT/f'{channel}.jpg'
                    if path.exists() and time.time()-path.stat().st_mtime < 2 and modified.get(channel) != path.stat().st_mtime_ns:
                        modified[channel] = path.stat().st_mtime_ns
                        frame = cv2.imread(str(path))
                        if frame is not None: emit(channel, frame)
                stop.wait(.15)
                continue
            if not owns:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); owns = True
                except BlockingIOError:
                    stop.wait(.15); continue
                for channel, (path, width, height, fps) in sources.items():
                    cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                    cap.set(cv2.CAP_PROP_FPS, fps); cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    cameras[channel] = cap
            for channel, cap in cameras.items():
                for _ in range(3): cap.grab()
                ok, frame = cap.read()
                if not ok:
                    if channel not in failed: print(channel+' camera read failed', file=sys.stderr, flush=True)
                    failed.add(channel); continue
                failed.discard(channel)
                if detector:
                    detections = detector.predict(frame)
                    for det in detections:
                        x1,y1,x2,y2 = map(round,det.box)
                        cv2.rectangle(frame,(x1,y1),(x2,y2),(0,255,255),3)
                        cv2.putText(frame,f'{det.label} {det.confidence:.2f}',(x1,max(25,y1-8)),
                                    cv2.FONT_HERSHEY_SIMPLEX,.9,(0,255,255),2)
                    (ROOT/'detections.json').write_text(json.dumps({'at':time.time(), 'items':[
                        {'label':d.label,'confidence':d.confidence,'box':d.box} for d in detections]}))
                emit(channel, frame)
            stop.wait(.1)
    finally:
        for cap in cameras.values(): cap.release()
        lock.close(); singleton.close()
        (ROOT/'enabled').unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zone', choices=['A','B','C'], required=True)
    run(parser.parse_args().zone)
