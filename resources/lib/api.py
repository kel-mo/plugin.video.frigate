# -*- coding: utf-8 -*-
"""Minimal Frigate REST client built on urllib (no external dependencies)."""
import json
import math
import ssl
from http.client import HTTPException
from http.cookies import CookieError, SimpleCookie
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

import xbmc

from . import kodi, proxy

TIMEOUT = 30
RTSP_PORT = 8554                         # go2rtc restream, unauthenticated
GO2RTC_PORT = 1984                       # go2rtc API, serves HLS
MEDIA_ROOT = '/media/frigate'            # nginx serves its clips/ as /clips/


class ApiError(Exception):
    def __init__(self, message, status=None, detail=None):
        super().__init__(message)
        self.status = status
        self.detail = detail


class AuthError(ApiError):
    pass


def clean_url(url):
    url = (url or '').strip().rstrip('/')
    if url.endswith('/api'):
        url = url[:-4]
    if url and not url.startswith(('http://', 'https://')):
        netloc = url.split('/')[0]
        host = netloc.rsplit(':', 1)[0].strip('[]').lower()
        # IPs, single-label names, LAN domains and Frigate's internal port are usually plain http
        plain = ('.' not in host or host.replace('.', '').isdigit() or ':' in host or netloc.endswith(':5000')
                 or host.endswith(('.local', '.lan', '.home.arpa', '.internal')))
        url = ('http://' if plain else 'https://') + url
    return url


def stream_name(camera, cam=None):
    """The go2rtc stream for a camera's live view: the first of live.streams, else its own name."""
    streams = ((cam or {}).get('live') or {}).get('streams') or {}
    return next(iter(streams.values()), None) or camera


def proxy_address():
    """Waits a moment for the service when Kodi has just started."""
    monitor = xbmc.Monitor()
    for _ in range(30):
        base = proxy.address()
        if base or monitor.waitForAbort(0.1):
            break
    if not base:
        raise ApiError(kodi.L(30626))
    return base


_monitor = None


def aborting():
    """True once Kodi is shutting down; every request checks it so no call outlives teardown."""
    global _monitor
    if _monitor is None:
        _monitor = xbmc.Monitor()
    return _monitor.abortRequested()


def _detail(e):
    try:
        found = json.loads(e.read().decode('utf-8', 'replace'))
        detail = found.get('message') or found.get('detail')
    except (ValueError, AttributeError, HTTPException, OSError):
        return None
    finally:
        e.close()
    return '; '.join(map(str, detail)) if isinstance(detail, list) else detail


class FrigateClient:
    def __init__(self, base_url=None, username=None, password=None, token=None, timeout=TIMEOUT):
        self.base_url = clean_url(base_url if base_url is not None else kodi.setting('server_url'))
        self.username = username if username is not None else kodi.setting('username')
        self.password = password if password is not None else kodi.setting('password')
        self.token = token if token is not None else kodi.setting('token')
        self.timeout = timeout
        self.ssl_ctx = ssl.create_default_context()

    # ------------------------------------------------------------------ core
    def url(self, path, **params):
        clean = {k: v for k, v in params.items() if v is not None and v != ''}
        query = urlencode(clean, doseq=True)
        return '{}{}{}'.format(self.base_url, path, '?' + query if query else '')

    def headers(self, extra=None):
        h = {'Accept': 'application/json',
             'User-Agent': '{}/{}'.format(kodi.ADDON_ID, kodi.ADDON_VERSION)}
        if self.token:
            h['Authorization'] = 'Bearer ' + self.token
        if extra:
            h.update(extra)
        return h

    def send(self, method, path, params=None, body=None, timeout=None):
        """One round trip: (headers, body bytes); every failure is an ApiError."""
        if not self.base_url:
            raise ApiError(kodi.L(30601))
        if aborting():
            raise ApiError('cancelled')
        url = self.url(path, **(params or {}))
        data = None
        extra = {}
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            extra['Content-Type'] = 'application/json'
        req = Request(url, data=data, headers=self.headers(extra), method=method)
        kodi.debug('{} {}'.format(method, url))
        try:
            with urlopen(req, timeout=timeout or self.timeout, context=self.ssl_ctx) as resp:
                return resp.headers, resp.read()
        except HTTPError as e:
            detail = _detail(e)
            if e.code in (401, 403):
                raise AuthError(kodi.L(30615), e.code, detail)
            raise ApiError('HTTP {} for {}: {}'.format(e.code, path, detail or e.reason), e.code, detail)
        except (URLError, HTTPException, OSError) as e:     # OSError covers timeouts
            raise ApiError('{}: {}'.format(kodi.L(30614), e))

    def request(self, method, path, params=None, body=None, timeout=None):
        fresh = False
        if self.username and not self.token:
            self.login()
            fresh = True
        try:
            _, payload = self.send(method, path, params, body, timeout)
        except AuthError:
            if fresh or not self.username:
                raise
            self.login()                                    # the token expired
            _, payload = self.send(method, path, params, body, timeout)
        if not payload:
            return None
        try:
            return json.loads(payload.decode('utf-8'))
        except ValueError:
            raise ApiError('{}: non-JSON response for {}'.format(kodi.L(30614), path))

    def get(self, path, **params):
        return self.request('GET', path, params=params)

    # ------------------------------------------------------------------ auth
    def login(self):
        """Frigate hands the JWT out as a cookie; it works as a Bearer token too."""
        self.token = ''
        headers, _ = self.send('POST', '/api/login', body={'user': self.username, 'password': self.password})
        cookie = SimpleCookie()
        try:
            for value in headers.get_all('Set-Cookie') or []:
                cookie.load(value)
        except CookieError:
            pass
        self.token = next((m.value for m in cookie.values() if m.value), '')
        if not self.token:
            raise AuthError(kodi.L(30615))
        kodi.set_setting('token', self.token)

    # ---------------------------------------------------------------- server
    def config(self):
        return self.get('/api/config') or {}

    def cameras(self):
        """Enabled cameras in the Frigate UI's order: [(name, camera config)]."""
        found = [(n, c) for n, c in (self.config().get('cameras') or {}).items() if c.get('enabled', True)]
        return sorted(found, key=lambda x: (x[1].get('ui') or {}).get('order') or 0)

    def review(self, limit, before=None):
        """Review items, newest first, that started before a timestamp."""
        return self.get('/api/review', limit=limit, before=before) or []

    # ------------------------------------------------------------------ media
    def media_url(self, path, **params):
        """Kodi fetches these through the local proxy, which adds the token."""
        return proxy_address() + self.url(path, **params)[len(self.base_url):]

    def snapshot_url(self, camera, height=360):
        return self.media_url('/api/{}/latest.jpg'.format(quote(camera)), h=height)

    def review_thumb_url(self, item):
        path = item.get('thumb_path') or ''
        return self.media_url(quote(path[len(MEDIA_ROOT):])) if path.startswith(MEDIA_ROOT + '/') else ''

    def clip_url(self, camera, start, end):
        return self.media_url('/api/{}/start/{}/end/{}/clip.mp4'.format(quote(camera), int(start),
                                                                       int(math.ceil(end))))

    def live_url(self, stream, source='rtsp', host=None):
        """go2rtc's restream: plain RTSP, or HLS from its API. Neither takes the Frigate sign-in."""
        host = (host or '').strip() or urlsplit(self.base_url).hostname or ''
        if ':' in host:
            host = '[{}]'.format(host.strip('[]'))
        if source == 'hls':
            return 'http://{}:{}/api/stream.m3u8?{}'.format(host, GO2RTC_PORT, urlencode({'src': stream}))
        return 'rtsp://{}:{}/{}'.format(host, RTSP_PORT, quote(stream))
