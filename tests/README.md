# Offline tests

`stubs/` replaces Kodi's `xbmc*` modules so the add-on can run outside Kodi, and `mock_frigate.py`
fakes a Frigate 0.18 server (sign in as `kodi` / `secret`). The suite needs no network:

```
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -b
```

To try a listing by hand, settings come from the flatpak Kodi profile, or from `FRIGATE_URL`,
`FRIGATE_USER` and `FRIGATE_PASSWORD`; the add-on profile is a temp directory.

```
python3 tests/mock_frigate.py 5000 --no-auth &
FRIGATE_URL=http://127.0.0.1:5000 PYTHONPATH=tests/stubs:. python3 -c 'from resources.lib import plugin, proxy; \
    proxy.xbmcgui.Window.PROPS[proxy.PROPERTY] = "58971"; plugin.run(["plugin://x/", "1", "?action=cameras"])'
```

Listed items are in `xbmcplugin.ITEMS`, notifications in `xbmcgui.LOG`. Media URLs need the proxy's
port in `xbmcgui.Window.PROPS`; the proxy itself only runs when started, as `test_proxy.py` does.
