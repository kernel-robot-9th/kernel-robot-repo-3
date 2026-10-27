import io
import os
from pathlib import Path
import signal
import subprocess
import sys
from unittest.mock import Mock

from robot_gateway.hardware import station_remote


def test_ctrl_c_delivers_cancel_before_waiting_for_remote_cleanup(tmp_path):
    cancel = tmp_path/'cancel'
    cleaned = tmp_path/'cleaned'
    child = f'''
from pathlib import Path
import time
print('READY', flush=True)
deadline = time.monotonic()+5
while not Path({str(cancel)!r}).exists():
    if time.monotonic() > deadline: raise SystemExit(2)
    time.sleep(.01)
Path({str(cleaned)!r}).write_text('cleanup complete')
print('CARTRINA_RESULT={{"status":"cancelled"}}', flush=True)
'''
    parent = f'''
import sys
from types import SimpleNamespace
from robot_gateway.hardware import station_remote as remote
remote.station_command = lambda *a: [sys.executable, '-u', '-c', {child!r}]
remote.ssh = lambda *a: [sys.executable, '-c', {f'from pathlib import Path; Path({str(cancel)!r}).touch()'!r}]
# Disable the background watcher: Ctrl-C must deliver cancellation directly.
remote.threading.Thread = lambda **kw: SimpleNamespace(start=lambda: None)
config = {{'stations': {{'A': {{'root':'/unused','host':'unused'}}}}}}
try:
    remote.run_station('A', {{'operation':'parking'}}, config=config)
except KeyboardInterrupt:
    print('CANCELLED', flush=True)
'''
    process = subprocess.Popen([sys.executable, '-u', '-c', parent], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        assert process.stdout.readline().strip() == 'READY'
        # Match terminal Ctrl-C: signal the foreground group, not just Python.
        os.killpg(process.pid, signal.SIGINT)
        output, error = process.communicate(timeout=8)
        assert process.returncode == 0, error
        assert 'CANCELLED' in output
        assert cancel.exists() and cleaned.read_text() == 'cleanup complete'
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_completed_station_does_not_send_cancel(monkeypatch):
    process = Mock(stdout=io.StringIO('CARTRINA_RESULT={"status":"aligned"}\n'))
    process.wait.return_value = 0
    popen, run = Mock(return_value=process), Mock()
    monkeypatch.setattr(station_remote.subprocess, 'Popen', popen)
    monkeypatch.setattr(station_remote.subprocess, 'run', run)
    monkeypatch.setattr(station_remote, 'station_command', lambda *a: ['unused'])
    result = station_remote.run_station('A', {'operation':'parking'}, config={'stations':{}})
    assert result == {'status':'aligned'}
    assert popen.call_args.kwargs['start_new_session'] is True
    run.assert_not_called()
