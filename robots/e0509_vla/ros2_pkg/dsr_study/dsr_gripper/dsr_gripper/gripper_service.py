#!/usr/bin/env python3
# =====================================================================
#  RH-P12-RN(A) 그리퍼 ROS2 서비스 노드  (상주 루프 · 고속)
#
#  서비스: /dsr01/gripper/cmd  (dsr_gripper_interfaces/GripperCmd)
#     요청: position(0~750), current(힘, 0이면 노드 기본값)
#     응답: success  ← 레지스터에 썼다는 뜻일 뿐, 동작 완료가 아니다
#  토픽:   /dsr01/gripper/state   (sensor_msgs/JointState)
#     position[0] = 현재 위치(명령과 같은 규약, 750=열림 0=닫힘)
#     effort[0]   = 현재 전류(부호 있음)
#     velocity[0] = 1.0 이면 움직이는 중, 0.0 이면 정지
#  상태는 DRL 루프가 그리퍼 Present 레지스터를 Modbus FC03 으로 읽어
#  출력 레지스터 15~20 에 써두고, 이 노드가 주기적으로 읽어 발행한다.
#
#  구조:
#    - 최초 1회 DrlStart 로 '무한 루프 DRL' 을 띄움 → 시리얼 계속 열어둠 + init 1회
#    - 이후 매 명령: ROS2가 명령 레지스터에만 write (빠름)
#    - 루프는 seq 레지스터가 바뀌면 position/current 를 읽어 move
#
#  레지스터 코덱(실기 확인): 한 번 건널 때 f(x)=(x & 0xFF)<<24  → 한 칸당 8비트.
#    안전하게 7비트씩 분할(값 0~127, 부호문제 없음)해서 두 칸으로 전송.
#    받는 쪽 복원: byte = (v >> 24) & 0xFF
# =====================================================================

import time
import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor

from dsr_msgs2.srv import (DrlStart, DrlStop, GetDrlState, GetOutputRegisterInt, GetRobotMode,
                            SetOutputRegisterInt, SetRobotMode)
from dsr_gripper_interfaces.srv import GripperCmd
from sensor_msgs.msg import JointState
from std_srvs.srv import SetBool

DRL_START_SRV = "/dsr01/dsr_controller2/drl/drl_start"
DRL_STOP_SRV = "/dsr01/dsr_controller2/drl/drl_stop"
DRL_STATE_SRV = "/dsr01/dsr_controller2/drl/get_drl_state"
GET_MODE_SRV = "/dsr01/dsr_controller2/system/get_robot_mode"
SET_MODE_SRV = "/dsr01/dsr_controller2/system/set_robot_mode"
SET_REG_SRV = "/dsr01/dsr_controller2/plc/set_output_register_int"
GET_REG_SRV = "/dsr01/dsr_controller2/plc/get_output_register_int"
GRIPPER_SRV = "/dsr01/gripper/cmd"
STATE_TOPIC = "/dsr01/gripper/state"

# 명령 레지스터 주소
REG_SEQ = 10
REG_POS_HI = 11
REG_POS_LO = 12
REG_CUR_HI = 13
REG_CUR_LO = 14

# 상태 레지스터 주소 (DRL -> ROS)
REG_ST_TICK = 15     # 루프가 상태를 갱신할 때마다 1씩 증가 (살아있는지 확인용)
REG_ST_PH = 16
REG_ST_PL = 17
REG_ST_CH = 18       # 전류는 +8192 오프셋을 더해 14비트로 보냄
REG_ST_CL = 19
REG_ST_MOV = 20      # 1 = 움직이는 중
REG_ST_EN = 21       # ROS -> DRL: 1 이면 상태 읽기·쓰기, 0 이면 안 함 (2026-10-21 컨트롤러 과부하 대책)

# RH-P12-RN(A) Modbus Present 영역 (2026-10-12 실기 덤프로 확인):
#   285 상위바이트 Moving Status / 하위바이트 Moving(0/1)   <- 한 워드에 1바이트씩 붙어 있다
#   286 Present PWM, 287 Present Current(부호),
#   288~289 Present Velocity, 290~291 Present Position (32비트, 하위 워드 먼저)
# 하위 워드 먼저인 건 gripper_move 가 Goal Position(282) 에 [stroke, 0] 으로 쓰는 것과 같은 순서.
# 이 그리퍼는 느리다: 닫기 명령 2.5초 뒤에도 위치 523 로 아직 닫히는 중이었다.
PRESENT_BASE = 285
PRESENT_COUNT = 7

# --- 상주 루프 DRL 템플릿 -------------------------------------------
# %(...)s 로 slave_id / baudrate / 레지스터 주소 치환
DRL_LOOP_TMPL = r'''
g_slaveid = 0
set_Operating_Mode = 5
set_Torque_Enable  = 256
set_Goal_Current   = 275
set_Goal_Position  = 282

def modbus_set_slaveid(slaveid):
    global g_slaveid
    g_slaveid = slaveid

def modbus_crc(data):
    crc = 0xFFFF
    for b in data:
        crc = crc ^ b
        i = 0
        while i < 8:
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc = crc >> 1
            i = i + 1
    return crc

def modbus_send_make(data):
    crc = modbus_crc(data)
    data += (crc & 0xFF).to_bytes(1, byteorder='big')
    data += ((crc >> 8) & 0xFF).to_bytes(1, byteorder='big')
    return data

def modbus_fc06(address, value):
    global g_slaveid
    data = (g_slaveid).to_bytes(1, byteorder='big')
    data += (6).to_bytes(1, byteorder='big')
    data += (address).to_bytes(2, byteorder='big')
    data += (value).to_bytes(2, byteorder='big')
    return modbus_send_make(data)

def modbus_fc16(startaddress, cnt, valuelist):
    global g_slaveid
    data = (g_slaveid).to_bytes(1, byteorder='big')
    data += (16).to_bytes(1, byteorder='big')
    data += (startaddress).to_bytes(2, byteorder='big')
    data += (cnt).to_bytes(2, byteorder='big')
    data += (2*cnt).to_bytes(1, byteorder='big')
    for i in range(0, cnt):
        data += (valuelist[i]).to_bytes(2, byteorder='big')
    return modbus_send_make(data)

def modbus_fc03(startaddress, cnt):
    global g_slaveid
    data = (g_slaveid).to_bytes(1, byteorder='big')
    data += (3).to_bytes(1, byteorder='big')
    data += (startaddress).to_bytes(2, byteorder='big')
    data += (cnt).to_bytes(2, byteorder='big')
    return modbus_send_make(data)

def recv_check():
    size, val = flange_serial_read(0.1)
    return (size > 0), val

def gripper_init():
    flange_serial_write(modbus_fc06(set_Torque_Enable, 0))
    recv_check()
    wait(0.2)
    flange_serial_write(modbus_fc06(set_Operating_Mode, 5 << 8))
    recv_check()
    wait(0.2)
    flange_serial_write(modbus_fc06(set_Torque_Enable, 1))
    recv_check()
    wait(0.2)

def set_gripper_current(current):
    flange_serial_write(modbus_fc06(set_Goal_Current, current))
    recv_check()

def gripper_move(stroke):
    flange_serial_write(modbus_fc16(set_Goal_Position, 2, [stroke, 0]))
    recv_check()

g_tick = 0

def publish_state():
    # 응답: [sid, 3, bytecount, w0hi, w0lo, ... w6hi, w6lo, crcL, crcH] = 19 바이트
    global g_tick
    flange_serial_read(0.01)           # 이전 명령 응답의 남은 조각 비우기 (안 비우면 파싱이 밀린다)
    flange_serial_write(modbus_fc03(%(pbase)d, %(pcnt)d))
    # 응답이 한 번에 다 오지 않는다(실측: 첫 read 에 8바이트만). 19바이트가 찰 때까지 모은다.
    v = bytearray()
    k = 0
    while len(v) < 19 and k < 8:
        size, part = flange_serial_read(0.02)
        if size > 0:
            v += part
        k = k + 1
    if len(v) < 19 or v[0] != g_slaveid or v[1] != 3 or v[2] != 14:
        return
    moving = v[4] & 0x01     # 285 의 하위 바이트. 상위 바이트(상태 비트)까지 보면 늘 참이 된다
    cur = (v[7] << 8) | v[8]
    if cur >= 32768:
        cur = cur - 65536
    pos = ((v[13] << 8) | v[14]) | (((v[15] << 8) | v[16]) << 16)
    if pos >= 2147483648:
        pos = pos - 4294967296
    pos = min(max(pos, 0), 16383)
    cur = min(max(cur + 8192, 0), 16383)
    set_output_register_int(%(sph)d, (pos >> 7) & 0x7F)
    set_output_register_int(%(spl)d, pos & 0x7F)
    set_output_register_int(%(sch)d, (cur >> 7) & 0x7F)
    set_output_register_int(%(scl)d, cur & 0x7F)
    set_output_register_int(%(smov)d, 1 if moving else 0)
    g_tick = (g_tick + 1) & 0x7F
    set_output_register_int(%(stick)d, g_tick)

def dec(v):
    # ROS2가 쓴 7비트 값을 DRL이 읽으면 (b<<24) 형태 -> b 복원
    return (v >> 24) & 0xFF

flange_serial_open(baudrate=%(baud)d, bytesize=DR_EIGHTBITS, parity=DR_PARITY_NONE, stopbits=DR_STOPBITS_ONE)
modbus_set_slaveid(%(sid)d)
gripper_init()

last_seq = dec(get_output_register_int(%(seq)d))
n_loop = 0
st_en = 0
while True:
    seq = dec(get_output_register_int(%(seq)d))
    if seq != last_seq:
        last_seq = seq
        ph = dec(get_output_register_int(%(ph)d))
        pl = dec(get_output_register_int(%(pl)d))
        ch = dec(get_output_register_int(%(ch)d))
        cl = dec(get_output_register_int(%(cl)d))
        pos = (ph << 7) | pl
        cur = (ch << 7) | cl
        set_gripper_current(cur)
        gripper_move(pos)
        n_loop = 4                  # 명령 직후엔 다음 바퀴에 바로 상태 갱신
    # 2026-10-20: 매 바퀴(50Hz) 시리얼 읽기+레지스터 6개 쓰기를 하면 30분쯤 뒤 컨트롤러 응답이 느려짐(ping 14~260ms).
    # 명령 확인은 50Hz 그대로, 상태 읽기·쓰기는 5바퀴에 한 번만(15바퀴는 상태가 0.8Hz 로 너무 느려 닫힘 판정이 틀림).
    # 2026-10-21: 상태 읽기를 켜 둔 채 30~40분이면 컨트롤러가 느려지고 한 번은 재부팅까지 감(하루 5번).
    # 상태가 필요할 때(로봇 작업 중)만 ROS 가 REG_ST_EN=1 로 켠다. 꺼져 있으면 시리얼 읽기·레지스터 쓰기 없이 10Hz 로 명령만 확인.
    n_loop = n_loop + 1
    if n_loop >= 5:
        n_loop = 0
        st_en = dec(get_output_register_int(%(sen)d))
        if st_en:
            publish_state()
    if st_en:
        wait(0.02)
    else:
        wait(0.1)
'''


def build_loop_drl(slave_id, baudrate):
    return DRL_LOOP_TMPL % {
        "baud": baudrate, "sid": slave_id,
        "seq": REG_SEQ, "ph": REG_POS_HI, "pl": REG_POS_LO,
        "ch": REG_CUR_HI, "cl": REG_CUR_LO,
        "pbase": PRESENT_BASE, "pcnt": PRESENT_COUNT,
        "stick": REG_ST_TICK, "sph": REG_ST_PH, "spl": REG_ST_PL,
        "sch": REG_ST_CH, "scl": REG_ST_CL, "smov": REG_ST_MOV, "sen": REG_ST_EN,
    }


def dec_reg(v):
    # DRL 이 쓴 0~127 값이 ROS 쪽에서 그대로 오거나 (b<<24) 로 바이트가 뒤집혀 온다.
    # 둘 중 하나만 채워지므로 OR 로 합치면 어느 쪽이든 복원된다.
    return ((v >> 24) & 0xFF) | (v & 0xFF)


class GripperService(Node):
    def __init__(self):
        super().__init__('gripper_service')
        self.declare_parameter('current', 200)
        self.declare_parameter('slave_id', 1)
        self.declare_parameter('baudrate', 57600)
        self.declare_parameter('launch_wait', 3.0)   # 루프 기동 + init 대기(초)
        self.declare_parameter('state_rate', 20.0)   # 레지스터 폴링 주기(Hz). 실제 발행은 DRL 갱신 속도에 묶인다
        self.declare_parameter('autostart', True)    # 노드 시작과 함께 루프 기동(상태를 바로 받기 위해)
        self.declare_parameter('state_on_start', True)   # False 면 상태 읽기 꺼진 채 시작(gripper/state_enable 로 켬)
        self.declare_parameter('state_idle_off', 0.0)    # >0 이면 이 초 동안 명령·켜기 요청이 없을 때 상태 읽기 자동 끔

        self.loop_started = False
        self.seq = 0
        cbg = ReentrantCallbackGroup()

        self.drl_cli = self.create_client(DrlStart, DRL_START_SRV, callback_group=cbg)
        self.drl_stop_cli = self.create_client(DrlStop, DRL_STOP_SRV, callback_group=cbg)
        self.drl_state_cli = self.create_client(GetDrlState, DRL_STATE_SRV, callback_group=cbg)
        self.get_mode_cli = self.create_client(GetRobotMode, GET_MODE_SRV, callback_group=cbg)
        self.set_mode_cli = self.create_client(SetRobotMode, SET_MODE_SRV, callback_group=cbg)
        self.reg_cli = self.create_client(SetOutputRegisterInt, SET_REG_SRV, callback_group=cbg)
        self.get_cli = self.create_client(GetOutputRegisterInt, GET_REG_SRV, callback_group=cbg)
        self.srv = self.create_service(GripperCmd, GRIPPER_SRV, self.on_cmd, callback_group=cbg)

        self.state_pub = self.create_publisher(JointState, STATE_TOPIC, 10)
        self.state_on = bool(self.get_parameter('state_on_start').value); self.state_t = time.time()
        self.create_service(SetBool, "/dsr01/gripper/state_enable", self.on_state_enable, callback_group=cbg)
        self.create_timer(5.0, self.on_idle_check, callback_group=cbg)
        self.last_tick = None
        self.create_timer(1.0 / self._f('state_rate'), self.on_state_timer, callback_group=cbg)
        if self.get_parameter('autostart').value:
            self._autostart = self.create_timer(0.5, self.on_autostart, callback_group=cbg)

        self.get_logger().info("그리퍼 서비스 준비됨: %s" % GRIPPER_SRV)

    def _i(self, n):
        return self.get_parameter(n).get_parameter_value().integer_value

    def _f(self, n):
        return self.get_parameter(n).get_parameter_value().double_value

    def _set_reg(self, address, value):
        if not self.reg_cli.wait_for_service(timeout_sec=2.0):
            return False
        r = SetOutputRegisterInt.Request()
        r.address = address
        r.value = value
        res = self.reg_cli.call(r)
        return res is not None and res.success

    def _get_reg(self, address):
        if not self.get_cli.wait_for_service(timeout_sec=1.0):
            return None
        # timeout_ms 를 비우면 0 으로 가서 값이 늘 0 으로 온다
        res = self.get_cli.call(GetOutputRegisterInt.Request(address=address, timeout_ms=300))
        return res.value if (res is not None and res.success) else None

    def set_state(self, on):
        ok = self._set_reg(REG_ST_EN, 1 if on else 0)
        if ok:
            if on != self.state_on: self.get_logger().info("상태 읽기 " + ("켬" if on else "끔"))
            self.state_on = on; self.last_tick = None
        self.state_t = time.time()
        return ok

    def on_state_enable(self, req, res):
        res.success = self.set_state(bool(req.data)); res.message = "on" if self.state_on else "off"
        return res

    def on_idle_check(self):
        idle = self._f('state_idle_off')
        if idle > 0 and self.state_on and time.time() - self.state_t > idle:
            self.get_logger().info("%.0f초 동안 요청 없음 -> 상태 읽기 끔" % idle)
            self.set_state(False)

    def on_autostart(self):
        self._autostart.cancel()
        if not self.loop_started:
            self.loop_started = self._launch_loop()

    def on_state_timer(self):
        if not self.loop_started or not self.state_on:
            return
        # 하나씩 동기 호출하면 왕복이 쌓여 3Hz 밖에 안 나온다. 한꺼번에 요청하고 모아서 받는다.
        if not self.get_cli.wait_for_service(timeout_sec=0.5):
            return
        futs = [self.get_cli.call_async(GetOutputRegisterInt.Request(address=a, timeout_ms=300))
                for a in (REG_ST_TICK, REG_ST_PH, REG_ST_PL, REG_ST_CH, REG_ST_CL, REG_ST_MOV)]
        t0 = time.time()
        while not all(f.done() for f in futs) and time.time() - t0 < 0.5:
            time.sleep(0.002)
        if not all(f.done() and f.result() is not None and f.result().success for f in futs):
            return
        vals = [f.result().value for f in futs]
        tick, ph, pl, ch, cl, mov = [dec_reg(v) for v in vals]
        if tick == self.last_tick:
            return          # 루프가 아직 새 상태를 안 썼다
        self.last_tick = tick
        hw_pos = (ph << 7) | pl
        cur = ((ch << 7) | cl) - 8192
        m = JointState()
        m.header.stamp = self.get_clock().now().to_msg()
        m.name = ['gripper']
        m.position = [float(750 - hw_pos)]   # 명령과 같은 규약(750=열림, 0=닫힘)으로 맞춤
        m.velocity = [1.0 if mov else 0.0]
        m.effort = [float(cur)]
        self.state_pub.publish(m)

    def _launch_loop(self):
        if not self.drl_cli.wait_for_service(timeout_sec=3.0):
            self.get_logger().error("drl_start 서비스 없음")
            return False
        # 이전 노드가 띄운 상주 루프가 남아 있으면 새 루프가 못 뜬다. 돌고 있을 때만 정지.
        if self.drl_state_cli.wait_for_service(timeout_sec=2.0):
            st = self.drl_state_cli.call(GetDrlState.Request())
            if st is not None and st.drl_state == 0:      # 0 = PLAY
                self.get_logger().info("이전 DRL 이 실행 중 -> 정지 후 재기동")
                before = self.get_mode_cli.call(GetRobotMode.Request())
                self.drl_stop_cli.call(DrlStop.Request(stop_mode=1))
                time.sleep(1.0)
                # 실행 중인 DRL 을 멈추면 컨트롤러가 MANUAL 로 바뀌고(알람 2008), 그 상태에선
                # drl_start 가 거부된다. 멈추기 전이 AUTONOMOUS 였을 때만 되돌린다.
                if before is not None and before.robot_mode == 1:
                    self.set_mode_cli.call(SetRobotMode.Request(robot_mode=1))
                    time.sleep(0.5)
        self._set_reg(REG_ST_EN, 1 if self.state_on else 0)   # 루프가 처음 읽을 스위치 값
        req = DrlStart.Request()
        req.robot_system = 0
        req.code = build_loop_drl(self._i('slave_id'), self._i('baudrate'))
        # 실기에서 drl_start 는 프로그램이 '시작'되면 바로 응답한다(무한 루프여도).
        fut = self.drl_cli.call_async(req)
        t0 = time.time()
        while not fut.done() and time.time() - t0 < 5.0:
            time.sleep(0.05)
        if fut.done() and fut.result() is not None and not fut.result().success:
            self.get_logger().error("DRL 시작 거부됨. 로봇이 AUTONOMOUS + STANDBY 인지 확인 (teach.py auto, recover.py)")
            return False
        time.sleep(self._f('launch_wait'))   # 루프 기동 + init 완료 대기
        self.get_logger().info("상주 루프 DRL 기동됨")
        return True

    def on_cmd(self, request, response):
        if not self.loop_started:
            if not self._launch_loop():
                response.success = False
                return response
            self.loop_started = True

        pos = max(0, min(750, request.position))
        # 이 그리퍼는 실제 stroke가 0=열림 / 750=닫힘 이라, 문서 규약(0=닫힘, 750=열림)에
        # 맞추기 위해 하드웨어로 보낼 때 반전한다.
        pos = 750 - pos
        cur = request.current if request.current > 0 else self._i('current')
        cur = max(0, min(16383, cur))   # 7비트x2 = 14비트 범위

        # 7비트 분할
        ph, pl = (pos >> 7) & 0x7F, pos & 0x7F
        ch, cl = (cur >> 7) & 0x7F, cur & 0x7F

        if not self.state_on: self.set_state(True)   # 명령이 오면 상태 읽기 자동으로 켬(동작 완료 확인용)
        self.state_t = time.time()
        # payload 먼저 쓰고, seq 를 마지막에 써서 트리거
        self.seq = (self.seq + 1) & 0x7F
        ok = (self._set_reg(REG_POS_HI, ph) and self._set_reg(REG_POS_LO, pl)
              and self._set_reg(REG_CUR_HI, ch) and self._set_reg(REG_CUR_LO, cl)
              and self._set_reg(REG_SEQ, self.seq))

        response.success = ok
        if ok:
            self.get_logger().info("gripper cmd: pos=%d cur=%d seq=%d" % (pos, cur, self.seq))
        else:
            self.get_logger().error("레지스터 write 실패")
        return response


def main():
    rclpy.init()
    node = GripperService()
    ex = MultiThreadedExecutor()
    ex.add_node(node)
    try:
        ex.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
