"""Count visible ArUco markers at full camera resolution; no robot connection."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time

import cv2
import numpy as np

from robot_gateway.hardware.aruco_parking import detect_markers


def annotate(frame, dictionary, fps=0.):
    found = detect_markers(frame, dictionary)
    height, width = frame.shape[:2]
    scale = min(1280/width, 720/height, 1.)
    view = cv2.resize(frame, None, fx=scale, fy=scale)
    records = []
    for number, marker in enumerate(found, 1):
        corners = np.float32(marker['corners'])
        shortest = float(np.linalg.norm(corners-np.roll(corners, -1, axis=0), axis=1).min())
        points = np.int32(corners*scale)
        cv2.polylines(view, [points], True, (0, 255, 0), 2)
        label = f'#{number} ID:{marker["marker_id"]} min:{shortest:.1f}px'
        text_width = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, .55, 1)[0][0]
        origin = (max(0, min(int(points[:, 0].min()), view.shape[1]-text_width)),
                  max(20, int(points[:, 1].min())-8))
        cv2.putText(view, label, origin, cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(view, label, origin, cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 255, 0), 1, cv2.LINE_AA)
        records.append(dict(marker, number=number, shortest_edge_px=shortest))
    canvas = np.zeros((view.shape[0]+90, view.shape[1], 3), np.uint8)
    canvas[90:] = view
    color = (0, 255, 0) if found else (0, 170, 255)
    cv2.putText(canvas, f'DETECTED: {len(found)}', (15, 40), cv2.FONT_HERSHEY_SIMPLEX,
                1.2, color, 2, cv2.LINE_AA)
    cv2.putText(canvas, f'{width}x{height} | {fps:.1f} FPS | {dictionary} | S: save | Q/Esc: quit',
                (15, 73), cv2.FONT_HERSHEY_SIMPLEX, .55, (240, 240, 240), 1, cv2.LINE_AA)
    return canvas, records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera', default='/dev/v4l/by-id/usb-HFSD-231214-J_SNAP_U2-video-index0')
    parser.add_argument('--dictionary', default='DICT_5X5_1000')
    args = parser.parse_args()
    cap = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
    window = 'Pinky marker count'
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
        print('원본 해상도로 검출합니다. 같은 ID도 각각 셉니다. 화면 표시만 축소합니다.', flush=True)
        print('DETECTED: 현재 검출 개수 / min: 원본 영상의 가장 짧은 변(px)', flush=True)
        print('S: 현재 원본·표시 영상·검출값 저장 / Q 또는 Esc: 종료', flush=True)
        began, frames, fps = time.monotonic(), 0, 0.
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                raise RuntimeError('카메라 영상 수신 실패. USB 연결과 다른 카메라 프로그램을 확인하세요.')
            canvas, markers = annotate(frame, args.dictionary, fps)
            frames += 1
            now = time.monotonic()
            if now-began >= 1:
                fps, frames, began = frames/(now-began), 0, now
            cv2.imshow(window, canvas)
            key = cv2.waitKey(1) & 0xff
            if key in (27, ord('q'), ord('Q')) or cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key in (ord('s'), ord('S')):
                root = Path('runtime/field/pinky-marker-view')/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                root.mkdir(parents=True)
                if not cv2.imwrite(str(root/'raw.png'), frame) or not cv2.imwrite(str(root/'view.jpg'), canvas):
                    raise RuntimeError('카메라 이미지 저장 실패')
                (root/'markers.json').write_text(json.dumps({'camera':args.camera,
                    'image_size':[frame.shape[1], frame.shape[0]], 'dictionary':args.dictionary,
                    'detected_count':len(markers), 'processing_fps':fps, 'markers':markers}, indent=2))
                print(f'저장: {root} / 검출 {len(markers)}개', flush=True)
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
