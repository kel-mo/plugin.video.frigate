# -*- coding: utf-8 -*-
"""Local media proxy: Kodi fetches from 127.0.0.1 and the proxy adds the Frigate token, so the token stays out
of Kodi's logs and texture cache."""
import os
import re
import socket
import threading
import time
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import urlopen

import xbmc
import xbmcgui

from . import api, kodi, mp4, mse, ts

PORT = 58971                             # fixed so Kodi's texture cache keeps its addresses
TRIES = 10
PROPERTY = '{}.proxy'.format(kodi.ADDON_ID)   # Home window property holding the port
TIMEOUT = 4                              # per socket wait: a relay under way ends inside Kodi's five-second wait at exit
LIVE_WAIT = 20                           # go2rtc dials the camera before live view starts; a stop still ends the wait at once
CHUNK = 64 * 1024
ALLOWED = re.compile(r'/(api/[\w-]+/latest\.jpg|vod/[\w-]+/start/\d+/end/\d+/[\w.-]+\.(m3u8|mp4|m4s)'
                     r'|clips/review/thumb-[\w.-]+\.webp)$')
SEEN_KEEP = 10                           # seconds a HEAD from Kodi is remembered, for wait_for_kodi()
LIVE = re.compile(r'/live/([\w%.~-]+)\.mp4$')      # a go2rtc stream, relayed from Frigate's MSE websocket
BIRDSEYE = '/birdseye.ts'                # Frigate's jsmpeg Birdseye, for when go2rtc doesn't restream it
JSMPEG = '/live/jsmpeg/birdseye'
REQUEST_HEADERS = ('Range', 'If-None-Match', 'If-Modified-Since')
RESPONSE_HEADERS = ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges', 'Cache-Control', 'ETag',
                    'Last-Modified')


def address():
    """The running proxy's base address, or None while the service isn't up."""
    port = xbmcgui.Window(10000).getProperty(PROPERTY)
    return 'http://127.0.0.1:{}'.format(port) if port else None


class Server(ThreadingHTTPServer):
    allow_reuse_address = os.name != 'nt'   # on Windows it lets a second server share the port
    daemon_threads = True
    client = None                           # api.FrigateClient, set by the service

    def __init__(self, port):
        super().__init__(('127.0.0.1', port), Handler)
        self.hosts = {'127.0.0.1:{}'.format(port), 'localhost:{}'.format(port)}
        self.seen = {}                          # path: time of Kodi's last HEAD
        self.lock = threading.Lock()
        self.open = set()                       # sockets under way, both sides, cut when Kodi quits
        self.open_lock = threading.Lock()

    def relogin(self, client, stale):
        """One sign-in for all the requests that met the expired token at once."""
        with self.lock:
            if client.token == stale:
                client.login()


class Handler(BaseHTTPRequestHandler):
    timeout = 5                              # a wait on Kodi's side this long means it has gone

    def setup(self):
        super().setup()
        self.upstream = []
        self.answered = None                    # a HEAD from Kodi, noted once its reply is out
        with self.server.open_lock:
            self.server.open.add(self.connection)

    def finish(self):
        with self.server.open_lock:
            self.server.open.difference_update([self.connection] + self.upstream)
        for sock in self.upstream:
            sock.close()
        super().finish()
        if self.answered:
            now = time.time()
            self.server.seen = {p: t for p, t in self.server.seen.items() if now - t < SEEN_KEEP}
            self.server.seen[self.answered] = now

    def log_message(self, fmt, *args):
        kodi.debug('proxy: ' + fmt % args)

    def do_HEAD(self):
        self.relay()

    def do_GET(self):
        self.relay()

    def fetch(self, client, path, target=None, extra=None):
        """The server's response, any status, or None; its socket is held in server.open so a stop cuts it."""
        headers = {k: self.headers[k] for k in REQUEST_HEADERS if self.headers.get(k)}
        headers.update(extra or {})
        if client.token:
            headers['Authorization'] = 'Bearer ' + client.token
        url = urlsplit(client.base_url)
        if url.scheme == 'https':
            conn = HTTPSConnection(url.netloc, timeout=TIMEOUT, context=client.ssl_ctx)
        else:
            conn = HTTPConnection(url.netloc, timeout=TIMEOUT)
        try:
            conn.connect()
            sock = conn.sock
            self.upstream.append(sock)
            with self.server.open_lock:
                self.server.open.add(sock)
            sock.settimeout(LIVE_WAIT if target else TIMEOUT)
            conn.request('GET' if target else self.command, url.path + (target or self.path), headers=headers)
            return conn.getresponse()
        except (HTTPException, OSError) as e:
            conn.close()
            kodi.log('proxy: {} failed: {}'.format(path, e), xbmc.LOGWARNING)
            return None

    def relay(self):
        path = self.path.split('?', 1)[0]
        if self.headers.get('Host') not in self.server.hosts:   # DNS rebinding
            return self.send_error(403)
        if path.startswith('/seen/'):
            stamp = self.server.seen.get(unquote(path[len('/seen'):]))
            return self.reply_headers(200 if stamp and time.time() - stamp < SEEN_KEEP else 404, {'Content-Length': '0'})
        client = self.server.client
        live = LIVE.match(path)
        birdseye = path == BIRDSEYE
        if not (ALLOWED.match(path) or live or birdseye) or not client or not client.base_url:
            return self.send_error(404)
        if self.command == 'HEAD':
            self.answered = path
            if live or birdseye:
                return self.reply_headers(200, {'Content-Type': 'video/mp2t' if birdseye else 'video/mp4'})
        if live or birdseye:
            args = (JSMPEG if birdseye else mse.target(unquote(live.group(1))), mse.handshake())
        else:
            args = ()
        resp = self.fetch(client, path, *args)
        if resp is not None and resp.status == 401 and client.username:
            resp.close()
            try:
                self.server.relogin(client, client.token)
            except api.ApiError as e:
                kodi.log('proxy: sign-in failed: {}'.format(e), xbmc.LOGWARNING)
                return self.send_error(401)
            resp = self.fetch(client, path, *args)
        if resp is None:
            try:
                return self.send_error(502)
            except OSError:
                return                          # Kodi has gone, or the service is stopping
        if (live or birdseye) and resp.status == 101:
            ws = mse.Stream(self.upstream[-1], resp.fp)
            if birdseye:
                return self.stream(path, ws, ts.Retimer(), 'video/mp2t')
            return self.stream(path, ws, mp4.Retimer() if unquote(live.group(1)) == 'birdseye' else None)
        self.upstream[-1].settimeout(TIMEOUT)
        with resp:
            headers = {k: resp.headers[k] for k in RESPONSE_HEADERS if resp.headers.get(k)}
            if self.command == 'GET' and path.endswith('.m3u8') and 'Content-Length' not in headers:
                try:                            # ffmpeg reports a playlist of unknown length as cut short
                    body = resp.read()
                    headers['Content-Length'] = str(len(body))
                    self.reply_headers(resp.status, headers)
                    self.wfile.write(body)
                except (HTTPException, OSError):
                    pass
                return
            self.reply_headers(resp.status, headers)
            if self.command == 'GET':
                try:
                    while True:
                        data = resp.read(CHUNK)
                        if not data or api.aborting():
                            break
                        self.wfile.write(data)
                except (HTTPException, OSError):
                    pass                        # Kodi hangs up when it seeks, or the server drops out

    def reply_headers(self, status, headers):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()

    def stream(self, path, ws, retimer=None, mime=None):
        """Live view as one endless response, until Kodi or the camera stops: go2rtc's fragmented MP4, or
        jsmpeg's MPEG-TS when a mime is given. Birdseye goes through a retimer, as it waits on the picture."""
        try:
            mime = mime or ws.start()
        except (mse.Error, ValueError, OSError) as e:
            kodi.log('proxy: {} failed: {}'.format(path, e), xbmc.LOGWARNING)
            try:
                return self.send_error(502)
            except OSError:
                return
        kodi.debug('proxy: {} is {}'.format(path, mime))
        self.close_connection = True
        try:
            self.reply_headers(200, {'Content-Type': mime.split(';', 1)[0], 'Cache-Control': 'no-store'})
            first = True
            for data in ws.messages(mse.BINARY):
                if api.aborting():
                    break
                if first:
                    ws.sock.settimeout(LIVE_WAIT if retimer else TIMEOUT)
                    first = False
                self.wfile.write(retimer.feed(data, time.time()) if retimer else data)
        except (mse.Error, OSError) as e:
            kodi.debug('proxy: {} ended: {}'.format(path, e))


def start():
    for port in range(PORT, PORT + TRIES):
        try:
            server = Server(port)
            break
        except OSError:
            continue
    else:
        kodi.log('proxy: no free port from {}'.format(PORT), xbmc.LOGERROR)
        return None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    xbmcgui.Window(10000).setProperty(PROPERTY, str(port))
    kodi.log('proxy on port {}'.format(port))
    return server


def stop(server):
    """Right away: relays under way are cut, so no thread of ours outlives Kodi's wait."""
    xbmcgui.Window(10000).clearProperty(PROPERTY)
    server.shutdown()
    server.server_close()
    with server.open_lock:
        for conn in list(server.open):
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def wait_for_kodi(url, limit=5):
    """Keep the plugin alive until Kodi's main thread has checked url through the proxy."""
    parts = urlsplit(url)
    probe = '{}://{}/seen{}'.format(parts.scheme, parts.netloc, quote(parts.path))
    monitor = xbmc.Monitor()
    end = time.time() + limit
    while time.time() < end:
        try:
            with urlopen(probe, timeout=1):
                return
        except HTTPError as e:
            e.close()
        except (URLError, OSError):
            return
        if monitor.waitForAbort(0.05):
            return


def forget_snapshots():
    """Drop Kodi's cached camera snapshots, so a listing shows them fresh."""
    found = kodi.jsonrpc('Textures.GetTextures', properties=['url'],
                         filter={'field': 'url', 'operator': 'contains', 'value': '/latest.jpg'})
    for t in (found or {}).get('textures') or []:
        if t['url'].startswith('http://127.0.0.1:'):
            kodi.jsonrpc('Textures.RemoveTexture', textureid=t['textureid'])
