"""Overhead position display server. Does not import ROS or command a robot."""
import argparse
import fcntl
import json
import math
from pathlib import Path
import socketserver
import threading
import time

import cv2
import numpy as np

from robot_gateway.hardware.aruco_parking import detect_markers
from robot_gateway.hardware.camera_navigation import CONFIG, SOCKET, frame_observation, observation
from robot_gateway.hardware.overhead import project
from robot_gateway.hardware.pinky import atomic_json


def run(args):
    config = json.loads(Path(args.config).read_text())
    calibration = json.loads(Path(config['calibration_file']).read_text())
    transform = json.loads(Path(config['layout_registry']).read_text())['layout_to_map']
    root = Path(config['output_directory']); root.mkdir(parents=True, exist_ok=True)
    socket_path = Path(config.get('socket', SOCKET))
    lock = socket_path.with_suffix('.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    socket_path.unlink(missing_ok=True)
    current = [{'running': True, 'robots': {}}]

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write((json.dumps(current[0])+'\n').encode())

    server = socketserver.ThreadingUnixStreamServer(str(socket_path), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    cap = None
    cam = config['camera']
    last_saved = 0.
    try:
        if not args.image:
            cap = cv2.VideoCapture(cam['camera_by_id'], cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, cam['width']); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cam['height'])
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        print('전체 카메라 위치 표시 시작. 이 창은 로봇을 움직이지 않습니다. Q: 종료', flush=True)
        count = 0
        while True:
            ok, frame = (True, cv2.imread(args.image)) if args.image else cap.read()
            if not ok or frame is None:
                raise RuntimeError('전체 카메라 영상 읽기 실패')
            if [frame.shape[1], frame.shape[0]] != calibration['image_size']:
                raise ValueError('캘리와 영상 해상도가 다릅니다')
            markers = detect_markers(frame, 'DICT_5X5_1000', None)
            current[0] = frame_observation(markers, calibration, config['robots'], transform, time.time())
            for name, value in current[0]['robots'].items():
                if 'map_pose' not in value:
                    continue
                p = value['map_pose']
                a, b = project([[p['x'], p['y']], [p['x']+.1*math.cos(p['yaw']), p['y']+.1*math.sin(p['yaw'])]],
                               np.linalg.inv(calibration['image_to_map'])).astype(int)
                color = (255, 210, 0) if name == 'pinky-1' else (60, 60, 255)
                cv2.arrowedLine(frame, tuple(a), tuple(b), color, 3, tipLength=.3)
                cv2.putText(frame, name, tuple(a+[0, -25]), cv2.FONT_HERSHEY_SIMPLEX, .7, color, 2)
            if time.time()-last_saved > .2:
                atomic_json(root/'navigation-latest.json', current[0])
                cv2.imwrite(str(root/'navigation-latest.jpg'), frame)
                last_saved = time.time()
            if not args.headless:
                cv2.imshow('Pinky camera navigation (NO MOTION)', cv2.resize(frame, (1280, 720)))
                if cv2.waitKey(1) & 255 in (ord('q'), 27):
                    break
            count += 1
            if args.frames and count >= args.frames:
                break
    finally:
        current[0] = {'running': False, 'robots': {}}
        atomic_json(root/'navigation-latest.json', current[0])
        if cap:
            cap.release()
        if not args.headless:
            cv2.destroyAllWindows()
        server.shutdown(); server.server_close(); thread.join()
        socket_path.unlink(missing_ok=True); lock.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['run', 'status'], default='run', nargs='?')
    p.add_argument('--config', default=str(CONFIG))
    p.add_argument('--headless', action='store_true')
    p.add_argument('--image', help='사진으로만 확인; 카메라·로봇 연결 없음')
    p.add_argument('--frames', type=int, default=0)
    args = p.parse_args()
    if args.operation == 'status':
        print(json.dumps(observation(), ensure_ascii=False, indent=2))
    else:
        run(args)


if __name__ == '__main__':
    main()
