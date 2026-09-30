"""plugin:// listings and playback against the mock Frigate."""
import time
import unittest
from urllib.parse import parse_qsl, urlsplit

from support import PROXY, FrigateCase, mock_frigate, settings, xbmcgui, xbmcplugin


def query(url):
    return dict(parse_qsl(urlsplit(url).query))


class Listings(FrigateCase):
    def labels(self, items):
        return [li.label for _, li, _ in items]

    def test_root(self):
        self.assertEqual(self.labels(self.run_plugin('')), ['Cameras', 'Review', 'Settings'])
        self.assertTrue(xbmcplugin.META['end'])

    def test_root_unconfigured_offers_settings(self):
        settings(server_url='')
        self.assertEqual(self.labels(self.run_plugin('')), ['Settings'])

    def test_cameras(self):
        items = self.run_plugin('?action=cameras')
        self.assertEqual(self.labels(items), ['Driveway', 'Tapo C200', 'Tapo C325wb'])
        self.assertEqual([query(url) for url, _, _ in items],
                         [{'action': 'live', 'camera': 'tapo_c100', 'stream': 'tapo_c100_sub'},
                          {'action': 'live', 'camera': 'tapo_c200', 'stream': 'tapo_c200'},
                          {'action': 'live', 'camera': 'tapo_c325wb', 'stream': 'tapo_c325wb'}])
        _, li, is_folder = items[0]
        self.assertFalse(is_folder)
        self.assertEqual(li.props['IsPlayable'], 'true')
        self.assertEqual(li.art['thumb'], PROXY + '/api/tapo_c100/latest.jpg?h=360')

    def test_live_rtsp(self):
        self.run_plugin('?action=live&camera=tapo_c100&stream=tapo_c100_sub')
        self.assertEqual(self.resolved().path, 'rtsp://127.0.0.1:8554/tapo_c100_sub')
        settings(server_url=self.mock.url, live_host='nvr.lan')
        self.run_plugin('?action=live&camera=tapo_c200')
        self.assertEqual(self.resolved().path, 'rtsp://nvr.lan:8554/tapo_c200')

    def test_live_hls(self):
        settings(server_url=self.mock.url, live_source='hls')
        self.run_plugin('?action=live&camera=tapo_c100&stream=tapo_c100_sub')
        li = self.resolved()
        self.assertEqual(li.path, 'http://127.0.0.1:1984/api/stream.m3u8?src=tapo_c100_sub')
        self.assertEqual(li.mime, 'application/vnd.apple.mpegurl')

    def test_review_items(self):
        settings(server_url=self.mock.url, username=mock_frigate.USER, password=mock_frigate.PASSWORD,
                 page_size='10')
        items = self.run_plugin('?action=review')[:10]
        first, fourth = items[0][1], items[3][1]
        self.assertTrue(first.label.endswith(' · Tapo C100'))
        self.assertEqual((items[1][1].label2, fourth.label2), ('person, dog', 'person, dog, bark'))
        item = mock_frigate.REVIEW[3]
        self.assertEqual(fourth.art['thumb'],
                         PROXY + '/clips/review/thumb-{}-{}.webp'.format(item['camera'], item['id']))
        self.assertEqual(query(items[3][0]), {'action': 'clip', 'camera': item['camera'],
                                              'start': str(item['start_time']), 'end': str(item['end_time'])})
        running = query(items[0][0])                # no end_time yet: plays up to now
        self.assertAlmostEqual(float(running['end']), time.time(), delta=5)

    def test_review_next_page(self):
        settings(server_url=self.mock.url, username=mock_frigate.USER, password=mock_frigate.PASSWORD,
                 page_size='10')
        items = self.run_plugin('?action=review')
        self.assertEqual(len(items), 11)
        url, li, is_folder = items[-1]
        self.assertEqual((li.label, is_folder), ('Next page', True))
        self.assertEqual(float(query(url)['before']), mock_frigate.REVIEW[9]['start_time'])
        del xbmcplugin.ITEMS[:]
        page2 = self.run_plugin('?' + urlsplit(url).query)
        self.assertEqual(query(page2[0][0])['start'], str(mock_frigate.REVIEW[10]['start_time']))

    def test_clip(self):
        item = mock_frigate.REVIEW[3]
        self.run_plugin('?action=clip&camera=tapo_c100&start={}&end={}'.format(item['start_time'], item['end_time']))
        li = self.resolved()
        self.assertEqual(li.path, PROXY + '/api/tapo_c100/start/{}/end/{}/clip.mp4'.format(
            int(item['start_time']), int(item['end_time']) + 1))
        self.assertEqual(li.mime, 'video/mp4')

    def test_unreachable_server_ends_listing(self):
        settings(server_url='http://127.0.0.1:9')
        self.assertEqual(self.run_plugin('?action=cameras'), [])
        self.assertIs(xbmcplugin.META['end'], False)
        self.assertTrue(xbmcgui.LOG[-1][1].startswith('Could not reach Frigate'))

    def test_wrong_password_notifies(self):
        settings(server_url=self.mock.url, username=mock_frigate.USER, password='wrong')
        self.run_plugin('?action=review')
        self.assertIs(xbmcplugin.META['end'], False)
        self.assertEqual(xbmcgui.LOG[-1][1], 'Frigate did not accept the user name or password')


if __name__ == '__main__':
    unittest.main()
