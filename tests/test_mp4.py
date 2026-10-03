"""Birdseye's restream, its fragments re-timed to when they arrive."""
import struct
import unittest

import support  # noqa: F401  (stubs on the path)
from mock_frigate import fmp4_frame, fmp4_init
from resources.lib import mp4


def tfdts(data):
    found = []
    for kind, b, e in mp4.boxes(data, 0, len(data)):
        if kind == b'moof':
            traf = mp4.child(data, b, e, b'traf')
            tfdt = mp4.child(data, traf[0], traf[1], b'tfdt')
            found.append(struct.unpack('>Q', data[tfdt[0] + 4:tfdt[0] + 12])[0])
    return found


class Retimer(unittest.TestCase):
    def test_whole_boxes_from_any_pieces(self):
        stream = fmp4_init() + b''.join(fmp4_frame(n * 9000) for n in range(5))
        r = mp4.Retimer()
        out = b''.join(r.feed(stream[i:i + 7], 10.0) for i in range(0, len(stream), 7))
        self.assertEqual(len(out), len(stream))
        self.assertEqual(r.scales, {1: 90000})

    def test_starts_follow_arrival(self):
        r = mp4.Retimer()
        r.feed(fmp4_init(scale=1000), 10.0)
        first = r.feed(fmp4_frame(0), 10.0)
        late = r.feed(fmp4_frame(100), 12.5)                     # stamped 100 ms on, but came 2.5 s later
        self.assertEqual(tfdts(first + late), [1000, 3500])

    def test_burst_keeps_its_spacing(self):
        r = mp4.Retimer()
        out = r.feed(fmp4_init() + b''.join(fmp4_frame(n * 9000) for n in range(3)), 10.0)
        self.assertEqual(tfdts(out), [90000, 99000, 108000])

    def test_other_boxes_untouched(self):
        stream = fmp4_init() + fmp4_frame(0)
        out = mp4.Retimer().feed(stream, 10.0)
        self.assertEqual(out[:len(fmp4_init())], fmp4_init())


if __name__ == '__main__':
    unittest.main()
