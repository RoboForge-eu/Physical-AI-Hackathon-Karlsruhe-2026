"""Servo-Schritte <-> Gelenkwinkel (rad) wie so101_modell.py (gleiches URDF so101_new_calib).

Gelenke in Isaac: shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper.
Arm: rad = (ticks - 2047) * 2*pi/4096 * SIGN. Greifer: Backe 0 (zu) .. GRIP_OPEN_RAD (auf), Ticks aus remote_kin.
ACHTUNG: Vorzeichen/Nullstellung beim ersten Isaac-Start mit sim/isaac/pruefen.py gegen remote_kin.fk pruefen.
"""
import math

NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
MID = 2047
STEP = 2 * math.pi / 4096
SIGN = [1, 1, 1, 1, 1, 1]
GRIP_CLOSED_TICKS, GRIP_OPEN_TICKS = 1430, 2880
GRIP_OPEN_RAD = 1.745


def ticks_zu_rad(t):
    out = [(t[i] - MID) * STEP * SIGN[i] for i in range(5)]
    g = (t[5] - GRIP_CLOSED_TICKS) / (GRIP_OPEN_TICKS - GRIP_CLOSED_TICKS)
    return out + [max(0.0, min(1.0, g)) * GRIP_OPEN_RAD]


def rad_zu_ticks(r):
    out = [int(round(MID + r[i] / (STEP * SIGN[i]))) for i in range(5)]
    g = r[5] / GRIP_OPEN_RAD
    return out + [int(round(GRIP_CLOSED_TICKS + g * (GRIP_OPEN_TICKS - GRIP_CLOSED_TICKS)))]
