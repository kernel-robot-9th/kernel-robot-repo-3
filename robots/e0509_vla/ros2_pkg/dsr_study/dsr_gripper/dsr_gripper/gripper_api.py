#!/usr/bin/env python3
# =====================================================================
#  그리퍼 Python API  (노트북/스크립트에서 import 해서 사용)
#
#  DSR_ROBOT2 와 동일한 패턴:
#    1) rclpy 노드를 만들어 DR_init.__dsr__node 에 등록 (연결 셀)
#    2) from dsr_gripper import gripper_open, gripper_close, gripper_cmd
#
#  내부적으로 /<namespace>/gripper/cmd 서비스(GripperCmd)를 호출합니다.
#  → gripper_service 노드가 실행 중이어야 합니다.
#     (ros2 run dsr_gripper gripper_service)
# =====================================================================

import time
import math

import rclpy
from dsr_gripper_interfaces.srv import GripperCmd
from sensor_msgs.msg import JointState

_grip_cli = None
_state_sub = None
_state = None          # 마지막 /<ns>/gripper/state (position, moving, current, 수신시각)


def _node():
    # DR_init 은 호출 시점에만 필요 (서비스 노드 실행에는 불필요하므로 지연 import)
    import DR_init
    node = getattr(DR_init, "__dsr__node", None)
    if node is None:
        raise RuntimeError(
            "노드가 없습니다. 먼저 rclpy 노드를 만들어 DR_init.__dsr__node 에 등록하세요 "
            "(DSR_ROBOT2 연결 셀 실행)."
        )
    return node


def _namespace():
    import DR_init
    return getattr(DR_init, "__dsr__id", "dsr01")


def _client():
    global _grip_cli
    if _grip_cli is None:
        _grip_cli = _node().create_client(GripperCmd, f"/{_namespace()}/gripper/cmd")
    return _grip_cli


def gripper_cmd(position, current=200, timeout=15.0):
    """그리퍼 이동. position: 0=완전닫힘 ~ 750=완전열림, current: 힘(전류) 제한."""
    node = _node()
    cli = _client()
    if not cli.wait_for_service(timeout_sec=3.0):
        raise RuntimeError("gripper 서비스 없음 → 'ros2 run dsr_gripper gripper_service' 확인")
    req = GripperCmd.Request()
    req.position = int(max(0, min(750, position)))
    req.current = int(current)
    fut = cli.call_async(req)
    rclpy.spin_until_future_complete(node, fut, timeout_sec=timeout)
    res = fut.result()
    if res is None:
        raise RuntimeError("gripper 응답 timeout")
    return res.success


def _on_state(m):
    global _state
    if not (len(m.position) and len(m.velocity) and len(m.effort)):
        return
    if not all(math.isfinite(x) for x in (m.position[0], m.velocity[0], m.effort[0])):
        return
    _state = {"position": m.position[0], "moving": m.velocity[0] > 0.5,
              "current": m.effort[0], "t": time.time()}


def _ensure_state_sub():
    global _state_sub
    if _state_sub is None:
        _state_sub = _node().create_subscription(
            JointState, f"/{_namespace()}/gripper/state", _on_state, 10)


def gripper_state(timeout=1.0):
    """최신 그리퍼 상태 dict(position 750=열림 0=닫힘, moving, current). 없으면 None."""
    _ensure_state_sub()
    t0 = time.time()
    while time.time() - t0 < timeout:
        rclpy.spin_once(_node(), timeout_sec=0.05)
        if _state is not None and time.time() - _state["t"] < 1.0:
            return dict(_state)
    return None


def gripper_wait(timeout=8.0, min_wait=1.5):
    """명령을 보낸 직후 호출. 그리퍼가 실제로 멈출 때까지 기다린다.

    - 호출 이후에 '새로 받은' 상태만 센다 (같은 메시지를 여러 번 세면 명령 전 상태로 끝나버린다)
    - 움직임(moving=True)을 한 번이라도 봤거나 min_wait 초가 지난 뒤에만 정지를 인정한다
      (명령이 그리퍼에 닿기까지 지연이 있어 처음 몇 샘플은 여전히 '정지'로 온다)
    - 정지 샘플 2개 연속이면 완료. 반환: 완료 상태 dict. 시간 초과/완료 미확인은 None.
    """
    _ensure_state_sub()
    t0 = time.time()
    last_t = _state["t"] if _state else 0.0
    seen_moving = False
    still = 0
    st = None
    while time.time() - t0 < timeout:
        rclpy.spin_once(_node(), timeout_sec=0.05)
        cur = _state
        if cur is None or cur["t"] <= last_t:
            continue                     # 새 메시지 아님
        last_t = cur["t"]
        st = dict(cur)
        if st["moving"]:
            seen_moving, still = True, 0
            continue
        if not seen_moving and time.time() - t0 < min_wait:
            continue
        still += 1
        if still >= 2:
            return st
    return None  # Timeout is never completion, even when a last sample exists.


def gripper_open(current=200, wait=True):
    """그리퍼 열기 (stroke 750). wait=True 면 멈출 때까지 기다린다."""
    ok = gripper_cmd(750, current)
    return gripper_wait() if (ok and wait) else ok


def gripper_close(current=300, wait=True):
    """그리퍼 닫기 / 물체 잡기 (stroke 0). wait=True 면 멈출 때까지 기다린다."""
    ok = gripper_cmd(0, current)
    return gripper_wait() if (ok and wait) else ok
