#!/bin/sh
# Start virtual display + noVNC and keep the HH container alive.
# Chromium/Playwright binaries are installed in the image; interactive login is separate.
set -eu

DISPLAY_NUM="${HH_DISPLAY:-:99}"
VNC_PORT="${HH_VNC_PORT:-5900}"
NOVNC_PORT="${HH_NOVNC_PORT:-6080}"
NOVNC_WEB="${HH_NOVNC_WEB:-/usr/share/novnc}"

export DISPLAY="${DISPLAY_NUM}"
export HH_NOVNC_ENABLED=1
export HH_CHROMIUM_INSTALLED=1

mkdir -p "${HH_STATE_DIR:-/var/lib/job-search-hh/state}" \
  "${HH_PROFILE_DIR:-/var/lib/job-search-hh/profile}"

Xvfb "${DISPLAY_NUM}" -screen 0 1280x720x24 -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
sleep 1
x11vnc -display "${DISPLAY_NUM}" -forever -shared -rfbport "${VNC_PORT}" -nopw -localhost \
  >/tmp/x11vnc.log 2>&1 &
websockify --web="${NOVNC_WEB}" "0.0.0.0:${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" \
  >/tmp/websockify.log 2>&1 &

HH_API_PORT="${HH_API_PORT:-8092}"
python -m job_search_hh.api >/tmp/hh-api.log 2>&1 &

while true; do
  python -m job_search_hh.cli session status >/tmp/hh-session.json || true
  sleep 30
done
