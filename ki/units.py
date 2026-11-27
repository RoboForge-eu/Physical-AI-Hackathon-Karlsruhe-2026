"""Umrechnung Servo-Schritte <-> Grad (Mitte 2047 = 0 Grad). Ohne Abhaengigkeiten, in beiden Umgebungen."""
import numpy as np

MID = 2047
DEG_PER_STEP = 360.0 / 4096


def to_deg(steps):
    return (np.asarray(steps, dtype=np.float32) - MID) * DEG_PER_STEP


def to_steps(deg):
    return np.clip(np.rint(np.asarray(deg, dtype=np.float64) / DEG_PER_STEP + MID), 0, 4095).astype(int)
