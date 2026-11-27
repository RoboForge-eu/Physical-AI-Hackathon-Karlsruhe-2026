"""Offline SO-101 incident timeline. Usage: python diagnose.py [logfile]"""
import argparse
import ast
from datetime import datetime
from pathlib import Path

def report(path):
    print(path)
    first = None
    phase = "Vorpruefung"
    leader = {}
    trace = None
    previous = None
    speeds = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stamp, _, msg = line.partition(" ")
        try:
            now = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if first is None:
            first = now
        if msg.startswith("Leader:"):
            leader = ast.literal_eval(msg.partition(":")[2].strip())
        if msg.startswith("Ziele:") and leader:
            goals = ast.literal_eval(msg.partition(":")[2].strip())
            print("Startziel minus Leader (Schritte):", {j: goals[j]-leader[j] for j in goals})
        if msg.startswith("BEWEGUNG:"):
            phase = msg.partition(":")[2].strip()
            trace = None
            previous = None
            speeds.clear()
        if msg.startswith("TRACE "):
            trace = line
            positions = ast.literal_eval(msg.split(" | ")[1].removeprefix("Leader "))
            if previous:
                dt = (now - previous[0]).total_seconds()
                if dt > 0:
                    rates = [abs(a-b)*360/4096/dt for a,b in zip(positions, previous[1])]
                    speeds.append((now, max(rates), rates.index(max(rates))+1))
            previous = now, positions
        if msg.startswith(("BEWEGUNG:", "BEENDET:", "ABLAGE NICHT", "ABGELEGT.", "VERBINDUNGSFEHLER", "STOP:")):
            print(f"{(now-first).total_seconds():7.3f}s  {msg}")
            if msg.startswith(("BEENDET:", "ABLAGE NICHT")):
                print("          Phase:", phase)
                if trace:
                    print("          Letzte Stichprobe:", trace)
                if speeds:
                    for label, samples in (("Phase", speeds), ("letzte Sekunde", [x for x in speeds if (now-x[0]).total_seconds() <= 1])):
                        if samples:
                            stamp, rate, joint = max(samples, key=lambda x: x[1])
                            print(f"          {label}: max. mittlere Leader-Geschwindigkeit {rate:.1f} Grad/s, ID {joint}, {(now-stamp).total_seconds():.2f} s vor Ereignis")
    print("Tischabstand und Kontakt werden im Log nicht gemessen.")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("logfile", type=Path, nargs="?")
    args = p.parse_args()
    files = sorted((Path(__file__).resolve().parent / "logs").glob("*.log"))
    if not args.logfile and not files:
        p.error("Keine Logdatei gefunden")
    report(args.logfile or files[-1])
