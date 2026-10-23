#!/usr/bin/env python3
"""실기 E0509 + RH-P12-RN 으로 티칭한 물체를 집어 옮긴다.

좌표는 teach.py 로 저장한 taught_points.json 에서 읽는다.
  pick  : 핸드가이딩으로 티칭한 파지 자세 (자세는 수직 보정됨)
  place : pick 에서 x-150mm 당긴 자리 (계산값)

사용법 (ROS_DOMAIN_ID=77, bringup + gripper_service 필요):
    python3 pick_place.py --dry        # 움직이지 않고 경로만 출력
    python3 pick_place.py --to-hover   # 물체 위 hover 까지만 가고 멈춤 (정렬 눈으로 확인용)
    python3 pick_place.py --from-hover # hover 에 있다고 보고 하강~놓기까지 마저
    python3 pick_place.py              # 전체 실행
"""
import json
import os
import sys
import time

import rclpy

ROBOT_ID = "dsr01"
ROBOT_MODEL = "e0509"
POINTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taught_points.json")

APPROACH_Z = 100.0     # 파지점 위로 띄우는 높이 mm
VEL = [50.0, 30.0]     # 실기 첫 시도라 느리게. 직선 mm/s, 회전 deg/s
ACC = [100.0, 60.0]
GRIP_FORCE = 300       # 파지 전류(힘) 제한. 200~400 권장
MOVE_SETTLE = 0.5      # 이동 뒤 정착 대기 s
# 그리퍼 서비스는 레지스터에 값을 쓰고 seq 를 올린 직후 success 를 돌려준다.
# 실제로 손가락을 움직이는 건 그 뒤 DRL 루프라, 응답은 파지 완료와 무관하다.
# 이걸 완료로 믿고 바로 movel 을 보내면 닫히는 중에 팔이 올라가 물체를 끌고,
# 그 반력으로 축2 충돌 감지 -> SAFE_STOP 이 걸린다. 넉넉히 기다린다.
GRIP_SETTLE = 3.0      # 그리퍼 동작 완료 대기 s


def above(p, dz=APPROACH_Z):
    return [p[0], p[1], p[2] + dz, p[3], p[4], p[5]]


def fmt(p):
    return (f"x{p[0]:7.1f} y{p[1]:7.1f} z{p[2]:7.1f}  "
            f"rx{p[3]:6.1f} ry{p[4]:7.1f} rz{p[5]:6.1f}")


def main():
    dry = "--dry" in sys.argv

    pts = json.load(open(POINTS))
    for k in ("pick", "place"):
        if k not in pts:
            print(f"taught_points.json 에 '{k}' 가 없습니다."); return 1
    pick = pts["pick"]["tcp"]
    place = pts["place"]["tcp"]

    # 앞 구간: 지금 있는 자리에서 수직으로 빠져나와 물체 위까지. 여기서 멈춰 정렬을 눈으로 본다.
    # 수직 상승을 먼저 하지 않으면 낮은 높이에서 비스듬히 이동해 물체/작업대를 칠 수 있다.
    to_hover = [
        ("현재 자리에서 수직 상승", "LIFT"),
        ("그리퍼 열기",            None),
        ("집을 자리 위로",         above(pick)),
    ]
    from_hover = [
        ("파지 높이까지 하강", pick),
        ("잡기",               None),
        ("들어올리기",         above(pick)),
        ("놓을 자리 위로",     above(place)),
        ("놓을 높이까지 하강", place),
        ("놓기",               None),
        ("빠지기",             above(place)),
    ]
    if "--to-hover" in sys.argv:
        plan = to_hover
    elif "--from-hover" in sys.argv:
        plan = from_hover
    else:
        plan = to_hover + from_hover

    print(f"pick  {fmt(pick)}")
    print(f"place {fmt(place)}")
    print(f"접근 높이 +{APPROACH_Z:.0f}mm, 속도 {VEL[0]:.0f}mm/s, 파지력 {GRIP_FORCE}\n")
    for i, (label, target) in enumerate(plan, 1):
        if target == "LIFT":
            print(f"  {i}) {label}  ->  현재 z 에서 +{APPROACH_Z:.0f}mm (실행 시점에 읽음)")
        else:
            print(f"  {i}) {label}" + (f"  ->  {fmt(target)}" if target else ""))
    if dry:
        print("\n--dry 이므로 여기서 끝. 실제 실행은 --dry 빼고.")
        return 0

    import DR_init
    DR_init.__dsr__id = ROBOT_ID
    DR_init.__dsr__model = ROBOT_MODEL
    rclpy.init()
    node = rclpy.create_node("pick_place", namespace=ROBOT_ID)
    DR_init.__dsr__node = node

    from DSR_ROBOT2 import movel, set_velx, set_accx, posx, get_current_posx, DR_BASE
    from dsr_msgs2.srv import GetRobotMode, GetRobotState
    from dsr_gripper import gripper_open, gripper_cmd

    # 움직이기 전에 자동 모드인지 확인한다. MANUAL 이면 모션 명령이 먹지 않는다.
    cli = node.create_client(GetRobotMode, f"/{ROBOT_ID}/dsr_controller2/system/get_robot_mode")
    if not cli.wait_for_service(timeout_sec=5.0):
        print("로봇 모드 서비스 없음 -> bringup 확인"); return 1
    fut = cli.call_async(GetRobotMode.Request())
    rclpy.spin_until_future_complete(node, fut, timeout_sec=10.0)
    mode = fut.result().robot_mode
    if mode != 1:
        print(f"로봇이 AUTONOMOUS 가 아닙니다 (mode={mode}). 'python3 teach.py auto' 먼저 실행."); return 1

    scli = node.create_client(GetRobotState, f"/{ROBOT_ID}/dsr_controller2/system/get_robot_state")
    if scli.wait_for_service(timeout_sec=5.0):
        sfut = scli.call_async(GetRobotState.Request())
        rclpy.spin_until_future_complete(node, sfut, timeout_sec=10.0)
        st = sfut.result().robot_state
        if st != 1:   # 1 = STATE_STANDBY
            names = {2: "MOVING", 3: "SAFE_OFF", 5: "SAFE_STOP", 6: "EMERGENCY_STOP"}
            print(f"로봇이 STANDBY 가 아닙니다 (state={st} {names.get(st, '')}). "
                  f"안전정지면 'python3 recover.py' 로 해제하세요.")
            return 1

    set_velx(*VEL)
    set_accx(*ACC)

    print("\n=== 실행 ===")
    for i, (label, target) in enumerate(plan, 1):
        print(f"  {i}) {label}", flush=True)
        if target == "LIFT":
            cur = list(get_current_posx(DR_BASE)[0][:6])
            up = [cur[0], cur[1], cur[2] + APPROACH_Z, cur[3], cur[4], cur[5]]
            print(f"     현재 {fmt(cur)}")
            print(f"     ->   {fmt(up)}")
            movel(posx(up), vel=VEL, acc=ACC, ref=DR_BASE)
            time.sleep(MOVE_SETTLE)
        elif target is None:
            if label == "잡기":
                ok = gripper_cmd(0, GRIP_FORCE)
            else:
                ok = gripper_open()
            print(f"     명령 접수 {'OK' if ok else '실패'} -> 동작 완료까지 {GRIP_SETTLE:.1f}s 대기")
            time.sleep(GRIP_SETTLE)
        else:
            movel(posx(target), vel=VEL, acc=ACC, ref=DR_BASE)
            time.sleep(MOVE_SETTLE)

    print("\n완료.")
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
