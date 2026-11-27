"""Simuliertes Handy fuer den Trockenlauf: Kupplung druecken, 10 cm nach vorn, 5 cm hoch, loslassen.

python remote_sim_client.py ws://127.0.0.1:8765/teleop     (WLAN, WebSocket)
python remote_sim_client.py --livekit                      (Internet, LiveKit-Raum aus livekit.json)
"""
import asyncio, json, sys, time


def pose_at(t, seq):
    clutch = 0.3 < t < 2.5
    s = min(max((t - 0.5) / 1.5, 0.0), 1.0)          # 0..1 waehrend 0,5-2,0 s
    p = [0.0, 0.05 * s, -0.10 * s]                      # ARKit: -z = vorn, y = oben
    return {"t": "pose", "seq": seq, "ts": time.monotonic(), "clutch": clutch,
            "p": p, "q": [0, 0, 0, 1], "grip": s, "track": "normal"}


HELLO = {"t": "hello", "v": 1, "client": "sim", "app": "0", "device": "pc"}


async def drive(send, states, rate, seconds=3.0):
    """Sendet Posen; gibt (gesendet, Zeit) zurueck."""
    seq = 0
    t0 = time.monotonic()
    while (t := time.monotonic() - t0) < seconds:
        seq += 1
        await send(pose_at(t, seq))
        if seq % 30 == 0 and states:
            last = states[-1]
            print(f"t={t:4.2f}s aktiv={last['active']} Spitze={last['ee']} Gelenke={last['joints']}", flush=True)
        await asyncio.sleep(1 / rate)
    return seq, time.monotonic() - t0


async def run(url, rate=60.0):
    from websockets.asyncio.client import connect
    async with connect(url) as ws:
        await ws.send(json.dumps(HELLO))
        print(json.loads(await ws.recv()))
        states = []

        async def reader():
            async for raw in ws:
                m = json.loads(raw)
                if m["t"] == "state":
                    states.append(m)
                elif m["t"] != "pong":
                    print("<-", m)

        task = asyncio.create_task(reader())
        await drive(lambda m: ws.send(json.dumps(m)), states, rate)
        task.cancel()


async def run_livekit(rate=60.0, seconds=3.0, identity=None):
    """Wie ein Handy ueber das Internet: LiveKit-Raum, Bediener-Token mit Daten-Recht.
    Gibt eine kleine Statistik zurueck (fuer Tests)."""
    from livekit import rtc
    import stream_livekit as S
    from remote_server import TOPIC
    cfg, why = S.load_config()
    if cfg is None:
        raise SystemExit(why)
    identity = identity or f"test-bediener-{int(time.time())}"
    room = rtc.Room()
    states, welcome, rtts = [], asyncio.get_event_loop().create_future(), []
    pings = {}

    def on_data(packet):
        if packet.topic != TOPIC:
            return
        m = json.loads(packet.data)
        if m["t"] == "welcome" and not welcome.done():
            welcome.set_result(m)
        elif m["t"] == "state":
            states.append(m)
        elif m["t"] == "pong" and m.get("id") in pings:
            rtts.append((time.monotonic() - pings.pop(m["id"])) * 1000)
        elif m["t"] != "pong":
            print("<-", m, flush=True)

    room.on("data_received", on_data)
    token = S.make_token(cfg, identity, publish=False, data=True)
    t = time.monotonic()
    await room.connect(cfg["url"], token, rtc.RoomOptions(auto_subscribe=False))
    print(f"verbunden mit Raum {cfg['room']} nach {time.monotonic() - t:.1f} s", flush=True)
    lp = room.local_participant

    async def send(m, reliable=False):
        await lp.publish_data(json.dumps(m), reliable=reliable, topic=TOPIC)

    w = None
    for attempt in range(10):                  # bis der Roboter-PC im Raum ist und antwortet
        await send(HELLO, reliable=True)
        try:
            w = await asyncio.wait_for(asyncio.shield(welcome), 1.0)
            break
        except asyncio.TimeoutError:
            continue
    if w is None:
        await room.disconnect()
        raise SystemExit("Keine Antwort vom Roboter-PC (laeuft remote_server mit LiveKit?)")
    print("welcome:", w, flush=True)
    for i in range(5):
        pings[i] = time.monotonic()
        await send({"t": "ping", "id": i, "ts": time.monotonic()}, reliable=True)
        await asyncio.sleep(0.1)
    sent, dur = await drive(lambda m: send(m), states, rate, seconds)
    await asyncio.sleep(0.5)
    await room.disconnect()
    result = {"welcome": w, "sent": sent, "states": len(states), "rtt_ms": sorted(rtts),
              "last": states[-1] if states else None, "seconds": dur}
    print(f"gesendet {sent} Posen in {dur:.1f} s, empfangen {len(states)} Zustaende, "
          f"Antwortzeit (Ping) {', '.join(f'{r:.0f}' for r in sorted(rtts))} ms", flush=True)
    return result


if __name__ == "__main__":
    if "--livekit" in sys.argv:
        asyncio.run(run_livekit())
    else:
        asyncio.run(run(sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8765/teleop"))
