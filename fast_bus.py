"""Feetech group I/O. No EEPROM writes; sync reads and RAM goals only.

Protocol: https://docs.waveshare.com/Servo_Communication_Protocol
"""
import time
from so101 import Bus


def packet(sid, instruction, params=b""):
    body = bytes([sid, len(params) + 2, instruction]) + bytes(params)
    return b"\xff\xff" + body + bytes([~sum(body) & 255])


class FastBus(Bus):
    def _send(self, raw):
        if self.ser.write(raw) != len(raw):
            raise OSError("Unvollstaendiger USB-Schreibvorgang")

    def _receive(self, ids, size, timeout=0.03):
        """Validate IDs, sizes and checksums; discard echo/garbage, keep partial frames."""
        wanted = set(ids)
        replies = {}
        raw = bytearray()
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            raw.extend(self.ser.read(self.ser.in_waiting or 1))
            while len(raw) >= 4:
                i = raw.find(b"\xff\xff")
                if i < 0:
                    raw[:] = raw[-1:] if raw[-1] == 255 else b""
                    break
                del raw[:i]
                if len(raw) < 4:
                    break
                length = raw[3]
                if length < 2 or length > 250:
                    del raw[0]
                    continue
                total = length + 4
                if len(raw) < total:
                    break
                frame = bytes(raw[:total])
                if sum(frame[2:]) & 255 != 255:
                    del raw[0]
                    continue
                del raw[:total]
                sid = frame[2]
                if sid in wanted and length == size + 2:
                    replies[sid] = (frame[4], frame[5:-1])
                    if len(replies) == len(wanted):
                        return replies
        return None

    def sync_read(self, ids, addr, size):
        ids = tuple(ids)
        self.ser.reset_input_buffer()
        self._send(packet(254, 0x82, bytes([addr, size, *ids])))
        return self._receive(ids, size)

    def sync_write(self, addr, values):
        if not values:
            return
        size = len(next(iter(values.values())))
        if any(len(value) != size for value in values.values()):
            raise ValueError("Uneinheitliche Sync-Write-Laenge")
        params = bytes([addr, size]) + b"".join(bytes([sid]) + bytes(value) for sid, value in values.items())
        self._send(packet(254, 0x83, params))
        # Broadcast intentionally has no acknowledgement. Subsequent telemetry
        # checks communication/actual position; a successful write is not motion proof.
