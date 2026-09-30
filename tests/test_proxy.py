"""Media proxy: adds the token, signs in again when it expires, relays nothing else."""
import unittest
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


if __name__ == '__main__':
    unittest.main()
