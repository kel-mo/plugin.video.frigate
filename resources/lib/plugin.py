# -*- coding: utf-8 -*-
"""plugin:// router and directory listings."""
import json
import time
import traceback
from datetime import datetime
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcgui
import xbmcplugin

from . import kodi, proxy
from .api import ApiError, AuthError, FrigateClient, stream_name

BASE = 'plugin://{}/'.format(kodi.ADDON_ID)
HANDLE = -1
HLS = 'application/vnd.apple.mpegurl'
MIME = {'hls': HLS, 'frigate': 'video/mp4'}

_formats = {}


def url_for(action, **params):
    params['action'] = action
    return BASE + '?' + urlencode({k: v for k, v in params.items() if v is not None and v != ''})


def end(succeeded=True, cache_to_disc=False):
    if HANDLE >= 0:                              # RunPlugin calls have no listing
        xbmcplugin.endOfDirectory(HANDLE, succeeded, cacheToDisc=cache_to_disc)


def folder(label, action, icon=None, art=None, label2='', **params):
    li = xbmcgui.ListItem(label, label2, offscreen=True)
    art = dict(art or {})
    if icon:
        art.setdefault('icon', icon)
        art.setdefault('thumb', icon)
    if art:
        li.setArt(art)
    xbmcplugin.addDirectoryItem(HANDLE, url_for(action, **params), li, isFolder=True)


def action_item(label, action, **params):
    li = xbmcgui.ListItem(label, offscreen=True)
    li.setArt({'icon': kodi.ICON, 'thumb': kodi.ICON})
    xbmcplugin.addDirectoryItem(HANDLE, url_for(action, **params), li, isFolder=False)


def video_item(label, url, thumb=None, label2='', seconds=0, stamp=None):
    li = xbmcgui.ListItem(label, label2, offscreen=True)
    if thumb:
        li.setArt({'thumb': thumb, 'icon': thumb})
    li.setProperty('IsPlayable', 'true')
    if stamp:
        li.setDateTime(stamp.strftime('%Y-%m-%dT%H:%M:%S'))
    tag = li.getVideoInfoTag()
    tag.setTitle(label)
    tag.setMediaType('video')
    if seconds:
        tag.setDuration(seconds)
    xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)


def resolve(url, mime=None):
    li = xbmcgui.ListItem(path=url, offscreen=True)
    if mime:
        li.setMimeType(mime)
    li.setContentLookup(False)
    xbmcplugin.setResolvedUrl(HANDLE, True, li)
    proxy.wait_for_kodi(url)                    # eases, not fixes, Kodi's stall on stat'ing the URL: xbmc/xbmc#29548


def region(key):
    if key not in _formats:
        _formats[key] = xbmc.getRegion(key) or {'dateshort': '%d/%m/%Y', 'time': '%H:%M'}.get(key, '')
    return _formats[key]


def when(stamp):
    return stamp.strftime('{} {}'.format(region('dateshort'), region('time').replace(':%S', '')))


def camera_label(name, cam=None):
    """Like the Frigate UI: its friendly name, else the name with words capitalised."""
    return (cam or {}).get('friendly_name') or ' '.join(w[:1].upper() + w[1:] for w in name.split('_'))


def page_size():
    return min(max(kodi.setting_int('page_size'), 10), 200)


# ------------------------------------------------------------------ listings
def root():
    if not kodi.setting('server_url'):
        action_item(kodi.L(30003), 'settings')
        return end()
    folder(kodi.L(30000), 'cameras', kodi.ICON)
    folder(kodi.L(30001), 'review', kodi.ICON)
    action_item(kodi.L(30003), 'settings')
    end()


def cameras(client):
    xbmcplugin.setContent(HANDLE, 'videos')
    xbmcplugin.setPluginCategory(HANDLE, kodi.L(30000))
    proxy.forget_snapshots()
    config = client.config()
    birdseye = config.get('birdseye') or {}
    if birdseye.get('enabled'):
        video_item(kodi.L(30002), url_for('birdseye', restream='1' if birdseye.get('restream') else None), kodi.ICON)
    for name, cam in client.cameras(config):
        video_item(camera_label(name, cam), url_for('live', camera=name, stream=stream_name(name, cam)),
                   client.snapshot_url(name))
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
    end()


def live(client, params):
    source = kodi.setting('live_source') or 'frigate'
    resolve(client.live_url(params.get('stream') or params['camera'], source, kodi.setting('live_host')),
            MIME.get(source))


def birdseye(client, params):
    if params.get('restream'):
        return live(client, {'stream': 'birdseye'})
    resolve(client.birdseye_url(), 'video/mp2t')


def review(client, params):
    size = page_size()
    found = client.review(size, params.get('before'))
    xbmcplugin.setContent(HANDLE, 'videos')
    xbmcplugin.setPluginCategory(HANDLE, kodi.L(30001))
    for item in found:
        start, stop = item['start_time'], item.get('end_time') or time.time()   # no end yet while it runs
        data = item.get('data') or {}
        what = ', '.join(dict.fromkeys((data.get('objects') or []) + (data.get('audio') or [])))
        stamp = datetime.fromtimestamp(start)
        video_item('{} · {}'.format(when(stamp), camera_label(item['camera'])),
                   url_for('clip', camera=item['camera'], start=start, end=stop),
                   client.review_thumb_url(item), what, int(stop - start), stamp)
    if len(found) == size:
        folder(kodi.L(30011), 'review', kodi.ICON, before=found[-1]['start_time'])
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_NONE)
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_DATE)
    end()


def clip(client, params):
    resolve(client.clip_url(params['camera'], float(params['start']), float(params['end'])), HLS)


# --------------------------------------------------------------------- main
def run(argv):
    global HANDLE
    HANDLE = int(argv[1])
    params = dict(parse_qsl(argv[2].lstrip('?')))
    action = params.get('action', 'root')
    kodi.debug('action={} params={}'.format(action, json.dumps(params)))
    try:
        dispatch(action, params)
    except AuthError as e:
        kodi.error(str(e))
        end(False)
    except ApiError as e:
        kodi.log('request failed: {}'.format(e), xbmc.LOGERROR)
        kodi.error(str(e))
        end(False)
    except Exception as e:  # keep Kodi from waiting on a listing that never ends
        kodi.log(traceback.format_exc(), xbmc.LOGERROR)
        kodi.error(str(e))
        end(False)


def dispatch(action, params):
    if action == 'root':
        root()
    elif action == 'settings':
        kodi.ADDON.openSettings()
        xbmc.executebuiltin('Container.Refresh')   # Kodi doesn't refresh plugin lists itself
    elif not kodi.setting('server_url'):
        kodi.error(kodi.L(30601))
        end(False)
    elif action == 'cameras':
        cameras(FrigateClient())
    elif action == 'live':
        live(FrigateClient(), params)
    elif action == 'birdseye':
        birdseye(FrigateClient(), params)
    elif action == 'review':
        review(FrigateClient(), params)
    elif action == 'clip':
        clip(FrigateClient(), params)
    else:
        kodi.log('unknown action {}'.format(action), xbmc.LOGWARNING)
        end(False)
