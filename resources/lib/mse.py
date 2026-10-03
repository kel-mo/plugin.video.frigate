# -*- coding: utf-8 -*-
"""go2rtc's MSE websocket, which Frigate's web UI plays live view from: one fragmented MP4 over the signed-in
address. Just enough of RFC 6455 for a client that only listens."""
import base64
import json
import os
import struct
from urllib.parse import quote

PATH = '/live/mse/api/ws?src={}'
CODECS = 'avc1.640029,avc1.64002A,avc1.640033,hvc1.1.6.L153.B0,mp4a.40.2,mp4a.40.5,flac,opus'
CONTINUATION, TEXT, BINARY, CLOSE, PING, PONG = 0, 1, 2, 8, 9, 10


class Error(Exception):
    pass


def target(stream):
    return PATH.format(quote(stream, safe=''))


def handshake():
    return {'Upgrade': 'websocket', 'Connection': 'Upgrade', 'Sec-WebSocket-Version': '13',
            'Sec-WebSocket-Key': base64.b64encode(os.urandom(16)).decode()}


class Stream:
    def __init__(self, sock, rfile):
        self.sock = sock
        self.rfile = rfile                      # the upgrade response's reader: it may hold the first frames

    def send(self, opcode, payload=b''):
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            head = struct.pack('>BB', 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            head = struct.pack('>BBH', 0x80 | opcode, 0x80 | 126, n)
        else:
            head = struct.pack('>BBQ', 0x80 | opcode, 0x80 | 127, n)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def exact(self, n):
        data = self.rfile.read(n)
        if len(data) < n:
            raise Error('connection closed')
        return data

    def frame(self):
        b1, b2 = self.exact(2)
        n = b2 & 0x7f
        if n == 126:
            n = struct.unpack('>H', self.exact(2))[0]
        elif n == 127:
            n = struct.unpack('>Q', self.exact(8))[0]
        mask = self.exact(4) if b2 & 0x80 else None
        data = self.exact(n)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return b1 & 0x0f, data

    def start(self):
        """Ask for MP4 and return go2rtc's MIME type for it."""
        self.send(TEXT, json.dumps({'type': 'mse', 'value': CODECS}).encode())
        for data in self.messages(TEXT):
            msg = json.loads(data.decode('utf-8', 'replace'))
            if msg.get('type') == 'mse':
                return msg.get('value') or 'video/mp4'
            if msg.get('type') == 'error':
                raise Error(msg.get('value') or 'go2rtc error')
        raise Error('closed before the stream started')

    def messages(self, kind):
        """Payloads of one kind until the server closes; pings are answered, the rest skipped."""
        current = None
        while True:
            opcode, data = self.frame()
            if opcode == PING:
                self.send(PONG, data)
            elif opcode == CLOSE:
                return
            elif opcode in (TEXT, BINARY):
                current = opcode
            if opcode in (TEXT, BINARY, CONTINUATION) and current == kind:
                yield data
