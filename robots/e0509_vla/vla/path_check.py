#!/usr/bin/env python3
"""직선 이동(movel) 경로를 관절 공간에서 미리 따라가 본다. 로봇 안 씀.
IK(감쇠 최소제곱)로 경로를 잘게 따라가며 관절값·특이점 근접도(조작성)·팔꿈치 위치를 본다."""
import math, sys
import numpy as np
from scipy.spatial.transform import Rotation
import xml.etree.ElementTree as ET
from fk import URDF
sys.path.insert(0, "/home/omen/doosan_ws/vla_test")
from fk import Chain, zyz_to_matrix

CH = Chain(); CH3 = Chain(tip="link_3")

_root = ET.parse(URDF).getroot()
LIMITS = np.array([[float(_root.find(f"joint[@name='joint_{i}']/limit").get(k))
                    for k in ("lower", "upper")] for i in range(1, 7)])

def validate_solution(q, p, R):
    if np.shape(q) != (6,) or not np.isfinite(q).all():
        raise ValueError("IK nonfinite/invalid joints")
    if np.any(q < LIMITS[:, 0]) or np.any(q > LIMITS[:, 1]):
        raise ValueError("IK outside URDF joint limits")
    e = pose_err(q, p, R)
    # Use the solver's existing orientation convergence tolerance.
    if not np.isfinite(e).all() or np.linalg.norm(e[3:]) >= 1e-4:
        raise ValueError("IK orientation did not converge")

def pose_err(q, p, R):
    pp, RR = CH.fk(q)
    dp = (p - pp) / 1000.0
    dR = R @ RR.T; w = Rotation.from_matrix(dR).as_rotvec()
    return np.concatenate([dp, w])

def jac(q, eps=1e-6):
    p0, R0 = CH.fk(q); J = np.zeros((6, 6))
    for i in range(6):
        dq = np.array(q, float); dq[i] += eps; p1, R1 = CH.fk(dq)
        dR = R1 @ R0.T
        J[:3, i] = (p1 - p0) / 1000.0 / eps
        J[3:, i] = 0.5 * np.array([dR[2, 1] - dR[1, 2], dR[0, 2] - dR[2, 0], dR[1, 0] - dR[0, 1]]) / eps
    return J

def ik(q0, p, R, it=60):
    q = np.array(q0, float)
    if q.shape != (6,) or not np.isfinite(q).all() or not np.isfinite(p).all() or not np.isfinite(R).all():
        raise ValueError("IK nonfinite/invalid input")
    for _ in range(it):
        e = pose_err(q, p, R)
        if np.linalg.norm(e[:3]) < 1e-5 and np.linalg.norm(e[3:]) < 1e-4: break
        J = jac(q); lam = 0.01
        q += J.T @ np.linalg.solve(J @ J.T + lam ** 2 * np.eye(6), e)
    return q, np.linalg.norm(pose_err(q, p, R)[:3]) * 1000

def follow(q0, a, b, ori=(0, 180, 0), n=40):
    R = zyz_to_matrix(*ori); q = np.array(q0, float); out = []
    for t in np.linspace(0, 1, n):
        p = np.array(a) + (np.array(b) - np.array(a)) * t
        q, err = ik(q, p, R)
        J = jac(q); man = math.sqrt(max(np.linalg.det(J @ J.T), 0))
        elbow = CH3.fk(q)[0]
        out.append((t, p, np.degrees(q), man, elbow, err))
    return out, q
