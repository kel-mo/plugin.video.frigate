# -*- coding: utf-8 -*-
"""Fragmented MP4 re-timed to arrival: Frigate's Birdseye restream stamps frames at 10 fps but makes one only
when it can, so Kodi would play ahead of the stream and keep stopping to buffer. Each fragment's start (tfdt)
is set from when it came; the rest is passed on as is."""
import struct


def boxes(data, start, end):
    """(type, header end, box end) of each whole box in data[start:end]."""
    i = start
    while i + 8 <= end:
        size, kind = struct.unpack('>I4s', data[i:i + 8])
        head = 8
        if size == 1:
            if i + 16 > end:
                return
            size = struct.unpack('>Q', data[i + 8:i + 16])[0]
            head = 16
        if size < head or i + size > end:
            return
        yield kind, i + head, i + size
        i += size


def child(data, start, end, kind):
    return next(((b, e) for k, b, e in boxes(data, start, end) if k == kind), None)


class Retimer:
    def __init__(self):
        self.buf = b''
        self.start = None
        self.scales = {}                        # track id: ticks per second
        self.last = {}                          # track id: (new tfdt, own tfdt)

    def feed(self, data, now):
        """Whole boxes of what has come so far, every fragment's start set from now (seconds)."""
        if self.start is None:
            self.start = now
        buf = self.buf + data
        out = bytearray()
        i = 0
        for kind, body, end in boxes(buf, 0, len(buf)):
            box = bytearray(buf[i:end])
            if kind == b'moov':
                self.read_scales(box, body - i)
            elif kind == b'moof':
                self.fix(box, body - i, now)
            out += box
            i = end
        self.buf = buf[i:]
        return bytes(out)

    def read_scales(self, moov, body):
        for kind, b, e in boxes(moov, body, len(moov)):
            if kind != b'trak':
                continue
            tkhd, mdia = child(moov, b, e, b'tkhd'), child(moov, b, e, b'mdia')
            mdhd = mdia and child(moov, mdia[0], mdia[1], b'mdhd')
            if not (tkhd and mdhd):
                continue
            track = struct.unpack('>I', moov[tkhd[0] + (20 if moov[tkhd[0]] else 12):][:4])[0]
            self.scales[track] = struct.unpack('>I', moov[mdhd[0] + (20 if moov[mdhd[0]] else 12):][:4])[0]

    def fix(self, moof, body, now):
        for kind, b, e in boxes(moof, body, len(moof)):
            if kind != b'traf':
                continue
            tfhd, tfdt = child(moof, b, e, b'tfhd'), child(moof, b, e, b'tfdt')
            if not (tfhd and tfdt):
                continue
            track = struct.unpack('>I', moof[tfhd[0] + 4:tfhd[0] + 8])[0]
            scale = self.scales.get(track, 90000)
            wide = moof[tfdt[0]] == 1
            at = tfdt[0] + 4
            own = struct.unpack('>Q' if wide else '>I', moof[at:at + (8 if wide else 4)])[0]
            clock = scale + int((now - self.start) * scale)       # a second in, like the TS retimer
            if track in self.last:
                new, old = self.last[track]
                step = own - old
                clock = max(clock, new + (step if 0 < step < scale else 1))   # a burst keeps its own spacing
            self.last[track] = (clock, own)
            moof[at:at + (8 if wide else 4)] = struct.pack('>Q' if wide else '>I', clock & ((1 << (64 if wide else 32)) - 1))
