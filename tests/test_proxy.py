"""Media proxy: adds the token, signs in again when it expires, relays nothing else."""
import http.client
import threading
import time
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import FrigateCase, api, mock_frigate, proxy


class Proxy(FrigateCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = proxy.start()

    @classmethod
    def tearDownClass(cls):
        proxy.stop(cls.server)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.client = api.FrigateClient(self.mock.url, mock_frigate.USER, mock_frigate.PASSWORD, '')
        self.client.login()
        self.server.client = self.client

    def fetch(self, path, host=None):
        port = self.server.server_address[1]
        req = Request('http://127.0.0.1:{}{}'.format(port, path),
                      headers={'Host': host or '127.0.0.1:{}'.format(port)})
        try:
            with urlopen(req, timeout=5) as resp:
                return resp.status, resp.headers['Content-Type'], resp.read()
        except HTTPError as e:
            e.close()
            return e.code, None, None

    def test_relays_media_with_token(self):
        self.assertEqual(self.fetch('/api/tapo_c200/latest.jpg?h=360'), (200, 'image/jpeg', mock_frigate.JPEG))
        self.assertEqual(self.mock.seen[-1][2].get('Authorization'), 'Bearer ' + self.client.token)

    def test_refuses_other_paths(self):
        self.assertEqual(self.fetch('/api/config')[0], 404)
        self.assertFalse([s for s in self.mock.seen if s[1] == '/api/config'])

    def test_refuses_other_hosts(self):
        self.assertEqual(self.fetch('/api/tapo_c200/latest.jpg', 'evil.example:80')[0], 403)

    def test_expired_token_signs_in_again(self):
        self.client.token = 'stale'
        self.assertEqual(self.fetch('/clips/review/thumb-tapo_c100-1.webp')[0], 200)
        self.assertEqual(self.mock.logins, 2)

    def test_vod_relayed(self):
        playlist = self.fetch('/vod/tapo_c100/start/1/end/2/index.m3u8')
        self.assertEqual(playlist, (200, 'application/vnd.apple.mpegurl', mock_frigate.VOD.encode()))
        port = self.server.server_address[1]
        with urlopen(Request('http://127.0.0.1:{}/vod/tapo_c100/start/1/end/2/index.m3u8'.format(port),
                             headers={'Host': '127.0.0.1:{}'.format(port)}), timeout=5) as resp:
            self.assertEqual(resp.headers['Content-Length'], str(len(mock_frigate.VOD)))
        self.assertEqual(self.fetch('/vod/tapo_c100/start/1/end/2/seg-1-v1-a1.m4s')[0], 200)
        self.assertEqual(self.fetch('/api/tapo_c100/start/1/end/2/clip.mp4')[0], 404)

    def test_live_relays_mse(self):
        self.assertEqual(self.fetch('/live/tapo_c100_sub.mp4'), (200, 'video/mp4', b''.join(mock_frigate.LIVE)))
        self.assertEqual(self.mock.mse_asked[-1]['type'], 'mse')
        self.assertIn('avc1.640029', self.mock.mse_asked[-1]['value'])
        self.assertEqual(self.mock.mse_pongs[-1], (10, b'hi'))
        ws = [s for s in self.mock.seen if s[1].startswith('/live/mse/api/ws')][-1]
        self.assertEqual((ws[1], ws[2].get('Authorization')), ('/live/mse/api/ws?src=tapo_c100_sub',
                                                              'Bearer ' + self.client.token))

    def test_birdseye_relayed_retimed(self):
        status, ctype, body = self.fetch('/birdseye.ts')
        self.assertEqual((status, ctype, len(body)), (200, 'video/mp2t', len(mock_frigate.BIRDSEYE)))
        self.assertTrue(all(body[i] == 0x47 for i in range(0, len(body), 188)))
        ws = [s for s in self.mock.seen if s[1] == '/live/jsmpeg/birdseye'][-1]
        self.assertEqual(ws[2].get('Authorization'), 'Bearer ' + self.client.token)

    def test_birdseye_restream_retimed(self):
        status, ctype, body = self.fetch('/live/birdseye.mp4')
        self.assertEqual((status, ctype, len(body)), (200, 'video/mp4', len(b''.join(mock_frigate.BIRDSEYE_MSE))))
        self.assertNotEqual(body, b''.join(mock_frigate.BIRDSEYE_MSE))      # tfdt rewritten, nothing else

    def test_live_signs_in_again(self):
        self.client.token = 'stale'
        self.assertEqual(self.fetch('/live/tapo_c200.mp4')[0], 200)
        self.assertEqual(self.mock.logins, 2)

    def test_live_unknown_stream(self):
        self.assertEqual(self.fetch('/live/nope.mp4')[0], 502)

    def test_live_may_take_longer_to_start(self):
        self.mock.live_delay = 0.6
        try:
            with mock.patch.object(proxy, 'TIMEOUT', 0.2):
                self.assertEqual(self.fetch('/live/tapo_c200.mp4')[0], 200)
        finally:
            self.mock.live_delay = 0

    def test_stopping_cuts_live_view_still_starting(self):
        self.mock.live_delay = 5
        server = proxy.Server(proxy.PORT + proxy.TRIES + 1)
        server.client = self.client
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        try:
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            conn.request('GET', '/live/tapo_c200.mp4', headers={'Host': '127.0.0.1:{}'.format(port)})
            deadline = time.time() + 5
            while len(server.open) < 2 and time.time() < deadline:      # Kodi's side and the server's
                time.sleep(0.05)
            self.assertEqual(len(server.open), 2)
            t = time.time()
            proxy.stop(server)
            with self.assertRaises((http.client.HTTPException, OSError)):
                conn.getresponse().read()
            self.assertLess(time.time() - t, 2)
        finally:
            self.mock.live_delay = 0

    def test_seen_after_kodi_head(self):
        port = self.server.server_address[1]
        url = 'http://127.0.0.1:{}/live/tapo_c200.mp4'.format(port)
        self.assertEqual(self.fetch('/seen/live/tapo_c200.mp4')[0], 404)
        with urlopen(Request(url + '?mimetype=video%2fmp4', method='HEAD', headers={'Host': '127.0.0.1:{}'.format(port)}),
                     timeout=5) as resp:
            self.assertEqual(resp.status, 200)
        t = time.time()
        proxy.wait_for_kodi(url)                        # noted once the reply is out, a moment after Kodi has it
        self.assertLess(time.time() - t, 0.5)
        self.assertEqual(self.fetch('/seen/live/tapo_c200.mp4')[0], 200)

    def test_wait_for_kodi_gives_up(self):
        port = self.server.server_address[1]
        t = time.time()
        proxy.wait_for_kodi('http://127.0.0.1:{}/vod/x/start/1/end/2/index.m3u8'.format(port), limit=0.3)
        self.assertLess(time.time() - t, 1)

    def test_stopping_cuts_a_relay_under_way(self):
        held, done = threading.Event(), threading.Event()

        def stuck(handler):                             # a relay sat waiting on a socket, as at Kodi's exit
            held.set()
            try:
                handler.connection.recv(1)
            except OSError:
                pass
            done.set()
        server = proxy.Server(proxy.PORT + proxy.TRIES)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        with mock.patch.object(proxy.Handler, 'relay', stuck):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            conn.request('GET', '/api/tapo_c200/latest.jpg', headers={'Host': '127.0.0.1:{}'.format(port)})
            self.assertTrue(held.wait(5))
            t = time.time()
            proxy.stop(server)
            self.assertTrue(done.wait(2))                                     # cut at once, not after a timeout
            self.assertLess(time.time() - t, 2)
            with self.assertRaises((http.client.HTTPException, OSError)):
                conn.getresponse()


if __name__ == '__main__':
    unittest.main()
