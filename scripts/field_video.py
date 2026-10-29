"""Relay station previews and the existing overhead frame into the admin video wall."""
import argparse
import base64
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

from robot_gateway.hardware.station_remote import configuration, ssh

ROOT = Path('runtime/field/video-preview')


def relay():
    config = configuration()
    token = json.loads(Path('runtime/field/credentials.json').read_text())['admin']
    instance = 'preview-'+str(uuid.uuid4())
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    def publish(channel, data):
        url = f'http://127.0.0.1:8000/api/admin/video/{channel}/frame?instance_id={instance}&sequence={time.time_ns()}'
        request = urllib.request.Request(url, data=data,
            headers={'Authorization':'Bearer '+token, 'Content-Type':'image/jpeg'})
        with urllib.request.urlopen(request, timeout=2) as response: response.read()

    def station(zone):
        station = config['stations'][zone]
        python = station.get('parking_python', station['python']) if zone == 'C' else station['python']
        command = 'cd '+shlex.quote(station['root'])+' && exec '+shlex.quote(python)+' -u -m scripts.station_video --zone '+zone
        with subprocess.Popen(ssh(config, station['host'], command), stdout=subprocess.PIPE, text=True) as child:
            try:
                for line in child.stdout:
                    if stop.is_set(): break
                    if line.startswith('CARTRINA_FRAME='):
                        channel, data = json.loads(line.partition('=')[2])
                        publish(channel, base64.b64decode(data))
                    else:
                        print(zone+': '+line.rstrip(), flush=True)
            except Exception as exc:
                print(zone+' video relay: '+type(exc).__name__, flush=True)
            finally:
                child.terminate()

    def overhead():
        path = Path('runtime/field/pinky-overhead/navigation-latest.jpg')
        previous = None
        while not stop.wait(.2):
            if path.exists() and time.time()-path.stat().st_mtime < 2 and path.stat().st_mtime_ns != previous:
                previous = path.stat().st_mtime_ns
                data = path.read_bytes()
                if data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'):
                    try: publish('overview', data)
                    except Exception as exc:
                        print('overview video relay: '+type(exc).__name__, flush=True)
                        return
    # C remains opt-in while the team records imitation-learning demonstrations.
    zones = 'ABC' if (ROOT/'enable-c').exists() else 'AB'
    threads = [threading.Thread(target=station,args=(zone,),daemon=True) for zone in zones]
    threads.append(threading.Thread(target=overhead,daemon=True))
    for thread in threads: thread.start()
    print(zones+' + overview video relay started (no robot motion)', flush=True)
    stop.wait()
    for zone in zones:
        station = config['stations'][zone]
        command = 'cd '+shlex.quote(station['root'])+" && python3 - <<'PY'\nimport os,signal\nfrom pathlib import Path\np=Path('runtime/field/station-video/preview.pid')\nif p.exists():\n pid=int(p.read_text())\n try:\n  if b'scripts.station_video' in Path(f'/proc/{pid}/cmdline').read_bytes(): os.kill(pid,signal.SIGTERM)\n except FileNotFoundError: pass\nPY"
        subprocess.run(ssh(config,station['host'],command),stdout=subprocess.DEVNULL,timeout=8)
    for thread in threads: thread.join(timeout=3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['start','stop','status','run'])
    args = parser.parse_args()
    ROOT.mkdir(parents=True,exist_ok=True)
    pidfile = ROOT/'relay.pid'
    pid = int(pidfile.read_text()) if pidfile.exists() else 0
    try: running = pid > 0 and b'scripts.field_video' in Path(f'/proc/{pid}/cmdline').read_bytes()
    except FileNotFoundError: running = False
    if args.operation == 'run': relay()
    elif args.operation == 'start':
        if not running:
            with (ROOT/'relay.log').open('ab') as log:
                child = subprocess.Popen([sys.executable,'-u','-m','scripts.field_video','run'],
                    stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
            pidfile.write_text(str(child.pid))
        print('미리보기 백그라운드 실행. 로그: '+str(ROOT/'relay.log'))
    elif args.operation == 'stop':
        if running: os.kill(pid,signal.SIGTERM)
        print('미리보기 종료 요청')
    else:
        print(json.dumps({'running':running,'pid':pid if running else None}))


if __name__ == '__main__': main()
