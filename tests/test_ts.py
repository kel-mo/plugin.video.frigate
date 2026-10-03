"""Birdseye's MPEG-TS, re-timed to when it arrives."""
import unittest

import support  # noqa: F401  (stubs on the path)
from mock_frigate import BIRDSEYE, ts_packet
from resources.lib import ts


def stamps(data):
    """(PTS, PCR or None) of each packet that opens a PES."""
    found = []
    for i in range(0, len(data), ts.PACKET):
        pkt = data[i:i + ts.PACKET]
        pos, pcr = 4, None
        if pkt[3] & 0x20:
            if pkt[5] & 0x10:
                b = pkt[6:12]
                pcr = b[0] << 25 | b[1] << 17 | b[2] << 9 | b[3] << 1 | b[4] >> 7
            pos = 5 + pkt[4]
        if pkt[1] & 0x40:
            found.append((ts.read_stamp(pkt[pos + 9:pos + 14]), pcr))
    return found


class Retimer(unittest.TestCase):
    def test_whole_packets_from_any_pieces(self):
        r = ts.Retimer()
        out = b''.join(r.feed(BIRDSEYE[i:i + 100], 10.0) for i in range(0, len(BIRDSEYE), 100))
        self.assertEqual(len(out), len(BIRDSEYE))
        self.assertTrue(all(out[i] == ts.SYNC for i in range(0, len(out), ts.PACKET)))

    def test_skips_to_the_next_sync(self):
        out = ts.Retimer().feed(b'\0junk' + BIRDSEYE, 10.0)
        self.assertEqual(len(out), len(BIRDSEYE))

    def test_stamps_follow_arrival(self):
        r = ts.Retimer()
        first = r.feed(ts_packet(5000, 5000), 10.0)
        late = r.feed(ts_packet(5000 + 3600), 12.5)          # stamped 40 ms on, but came 2.5 s later
        self.assertEqual(stamps(first), [(ts.HZ, ts.HZ - ts.HZ // 10)])
        self.assertEqual(stamps(late), [(ts.HZ + int(2.5 * ts.HZ), None)])

    def test_burst_keeps_its_spacing(self):
        r = ts.Retimer()
        out = r.feed(b''.join(ts_packet(5000 + n * 3600) for n in range(3)), 10.0)
        self.assertEqual([p for p, _ in stamps(out)], [ts.HZ, ts.HZ + 3600, ts.HZ + 7200])


if __name__ == '__main__':
    unittest.main()
