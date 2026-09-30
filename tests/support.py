"""Shared set-up: Kodi stubs on the path, a mock Frigate per test class, fresh settings per test."""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, 'stubs'), os.path.dirname(HERE)]

import xbmcaddon  # noqa: E402
import xbmcgui  # noqa: E402
import xbmcplugin  # noqa: E402

import mock_frigate  # noqa: E402
from resources.lib import api, plugin, proxy  # noqa: E402

with open(os.path.join(os.path.dirname(HERE), 'resources', 'settings.xml'), encoding='utf-8') as _f:
    DEFAULTS = dict(re.findall(r'<setting id="([^"]+)"[^>]*>(?:(?!</setting>).)*?<default>([^<]*)</default>',
                               _f.read(), re.S))
PROXY = 'http://127.0.0.1:{}'.format(proxy.PORT)


def settings(**values):
    xbmcaddon.SETTINGS.clear()
    xbmcaddon.SETTINGS.update(DEFAULTS, **values)


class FrigateCase(unittest.TestCase):
    auth = True

    @classmethod
    def setUpClass(cls):
        cls.mock = mock_frigate.start(cls.auth)

    @classmethod
    def tearDownClass(cls):
        mock_frigate.stop(cls.mock)

    def setUp(self):
        creds = {'username': mock_frigate.USER, 'password': mock_frigate.PASSWORD} if self.auth else {}
        settings(server_url=self.mock.url, **creds)
        self.mock.logins = 0
        self.mock.tokens.clear()
        self.mock.seen.clear()
        del xbmcplugin.ITEMS[:]
        xbmcplugin.META.clear()
        del xbmcgui.LOG[:]
        xbmcgui.Window.PROPS = {proxy.PROPERTY: str(proxy.PORT)}

    def run_plugin(self, query):
        plugin.run([plugin.BASE, '1', query])
        return xbmcplugin.ITEMS

    def resolved(self):
        ok, li = xbmcplugin.META['resolved']
        self.assertTrue(ok)
        return li


__all__ = ['api', 'plugin', 'proxy', 'mock_frigate', 'xbmcaddon', 'xbmcgui', 'xbmcplugin', 'FrigateCase',
           'settings', 'PROXY']
