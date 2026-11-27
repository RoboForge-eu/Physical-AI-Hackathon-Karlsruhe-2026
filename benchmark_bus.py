"""Read-only bus benchmark; never sends goals or enables torque."""
import statistics
import time
from fast_bus import FastBus
from so101 import JOINTS, POS, find_port


def main():
    for name in ("follower", "leader"):
        bus = FastBus(find_port(name))
        try:
            for size in (2, 10):
                times = []
                for _ in range(300):
                    t = time.perf_counter()
                    reply = bus.sync_read(JOINTS, POS, size)
                    times.append((time.perf_counter() - t) * 1000)
                    if reply is None:
                        raise SystemExit(f"{name}: keine vollstaendige Sync-Read-Antwort; keine weiteren Busbefehle.")
                    if any(status for status, _ in reply.values()):
                        raise SystemExit(f"{name}: Servofehler {reply}; keine weiteren Busbefehle.")
                ordered = sorted(times)
                print(f"{name}: 6 IDs, {size} Bytes/ID, n=300, mean={statistics.mean(times):.3f} ms, median={statistics.median(times):.3f} ms, p95={ordered[284]:.3f} ms, max={max(times):.3f} ms, errors=0", flush=True)
        finally:
            bus.close()


if __name__ == "__main__":
    main()
