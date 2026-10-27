"""Thread-safe display status and command-scoped operator observations. No I/O on import."""
from copy import deepcopy
import threading
import time

from .evidence import EvidenceFiles


class FieldStatus:
    def __init__(self):
        self.lock = threading.Lock()
        self.robots = {}
        self.observations = {}

    def update(self, command, **values):
        robot = command['robot_id']
        with self.lock:
            old = self.robots.get(robot, {})
            if old.get('command_id') != command['id']:
                old = {}
            old.update(robot_id=robot, command_id=command['id'], task_id=command['task_id'],
                       device_id=command['device_id'], kind=command['kind'], zone_id=command['zone_id'],
                       updated_at=time.time(), **values)
            self.robots[robot] = old

    def snapshot(self):
        with self.lock:
            return deepcopy(self.robots)

    def receive(self, observations):
        with self.lock:
            self.observations = observations

    def observation(self, command, kind):
        with self.lock:
            value = self.observations.get(command['id'], {}).get(kind)
            return deepcopy(value['data']) if value else None


class FieldEvidence(EvidenceFiles):
    """Existing local observer files plus explicit operator facts from the admin UI."""
    def __init__(self, directory, status):
        super().__init__(directory)
        self.status = status

    def read(self, command, kind):
        return self.status.observation(command, kind) or super().read(command, kind)
