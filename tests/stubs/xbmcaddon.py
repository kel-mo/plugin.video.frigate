"""Kodi stub: settings come from the real Kodi profile or FRIGATE_URL/FRIGATE_USER/FRIGATE_PASSWORD, strings from strings.po."""
import os, re, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROFILE = os.path.join(tempfile.gettempdir(), 'frigate-test-profile')
SETTINGS = {}
_S = os.path.expanduser('~/.var/app/tv.kodi.Kodi/data/userdata/addon_data/plugin.video.frigate/settings.xml')
if os.path.exists(_S):
    for k, v in re.findall(r'<setting id="([^"]+)"[^>]*>([^<]*)<', open(_S).read()): SETTINGS[k] = v
for k, env in (('server_url', 'FRIGATE_URL'), ('username', 'FRIGATE_USER'), ('password', 'FRIGATE_PASSWORD')):
    if os.environ.get(env): SETTINGS[k] = os.environ[env]
for k, v in re.findall(r'<setting id="([^"]+)"[^>]*>(?:(?!</setting>).)*?<default>([^<]*)</default>',
                       open(os.path.join(ROOT, 'resources', 'settings.xml')).read(), re.S): SETTINGS.setdefault(k, v)
STRINGS = {}
_P = os.path.join(ROOT, 'resources', 'language', 'resource.language.en_gb', 'strings.po')
for i, t in re.findall(r'msgctxt "#(\d+)"\nmsgid "((?:[^"\\]|\\.)*)"', open(_P).read()): STRINGS[int(i)] = t
class Addon:
    def __init__(self, id=None): pass
    def getAddonInfo(self, k): return {'id': 'plugin.video.frigate', 'name': 'Frigate', 'version': '0.1.0',
        'path': ROOT, 'profile': PROFILE}[k]
    def getLocalizedString(self, i): return STRINGS.get(i, '#%d' % i)
    def getSetting(self, k): return SETTINGS.get(k, '')
    def getSettingBool(self, k): return SETTINGS.get(k, 'false') == 'true'
    def getSettingInt(self, k): return int(SETTINGS.get(k) or 0)
    def setSetting(self, k, v): SETTINGS[k] = v
    def openSettings(self): pass
