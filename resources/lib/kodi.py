# -*- coding: utf-8 -*-
"""Thin helpers around the Kodi Python API."""
import os

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_NAME = ADDON.getAddonInfo('name')
ADDON_VERSION = ADDON.getAddonInfo('version')
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('path'))
ICON = os.path.join(ADDON_PATH, 'resources', 'icon.png')


def L(string_id, *args):
    text = ADDON.getLocalizedString(string_id)
    return text.format(*args) if args else text


def setting(key):
    return ADDON.getSetting(key)


def fresh_setting(key):
    """Read from disk; ADDON keeps a snapshot, and settings buttons run before the dialog saves."""
    return xbmcaddon.Addon().getSetting(key)


def setting_bool(key):
    return ADDON.getSettingBool(key)


def setting_int(key):
    return ADDON.getSettingInt(key)


def set_setting(key, value):
    ADDON.setSetting(key, str(value) if value is not None else '')


def log(msg, level=xbmc.LOGINFO):
    xbmc.log('[{}] {}'.format(ADDON_ID, msg), level)


def debug(msg):
    if setting_bool('debug'):
        xbmc.log('[{}] {}'.format(ADDON_ID, msg), xbmc.LOGINFO)
    else:
        xbmc.log('[{}] {}'.format(ADDON_ID, msg), xbmc.LOGDEBUG)


def error(message, heading=None):
    xbmcgui.Dialog().notification(heading or ADDON_NAME, message, xbmcgui.NOTIFICATION_ERROR, 6000)
