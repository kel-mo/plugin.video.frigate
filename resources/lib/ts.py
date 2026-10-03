# -*- coding: utf-8 -*-
"""MPEG-TS re-timed to arrival: Frigate's jsmpeg Birdseye stamps frames at 25 fps but sends one only when the
picture changes, so Kodi would play ahead of the stream and keep stopping to buffer."""
PACKET = 188
SYNC = 0x47
HZ = 90000


def read_stamp(b):
    return ((b[0] >> 1) & 0x07) << 30 | b[1] << 22 | (b[2] >> 1) << 15 | b[3] << 7 | b[4] >> 1


def stamp(prefix, v):
    v &= (1 << 33) - 1
    return bytes([prefix << 4 | (v >> 30 & 0x07) << 1 | 1, v >> 22 & 0xff, (v >> 15 & 0x7f) << 1 | 1,
                  v >> 7 & 0xff, (v & 0x7f) << 1 | 1])


def pcr(v):
    v &= (1 << 33) - 1
    return bytes([v >> 25 & 0xff, v >> 17 & 0xff, v >> 9 & 0xff, v >> 1 & 0xff, (v & 1) << 7 | 0x7e, 0])


class Retimer:
    def __init__(self):
        self.buf = b''
        self.start = None
        self.last = -1
        self.original = None                    # the last frame's own stamp

    def feed(self, data, now):
        """Whole packets of what has come so far, every clock set from now (seconds)."""
        if self.start is None:
            self.start = now
        clock = HZ + int((now - self.start) * HZ)     # a second in, so the reference clock can sit behind
        buf = self.buf + data
        out = bytearray()
        i = 0
        while len(buf) - i >= PACKET:
            if buf[i] != SYNC:
                found = buf.find(bytes([SYNC]), i + 1)
                i = found if found > 0 else len(buf)
                continue
            pkt = bytearray(buf[i:i + PACKET])
            i += PACKET
            self.fix(pkt, clock)
            out += pkt
        self.buf = buf[i:]
        return bytes(out)

    def fix(self, pkt, clock):
        control = pkt[3] >> 4 & 3
        pos = 4
        if control & 2:
            length = pkt[4]
            if length >= 7 and pkt[5] & 0x10:
                pkt[6:12] = pcr(clock - HZ // 10)
            pos = 5 + length
        if not (control & 1 and pkt[1] & 0x40) or pkt[pos:pos + 3] != b'\0\0\1' or pos + 19 > PACKET:
            return
        if not 0xe0 <= pkt[pos + 3] <= 0xef:              # video only; the stream has nothing else
            return
        flags = pkt[pos + 7] >> 6
        if not flags & 2:
            return
        own = read_stamp(pkt[pos + 14:pos + 19] if flags == 3 else pkt[pos + 9:pos + 14])
        step = own - self.original if self.original is not None else 0
        self.original = own
        clock = max(clock, self.last + (step if 0 < step < HZ else 1))   # a burst keeps its own spacing
        self.last = clock
        if flags == 3:
            ahead = read_stamp(pkt[pos + 9:pos + 14]) - own
            pkt[pos + 9:pos + 14] = stamp(3, clock + ahead)
            pkt[pos + 14:pos + 19] = stamp(1, clock)
        else:
            pkt[pos + 9:pos + 14] = stamp(2, clock)
