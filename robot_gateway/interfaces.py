"""Internal application contracts; none of these names claim to be ROS interfaces."""
from typing import Protocol


class MobileAdapter(Protocol):
    def navigate(self, command: dict) -> None: ...
    def leave(self, command: dict) -> None: ...
    def stop(self, command: dict) -> None: ...


class ArmAdapter(Protocol):
    def execute_items(self, command: dict) -> list[dict]: ...
    def clear_path(self, command: dict) -> None: ...
    def stop(self, command: dict) -> None: ...


class UnverifiedROSAdapter:
    def __init__(self):
        raise NotImplementedError(
            "실제 Pinky Pro / OMX-AI의 설치 버전·명령·결과·중단 인터페이스 확인 전입니다. "
            "Confluence/Jira에 확인한 인터페이스를 기록한 뒤 실제 어댑터를 구현하세요."
        )
