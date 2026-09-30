"""Kodi stub: logs and builtins are printed and recorded in BUILTINS."""
LOGDEBUG, LOGINFO, LOGWARNING, LOGERROR = 0, 1, 2, 3
BUILTINS = []
def log(msg, level=0): print('LOG', level, msg)
def executebuiltin(s, wait=False): BUILTINS.append(s); print('BUILTIN', s)
class Monitor:
    def abortRequested(self): return False
    def waitForAbort(self, t=0): return False
def getRegion(k): return {'dateshort': '%d/%m/%Y', 'time': '%H:%M:%S'}.get(k, '')
