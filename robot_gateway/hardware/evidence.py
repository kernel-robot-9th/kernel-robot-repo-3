"""Application evidence contract; this is NOT a ROS topic or a vision detector."""
import json
from pathlib import Path


class EvidenceFiles:
    """A field observer writes a separate atomic JSON file per command + observation.

    The observer must measure/confirm the facts. An image, empty cart alone, timer
    or successful process exit is never interpreted as evidence by this reader.
    """
    def __init__(self, directory):
        self.directory = Path(directory)

    def read(self, command, kind):
        # Commands are issued by the authenticated central scheduler.
        command_id = command['id']
        if any(c not in '0123456789abcdef-' for c in command_id.lower()):
            raise ValueError('invalid command id')
        path = self.directory / f'{command_id}.{kind}.json'
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        for key in ('run_id', 'task_id', 'session_id', 'device_id'):
            if value.get(key) != command[key]:
                return None
        if value.get('source') not in {'vision', 'feedback', 'operator'}:
            return None
        return value.get('data') if isinstance(value.get('data'), dict) else None
