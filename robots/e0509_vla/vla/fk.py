#!/usr/bin/env python3
"""URDF 기반 E0509 순기구학. 관절(rad) -> base 기준 link_6(플랜지) 위치(mm)·회전행렬.
녹화 중 컨트롤러에 TCP 를 묻지 않으려고(과부하 방지) 관절만 기록하고 TCP 는 이걸로 계산한다.
컨트롤러 TCP 와의 차이(툴 오프셋)는 calibrate 로 확인한다."""
import math
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

URDF = Path(__file__).resolve().parent / "robot.urdf"


def _rpy(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _axis_angle(ax, t):
    ax = np.asarray(ax, float) / np.linalg.norm(ax); x, y, z = ax; c, s, C = math.cos(t), math.sin(t), 1 - math.cos(t)
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


class Chain:
    def __init__(self, urdf=URDF, base="base_link", tip="link_6"):
        root = ET.parse(urdf).getroot()
        by_child = {}
        for j in root.findall("joint"):
            o = j.find("origin"); a = j.find("axis")
            by_child[j.find("child").get("link")] = dict(
                name=j.get("name"), type=j.get("type"), parent=j.find("parent").get("link"),
                xyz=[float(v) for v in (o.get("xyz", "0 0 0") if o is not None else "0 0 0").split()],
                rpy=[float(v) for v in (o.get("rpy", "0 0 0") if o is not None else "0 0 0").split()],
                axis=[float(v) for v in (a.get("xyz") if a is not None else "0 0 1").split()])
        chain, link = [], tip
        while link != base:
            j = by_child[link]; chain.append(j); link = j["parent"]
        self.joints = chain[::-1]
        self.names = [j["name"] for j in self.joints if j["type"] != "fixed"]

    def fk(self, q):
        """q: 관절 6개 rad (joint_1..6 순서). 반환 (위치 mm, 회전행렬 3x3)."""
        qd = dict(zip([f"joint_{i}" for i in range(1, 7)], q))
        T = np.eye(4)
        for j in self.joints:
            A = np.eye(4); A[:3, :3] = _rpy(*j["rpy"]); A[:3, 3] = j["xyz"]; T = T @ A
            if j["type"] != "fixed":
                R = np.eye(4); R[:3, :3] = _axis_angle(j["axis"], qd[j["name"]]); T = T @ R
        return T[:3, 3] * 1000.0, T[:3, :3]


def zyz_to_matrix(a, b, g):
    a, b, g = np.deg2rad([a, b, g])
    rz = lambda v: np.array([[math.cos(v), -math.sin(v), 0], [math.sin(v), math.cos(v), 0], [0, 0, 1]])
    ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    return rz(a) @ ry @ rz(g)
