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

Live view plays go2rtc's restream of each camera, which Frigate runs
alongside itself: RTSP on port 8554, or HLS on port 1984. Both must be
reachable from Kodi, and neither asks for the sign-in. Pick one under
*Settings → Live view*, and set *Stream host* if go2rtc is not on the same
host as the Frigate address.

---

GPL-2.0-or-later. Not affiliated with the Frigate project.
