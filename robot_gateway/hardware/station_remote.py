"""Run camera/arm code where the USB devices are, from the central laptop."""
import base64
import json
from pathlib import Path
import shlex
import subprocess
import threading
import uuid


def configuration():
    return json.loads(Path('runtime/field/pinky-control.json').read_text())


def ssh(config, host, command, interactive=False):
    return ['ssh', '-tt' if interactive else '-T', '-i', str(Path(config['ssh_key']).expanduser()),
            '-o', 'BatchMode=yes', host, command]


def station_command(config, zone, request):
    station = config['stations'][zone]
    payload = base64.urlsafe_b64encode(json.dumps(request).encode()).decode()
    python = station.get('parking_python', station['python']) if request['operation'] != 'arm' else station['python']
    command = ('cd '+shlex.quote(station['root'])+' && bash scripts/run_pinky_station.sh '+
               shlex.quote(python)+' '+shlex.quote(payload))
    return ssh(config, station['host'], command, request.get('interactive', False))


def run_station(zone, request, config=None, cancelled=None, frames=None):
    config = config or configuration()
    request = dict(request, job_id=str(uuid.uuid4()), stream_frames=frames is not None)
    if request.get('interactive'):
        subprocess.run(station_command(config, zone, request), check=True)
        return {'status': 'operator_session_closed'}
    process = subprocess.Popen(station_command(config, zone, request), stdout=subprocess.PIPE,
                               text=True, bufsize=1, start_new_session=True)
    cancelled = cancelled or threading.Event()
    done = threading.Event()
    def cancel_remote():
        station = config['stations'][zone]
        path = station['root']+'/runtime/field/station-jobs/'+request['job_id']+'.cancel'
        subprocess.run(ssh(config, station['host'], 'mkdir -p '+shlex.quote(str(Path(path).parent))+
                           ' && touch '+shlex.quote(path)), check=True, start_new_session=True)
    def cancellation():
        while not done.wait(.2):
            if cancelled.is_set():
                cancel_remote()
                return
    threading.Thread(target=cancellation, daemon=True).start()
    result = None
    try:
        for line in process.stdout:
            if line.startswith('CARTRINA_FRAME='):
                if frames is not None:
                    import cv2
                    import numpy as np
                    channel, encoded = json.loads(line.partition('=')[2])
                    frame = cv2.imdecode(np.frombuffer(base64.b64decode(encoded), dtype=np.uint8), cv2.IMREAD_COLOR)
                    frames.offer(channel, frame)
            elif line.startswith('CARTRINA_RESULT='):
                result = json.loads(line.partition('=')[2])
            else:
                print(line, end='', flush=True)
        code = process.wait()
    except BaseException:
        done.set()
        cancelled.set()
        cancel_remote()
        # Drain output while the station runs its parking/nav2 cleanup and exits.
        process.communicate()
        raise
    finally:
        done.set(); process.stdout.close()
    if code:
        raise RuntimeError(zone+' 현장 실행 실패: 위 원인 로그 확인')
    return result or {}


class RemoteArm:
    def __init__(self, zone, frames=None):
        self.zone, self.executed = zone, []
        self.frames = frames

    def execute(self, command, cancelled):
        return run_station(self.zone, {'operation': 'arm', 'zone': self.zone, 'command': command},
                           cancelled=cancelled, frames=self.frames)

    stop = execute
    stopped = execute
