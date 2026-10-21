"""Central USB overview camera; never shared with ACT input."""
import argparse
import json
import os
from pathlib import Path
import uuid

from .frames import JpegSender, LatestFramePublisher, RtspSender


def main():
    parser = argparse.ArgumentParser(description='관제 PC 전경 카메라 송신')
    parser.add_argument('--device', required=True)
    parser.add_argument('--media-config', type=Path, help='prepare_media.py가 만든 central.json')
    parser.add_argument('--server', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    if not args.device.startswith('/dev/v4l/by-id/') or not Path(args.device).exists():
        parser.error('현장 카메라의 /dev/v4l/by-id 경로 필요')
    import cv2
    if args.media_config:
        config = json.loads(args.media_config.read_text())
        sender = RtspSender(config['rtsp_urls'], config['fps'])
        fps = config['fps']
    else:
        token = os.getenv('SHOP_OVERVIEW_TOKEN', '')
        if len(token) < 16:
            parser.error('SHOP_OVERVIEW_TOKEN 필요')
        sender = JpegSender(args.server, token, str(uuid.uuid4()), overview=True)
        fps = 5
    frames = LatestFramePublisher(sender, fps)
    camera = cv2.VideoCapture(args.device, cv2.CAP_V4L2)
    try:
        if not camera.isOpened():
            raise RuntimeError('전경 카메라 열기 실패')
        camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        while True:
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError('전경 카메라 수신 끊김')
            frames.offer('overview', frame)
    finally:
        camera.release()
        if hasattr(sender, 'close'):
            sender.close()
        frames.close()


if __name__ == '__main__':
    main()
