#!/usr/bin/env python3
"""Tiny fake Frigate server for offline tests: python3 tests/mock_frigate.py [port] [--no-auth]

Shapes follow Frigate 0.18. Sign in as kodi / secret; --no-auth plays the internal port 5000.
"""
import base64
import hashlib
import json
import re
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

USER, PASSWORD = 'kodi', 'secret'
NOW = 1790764342.0
JPEG = b'\xff\xd8\xff\xe0' + b'\0' * 60 + b'\xff\xd9'
WEBP = b'RIFF\x24\0\0\0WEBPVP8 ' + b'\0' * 24
MP4 = b'\0\0\0\x18ftypisom\0\0\x02\0isomiso2' + b'\0' * 64
LIVE = [MP4, b'\0\0\0\x10moof' + b'\1' * 8, b'\0\0\x01\x08mdat' + b'\2' * 260, b'\0\0\0\x10moof' + b'\3' * 70000]


def ts_packet(pts, pcr=None):
    """One MPEG-TS packet opening a video PES stamped pts, with a PCR when given."""
    head = b'\x47\x41\x00'
    if pcr is None:
        head += b'\x10'
    else:
        head += b'\x30\x07\x10' + bytes([pcr >> 25 & 0xff, pcr >> 17 & 0xff, pcr >> 9 & 0xff, pcr >> 1 & 0xff,
                                          (pcr & 1) << 7 | 0x7e, 0])
    stamp = bytes([0x21 | (pts >> 30 & 7) << 1, pts >> 22 & 0xff, (pts >> 15 & 0x7f) << 1 | 1, pts >> 7 & 0xff,
                   (pts & 0x7f) << 1 | 1])
    pkt = head + b'\0\0\1\xe0\0\0\x80\x80\x05' + stamp
    return pkt + b'\xff' * (188 - len(pkt))


def box(kind, body=b''):
    return struct.pack('>I', 8 + len(body)) + kind + body


def fmp4_init(track=1, scale=90000):
    tkhd = box(b'tkhd', b'\0\0\0\3' + b'\0' * 8 + struct.pack('>I', track) + b'\0' * 68)
    mdhd = box(b'mdhd', b'\0\0\0\0' + b'\0' * 8 + struct.pack('>I', scale) + b'\0' * 8)
    return box(b'ftyp', b'iso5\0\0\2\0iso5iso6mp41') + box(b'moov', box(b'trak', tkhd + box(b'mdia', mdhd)))


def fmp4_frame(tfdt, track=1):
    """One fragment of one sample, as go2rtc sends them."""
    tfhd = box(b'tfhd', b'\0\2\0\0' + struct.pack('>I', track))
    traf = box(b'traf', tfhd + box(b'tfdt', b'\1\0\0\0' + struct.pack('>Q', tfdt)) + box(b'trun', b'\0\0\0\1' + b'\0\0\0\1'))
    return box(b'moof', box(b'mfhd', b'\0' * 8) + traf) + box(b'mdat', b'\0\0\0\2\x09\xf0')


BIRDSEYE_MSE = [fmp4_init()] + [fmp4_frame(n * 9000) for n in range(4)]
BIRDSEYE = b''.join(ts_packet(90000 + n * 3600, 90000 + n * 3600 if n % 2 == 0 else None) for n in range(6))
VOD = '#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-MAP:URI="init-v1-a1.mp4"\n#EXTINF:10.0,\nseg-1-v1-a1.m4s\n#EXT-X-ENDLIST\n'

CONFIG = {'cameras': {
    'tapo_c200': {'enabled': True, 'live': {'streams': {'tapo_c200': 'tapo_c200'}}, 'ui': {'order': 2}},
    'tapo_c100': {'enabled': True, 'friendly_name': 'Driveway', 'ui': {'order': 1},
                  'live': {'streams': {'Sub': 'tapo_c100_sub', 'Main': 'tapo_c100'}}},
    'garage': {'enabled': False, 'live': {'streams': {}}, 'ui': {'order': 0}},
    'tapo_c325wb': {'enabled': True, 'live': {'streams': {}}, 'ui': {'order': 3}}},
    'birdseye': {'enabled': True, 'restream': False, 'mode': 'motion', 'width': 1280, 'height': 720},
    'go2rtc': {'streams': {'tapo_c200': ['rtsp://*:*@camera/stream1']}}}


def make_review():
    items = []
    for n in range(25):
        start = NOW - n * 600 + 0.247918
        rid = '{:.6f}-rev{:03d}'.format(start, n)
        cam = ('tapo_c100', 'tapo_c200', 'tapo_c325wb')[n % 3]
        items.append({'id': rid, 'camera': cam, 'start_time': start, 'end_time': None if n == 0 else start + 12.3,
                      'severity': 'alert' if n % 2 else 'detection',
                      'thumb_path': '/media/frigate/clips/review/thumb-{}-{}.webp'.format(cam, rid),
                      'data': {'detections': ['{}-ev'.format(rid)], 'objects': ['person', 'dog'][:1 + n % 2],
                               'verified_objects': [], 'sub_labels': [], 'zones': [],
                               'audio': ['bark'] if n == 3 else [], 'thumb_time': start + 0.2, 'metadata': None},
                      'has_been_reviewed': False})
    return items


REVIEW = make_review()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def reply(self, status, body=b'', ctype='application/json', headers=()):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def signed_in(self):
        auth = self.headers.get('Authorization') or ''
        return not self.server.auth or auth[len('Bearer '):] in self.server.tokens

    def do_POST(self):
        self.server.seen.append(('POST', self.path, dict(self.headers)))
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        if self.path != '/api/login':
            return self.reply(404, {'detail': 'Not Found'})
        self.server.logins += 1
        if not self.server.auth:
            return self.reply(404, {'message': 'Authentication is disabled'})
        if (body.get('user'), body.get('password')) != (USER, PASSWORD):
            return self.reply(401, {'message': 'Login failed'})
        token = 'jwt-{}'.format(self.server.logins)
        self.server.tokens.add(token)
        self.reply(200, headers=[('Set-Cookie', 'frigate_token={}; HttpOnly; Path=/; Max-Age=86400'.format(token))])

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self.server.seen.append(('GET', self.path, dict(self.headers)))
        url = urlparse(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        path = url.path
        if path.startswith('/api/fault/'):
            return self.fault(path[len('/api/fault/'):])
        if not self.signed_in():
            return self.reply(401, b'<html>401 Authorization Required</html>', 'text/html')
        if path == '/api/config':
            return self.reply(200, CONFIG)
        if path == '/api/review':
            before = float(query.get('before') or time.time() + 3600)
            found = [r for r in REVIEW if r['start_time'] < before]
            return self.reply(200, found[:int(query['limit'])] if query.get('limit') else found)
        if re.match(r'/api/[\w-]+/latest\.jpg$', path):
            return self.reply(200, JPEG, 'image/jpeg')
        if re.match(r'/clips/review/thumb-[\w.-]+\.webp$', path):
            return self.reply(200, WEBP, 'image/webp')
        if re.match(r'/vod/[\w-]+/start/\d+/end/\d+/index\.m3u8$', path):
            self.send_response(200)             # nginx-vod sends no length
            self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
            self.end_headers()
            self.wfile.write(VOD.encode())
            self.close_connection = True
            return
        if re.match(r'/vod/[\w-]+/start/\d+/end/\d+/(init-v1-a1\.mp4|seg-\d+-v1-a1\.m4s)$', path):
            return self.reply(200, MP4, 'video/mp4')
        if path == '/live/mse/api/ws' and self.headers.get('Upgrade') == 'websocket':
            return self.mse(query.get('src'))
        if path == '/live/jsmpeg/birdseye' and self.headers.get('Upgrade') == 'websocket':
            return self.jsmpeg()
        self.reply(404, {'detail': 'Not Found'})

    def frame(self, opcode, payload):
        n = len(payload)
        head = struct.pack('>BB', 0x80 | opcode, n) if n < 126 else (
            struct.pack('>BBH', 0x80 | opcode, 126, n) if n < 65536 else struct.pack('>BBQ', 0x80 | opcode, 127, n))
        self.wfile.write(head + payload)

    def read_frame(self):
        b1, b2 = self.rfile.read(2)
        n = b2 & 0x7f
        if n == 126:
            n = struct.unpack('>H', self.rfile.read(2))[0]
        mask = self.rfile.read(4)
        return b1 & 0x0f, bytes(b ^ mask[i % 4] for i, b in enumerate(self.rfile.read(n)))

    def upgrade(self):
        key = self.headers['Sec-WebSocket-Key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
        self.send_response(101)
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', base64.b64encode(hashlib.sha1(key.encode()).digest()).decode())
        self.end_headers()
        self.close_connection = True

    def jsmpeg(self):
        """Frigate's jsmpeg Birdseye: MPEG-TS stamped at 25 fps, in pieces that ignore packet bounds."""
        self.upgrade()
        for i in range(0, len(BIRDSEYE), 300):
            self.frame(2, BIRDSEYE[i:i + 300])
            time.sleep(0.05)
        self.frame(8, b'')

    def mse(self, src):
        """go2rtc's MSE websocket: a codec list in, the MIME type and fragmented MP4 out."""
        self.upgrade()
        opcode, data = self.read_frame()
        self.server.mse_asked.append(json.loads(data))
        time.sleep(self.server.live_delay)      # go2rtc dials the camera first
        if src not in ('tapo_c100_sub', 'tapo_c200', 'birdseye'):
            return self.frame(1, json.dumps({'type': 'error', 'value': 'streams: unknown source'}).encode())
        self.frame(9, b'hi')                    # a ping, to be answered
        self.frame(1, json.dumps({'type': 'mse', 'value': 'video/mp4; codecs="avc1.640029,flac"'}).encode())
        for chunk in BIRDSEYE_MSE if src == 'birdseye' else LIVE:
            self.frame(2, chunk)
        self.server.mse_pongs.append(self.read_frame())
        self.frame(8, b'')
        self.close_connection = True

    def fault(self, kind):
        if kind == '500':
            return self.reply(500, {'success': False, 'message': 'boom'})
        if kind == '403':
            return self.reply(403, {'success': False, 'message': 'Access denied'})
        if kind == 'text':
            return self.reply(200, b'0.18.0-77a66e7', 'text/plain')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', '100')
        self.end_headers()
        self.wfile.write(b'{"cameras":')
        self.wfile.flush()
        if kind == 'stall':
            time.sleep(1.5)                     # longer than the tests' client timeout
        # 'truncated': hang up short of Content-Length


class MockFrigate(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=0, auth=True):
        super().__init__(('127.0.0.1', port), Handler)
        self.auth = auth
        self.tokens = set()
        self.logins = 0
        self.seen = []
        self.live_delay = 0
        self.mse_asked = []
        self.mse_pongs = []

    @property
    def url(self):
        return 'http://127.0.0.1:{}'.format(self.server_address[1])


def start(auth=True):
    server = MockFrigate(auth=auth)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def stop(server):
    server.shutdown()
    server.server_close()


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    server = MockFrigate(int(args[0]) if args else 5000, auth='--no-auth' not in sys.argv)
    print('mock Frigate on {}'.format(server.url))
    server.serve_forever()
