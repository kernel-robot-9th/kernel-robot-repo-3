# 그리퍼 열고 수집 시작점(x430 y13 z427)으로: 먼저 수직 상승, 그다음 수평 이동
import time, rclpy, DR_init
DR_init.__dsr__id, DR_init.__dsr__model = "dsr01", "e0509"
rclpy.init(); node = rclpy.create_node("go_home", namespace="dsr01"); DR_init.__dsr__node = node
from DSR_ROBOT2 import movel, posx, get_current_posx, DR_BASE
from dsr_gripper import gripper_cmd, gripper_wait
p = get_current_posx(DR_BASE)[0]; print("현재", [round(v, 1) for v in p])
gripper_cmd(750, 200); gripper_wait(timeout=12.0); time.sleep(1.0); print("그리퍼 열림")
if p[2] < 427.0:
    movel(posx([p[0], p[1], 427.0, p[3], p[4], p[5]]), vel=40, acc=80); print("수직 상승 z427")
movel(posx([430.0, 13.0, 427.0, p[3], p[4], p[5]]), vel=50, acc=100)
print("기본 자세", [round(v, 1) for v in get_current_posx(DR_BASE)[0]])
rclpy.shutdown()
