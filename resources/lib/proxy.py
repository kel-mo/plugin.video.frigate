# -*- coding: utf-8 -*-
"""Local media proxy: Kodi fetches from 127.0.0.1 and the proxy adds the Frigate token, so the token stays out
of Kodi's logs and texture cache."""
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import xbmc
import xbmcgui

from . import kodi

PORT = 58971                             # fixed so Kodi's texture cache keeps its addresses
TRIES = 10
PROPERTY = '{}.proxy'.format(kodi.ADDON_ID)   # Home window property holding the port
TIMEOUT = 30
CHUNK = 64 * 1024
ALLOWED = re.compile(r'/(api/[\w-]+/latest\.jpg|api/[\w-]+/start/\d+/end/\d+/clip\.mp4'
                     r'|clips/review/thumb-[\w.-]+\.webp)$')
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
        self.lock = threading.Lock()

    def relogin(self, client, stale):
        """One sign-in for all the requests that met the expired token at once."""
        with self.lock:
            if client.token == stale:
                client.login()


class Handler(BaseHTTPRequestHandler):
    timeout = 60

    def log_message(self, fmt, *args):
        kodi.debug('proxy: ' + fmt % args)

    def do_HEAD(self):
        self.relay()

    def do_GET(self):
        self.relay()

    def fetch(self, client):
        headers = {k: self.headers[k] for k in REQUEST_HEADERS if self.headers.get(k)}
        if client.token:
            headers['Authorization'] = 'Bearer ' + client.token
        req = Request(client.base_url + self.path, headers=headers, method=self.command)
        try:
            return urlopen(req, timeout=TIMEOUT, context=client.ssl_ctx)
        except HTTPError as e:                  # 304 and 416 included
            return e
        except (URLError, socket.timeout, OSError) as e:
            kodi.log('proxy: {} failed: {}'.format(self.path.split('?', 1)[0], e), xbmc.LOGWARNING)
            return None

    def relay(self):
        path = self.path.split('?', 1)[0]
        if self.headers.get('Host') not in self.server.hosts:   # DNS rebinding
            return self.send_error(403)
        client = self.server.client
        if not ALLOWED.match(path) or not client or not client.base_url:
            return self.send_error(404)
        resp = self.fetch(client)
        if resp is not None and resp.status == 401 and client.username:
            resp.close()
            try:
                self.server.relogin(client, client.token)
            except Exception as e:              # api.ApiError, kept out of this module's imports
                kodi.log('proxy: sign-in failed: {}'.format(e), xbmc.LOGWARNING)
                return self.send_error(401)
            resp = self.fetch(client)
        if resp is None:
            return self.send_error(502)
        with resp:
            self.send_response(resp.status)
            for k in RESPONSE_HEADERS:
                if resp.headers.get(k):
                    self.send_header(k, resp.headers[k])
            self.end_headers()
            if self.command == 'GET':
                try:
                    while True:
                        data = resp.read(CHUNK)
                        if not data:
                            break
                        self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, socket.timeout):
                    pass                        # Kodi hangs up when it seeks


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
    xbmcgui.Window(10000).clearProperty(PROPERTY)
    server.shutdown()
    server.server_close()
