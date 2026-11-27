"""Simulation des SO-101 ohne Hardware.

Zwei Backends mit derselben Schnittstelle (sim.backend.Backend):
  - "kinsim": eigene leichte Simulation (welt.py): Servo-Positionsregler, Kontakt mit Tisch/Halterung/Loch,
    Schachtel greifen, zwei Kameras (Handgelenk, Turm) mit Domain Randomization. Laeuft ueberall, keine GPU.
  - "isaac": NVIDIA Isaac Sim 6.2 / Isaac Lab 3.0 (isaac/), in %USERPROFILE%\\isaac-env. Gleiche Methoden.

Alles hier ist SIMULATION. Es oeffnet nie einen COM-Port und bewegt nie einen echten Arm.
"""
SIM_PREFIX = "sim_"          # Arm-Schluessel simulierter Arme beginnen immer so (nie mit echten verwechseln)


def is_sim_arm(key):
    return str(key).startswith(SIM_PREFIX)
