#!/usr/bin/env python3
"""Tiny fake Frigate server for offline tests: python3 tests/mock_frigate.py [port] [--no-auth]

Shapes follow Frigate 0.18. Sign in as kodi / secret; --no-auth plays the internal port 5000.
"""
import json
import re
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

CONFIG = {'cameras': {
    'tapo_c200': {'enabled': True, 'live': {'streams': {'tapo_c200': 'tapo_c200'}}, 'ui': {'order': 2}},
    'tapo_c100': {'enabled': True, 'friendly_name': 'Driveway', 'ui': {'order': 1},
                  'live': {'streams': {'Sub': 'tapo_c100_sub', 'Main': 'tapo_c100'}}},
    'garage': {'enabled': False, 'live': {'streams': {}}, 'ui': {'order': 0}},
    'tapo_c325wb': {'enabled': True, 'live': {'streams': {}}, 'ui': {'order': 3}}},
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
        if re.match(r'/api/[\w-]+/start/\d+/end/\d+/clip\.mp4$', path):
            return self.reply(200, MP4, 'video/mp4')
        self.reply(404, {'detail': 'Not Found'})

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
