# Frigate for Kodi

Watch the cameras of your self-hosted [Frigate](https://frigate.video) NVR
live on Kodi, and play back the clips of its recent review items.

View only: the add-on never changes anything on the server.

Needs Frigate 0.14 or newer, and Kodi 22.

## Install

1. In Kodi, turn on *Settings → System → Add-ons → Unknown sources*.
2. Download the `repository.kelmo-<version>.zip` linked at the top of
   <https://kel-mo.github.io/repository.kelmo/>.
3. *Add-ons → Install from zip file* and pick that zip.
4. *Install from repository → kel-mo Add-on Repository → Video add-ons →
   Frigate → Install*.

## Set up

1. Open the add-on settings and enter your Frigate address, for example
   `https://frigate.example.com` or `https://nvr.lan:8971`.
2. Enter a Frigate user name and password. Leave them empty for Frigate's
   internal port `http://nvr.lan:5000`, which asks for no sign-in.

## Live view

Live view plays the way the Frigate web UI does, over the Frigate
address with your sign-in, so it works wherever that address does,
behind a reverse proxy too.

## Birdseye

When Birdseye is on in Frigate, it heads the list of cameras. Kodi plays
the same view as the Frigate web UI, over the Frigate address. With
`birdseye: restream: true` in the Frigate config, it plays go2rtc's
sharper H.264 restream instead. Frigate's Birdseye `mode` decides
which cameras appear in it: `continuous` shows them all.

---

GPL-2.0-or-later. Not affiliated with the Frigate project.
