"""API client: requests, errors, sign-in and the URLs it builds."""
import email.message
import unittest
from unittest import mock
from urllib.error import HTTPError

from support import PROXY, FrigateCase, api, mock_frigate, xbmcaddon, xbmcgui


class FakeResponse:
    """Stands in for urlopen's response; records close()."""
    def __init__(self, body=b'', error=None):
        self.body, self.error, self.closed = body, error, False
        self.headers = email.message.Message()

    def read(self, *a):
        if self.error:
            raise self.error
        return self.body

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Requests(FrigateCase):
    auth = False

    def client(self, **kw):
        return api.FrigateClient(self.mock.url, '', '', '', **kw)

    def test_config_is_parsed(self):
        self.assertIn('tapo_c200', self.client().config()['cameras'])

    def test_http_error_is_api_error_with_status_and_message(self):
        with self.assertRaises(api.ApiError) as cm:
            self.client().get('/api/fault/500')
        self.assertNotIsInstance(cm.exception, api.AuthError)
        self.assertEqual((cm.exception.status, cm.exception.detail), (500, 'boom'))

    def test_unreachable_is_api_error(self):
        with self.assertRaises(api.ApiError) as cm:
            api.FrigateClient('http://127.0.0.1:9', '', '', '').config()
        self.assertIsNone(cm.exception.status)

    def test_read_timeout_is_api_error(self):
        with self.assertRaises(api.ApiError):
            self.client(timeout=0.3).get('/api/fault/stall')

    def test_truncated_body_is_api_error(self):
        with self.assertRaises(api.ApiError):
            self.client().get('/api/fault/truncated')

    def test_non_json_is_api_error(self):
        with self.assertRaises(api.ApiError):
            self.client().get('/api/fault/text')

    def test_missing_address_is_api_error(self):
        with self.assertRaises(api.ApiError) as cm:
            api.FrigateClient('', '', '', '').config()
        self.assertEqual(str(cm.exception), 'Set the Frigate address first')

    def test_response_closed_after_success(self):
        resp = FakeResponse(b'{"cameras": {}}')
        with mock.patch.object(api, 'urlopen', return_value=resp):
            self.assertEqual(self.client().config(), {'cameras': {}})
        self.assertTrue(resp.closed)

    def test_response_closed_when_read_fails(self):
        resp = FakeResponse(error=TimeoutError('timed out'))
        with mock.patch.object(api, 'urlopen', return_value=resp):
            with self.assertRaises(api.ApiError):
                self.client().config()
        self.assertTrue(resp.closed)

    def test_error_body_closed(self):
        body = FakeResponse(b'{"message": "nope"}')
        error = HTTPError(self.mock.url, 500, 'Server Error', email.message.Message(), body)
        with mock.patch.object(api, 'urlopen', side_effect=error):
            with self.assertRaises(api.ApiError) as cm:
                self.client().config()
        self.assertEqual(cm.exception.detail, 'nope')
        self.assertTrue(body.closed)

    def test_no_credentials_no_sign_in(self):
        self.client().config()
        self.assertEqual(self.mock.logins, 0)
        self.assertNotIn('Authorization', self.mock.seen[-1][2])


class SignIn(FrigateCase):
    def client(self, password=mock_frigate.PASSWORD, token=''):
        return api.FrigateClient(self.mock.url, mock_frigate.USER, password, token)

    def test_signs_in_and_sends_bearer(self):
        client = self.client()
        client.config()
        self.assertEqual(self.mock.logins, 1)
        self.assertEqual(xbmcaddon.SETTINGS['token'], client.token)
        self.assertEqual(self.mock.seen[-1][2].get('Authorization'), 'Bearer ' + client.token)

    def test_expired_token_signs_in_again(self):
        client = self.client(token='stale')
        self.assertIn('cameras', client.config())
        self.assertEqual(self.mock.logins, 1)
        self.assertNotEqual(client.token, 'stale')

    def test_wrong_password_is_auth_error(self):
        with self.assertRaises(api.AuthError):
            self.client('wrong').config()
        self.assertEqual(self.mock.logins, 1)
        self.assertEqual(xbmcaddon.SETTINGS['token'], '')

    def test_refused_after_fresh_sign_in_is_not_retried(self):
        with self.assertRaises(api.AuthError):
            self.client().get('/api/fault/403')
        self.assertEqual(self.mock.logins, 1)


class Urls(FrigateCase):
    auth = False

    def test_clean_url(self):
        cases = {'hulk:5000': 'http://hulk:5000', 'frigate.example.com': 'https://frigate.example.com',
                 'http://nvr.lan:5000/api/': 'http://nvr.lan:5000', '192.168.1.5:8971': 'http://192.168.1.5:8971',
                 ' https://frigate.example.com/ ': 'https://frigate.example.com'}
        self.assertEqual({k: api.clean_url(k) for k in cases}, cases)

    def test_live_url(self):
        client = api.FrigateClient('https://frigate.example.com', '', '', '')
        self.assertEqual(client.live_url('tapo c200/x'), PROXY + '/live/tapo%20c200%2Fx.mp4')
        self.assertEqual(client.birdseye_url(), PROXY + '/birdseye.ts')
        self.assertEqual(client.live_url('tapo_c200', 'rtsp'), 'rtsp://frigate.example.com:8554/tapo_c200')
        self.assertEqual(client.live_url('tapo c200', 'hls'),
                         'http://frigate.example.com:1984/api/stream.m3u8?src=tapo+c200')
        self.assertEqual(client.live_url('cam', 'rtsp', ' nvr.lan '), 'rtsp://nvr.lan:8554/cam')
        self.assertEqual(api.FrigateClient('http://[fd00::5]:5000', '', '', '').live_url('cam', 'rtsp'),
                         'rtsp://[fd00::5]:8554/cam')

    def test_stream_name(self):
        cam = mock_frigate.CONFIG['cameras']['tapo_c100']
        self.assertEqual(api.stream_name('tapo_c100', cam), 'tapo_c100_sub')
        self.assertEqual(api.stream_name('tapo_c325wb', {'live': {'streams': {}}}), 'tapo_c325wb')

    def test_media_urls_go_through_proxy(self):
        client = api.FrigateClient(self.mock.url, '', '', '')
        item = mock_frigate.REVIEW[1]
        self.assertEqual(client.snapshot_url('tapo_c200'), PROXY + '/api/tapo_c200/latest.jpg?h=360')
        self.assertEqual(client.review_thumb_url(item),
                         PROXY + '/clips/review/thumb-{}-{}.webp'.format(item['camera'], item['id']))
        self.assertEqual(client.review_thumb_url({'thumb_path': ''}), '')
        self.assertEqual(client.clip_url('tapo_c100', 1790764342.9, 1790764354.1),
                         PROXY + '/vod/tapo_c100/start/1790764342/end/1790764355/index.m3u8')

    def test_media_needs_the_service(self):
        xbmcgui.Window.PROPS = {}
        with self.assertRaises(api.ApiError) as cm:
            api.FrigateClient(self.mock.url, '', '', '').snapshot_url('tapo_c200')
        self.assertIn('service is not running', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
