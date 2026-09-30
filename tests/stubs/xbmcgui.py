"""Kodi stub: dialogs print and record in LOG."""
NOTIFICATION_ERROR = 'error'
LOG = []
class Dialog:
    def notification(self, h, m, i=None, t=0): LOG.append(('notify', m)); print('NOTIFY', m)
class _Tag:
    def __getattr__(self, n): return lambda *a, **k: None
class ListItem:
    def __init__(self, label='', label2='', path='', offscreen=False): self.label = label; self.label2 = label2; self.mime = ''; self.art = {}; self.props = {}; self.path = path
    def setArt(self, a): self.art.update(a)
    def setProperty(self, k, v): self.props[k] = v
    def setMimeType(self, m): self.mime = m
    def __getattr__(self, n): return lambda *a, **k: _Tag()
class Window:
    PROPS = {}
    def __init__(self, i=0): pass
    def getProperty(self, k): return Window.PROPS.get(k, '')
    def setProperty(self, k, v): Window.PROPS[k] = v
    def clearProperty(self, k): Window.PROPS.pop(k, None)
