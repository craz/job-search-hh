#!/bin/sh
# Start virtual display + noVNC and keep the HH container alive.
# Chromium/Playwright binaries are installed in the image; interactive login is separate.
# Survives container restart with a dirty /tmp (stale X locks) by healing the stack.
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

display_suffix() {
  echo "${DISPLAY_NUM}" | tr -d ':'
}

process_running() {
  # $1 = substring matched against ps args (busybox/procps compatible).
  ps -eo args 2>/dev/null | grep -F -- "$1" | grep -v grep >/dev/null 2>&1
}

port_listening() {
  # Prefer ss; fall back to python so we don't depend on netstat.
  if command -v ss >/dev/null 2>&1; then
    ss -lnt 2>/dev/null | grep -E ":$1[[:space:]]" >/dev/null 2>&1 && return 0
  fi
  python - "$1" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket()
s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", port))
except OSError:
    sys.exit(1)
finally:
    s.close()
sys.exit(0)
PY
}

cleanup_stale_x() {
  suffix="$(display_suffix)"
  if process_running "Xvfb ${DISPLAY_NUM}"; then
    return 0
  fi
  rm -f "/tmp/.X${suffix}-lock" "/tmp/.X11-unix/X${suffix}" 2>/dev/null || true
  mkdir -p /tmp/.X11-unix
  chmod 1777 /tmp/.X11-unix 2>/dev/null || true
}

ensure_xvfb() {
  if process_running "Xvfb ${DISPLAY_NUM}"; then
    return 0
  fi
  cleanup_stale_x
  Xvfb "${DISPLAY_NUM}" -screen 0 1280x720x24 -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
  sleep 1
  if process_running "Xvfb ${DISPLAY_NUM}"; then
    return 0
  fi
  echo "hh-browser-runtime: Xvfb failed to start" >&2
  tail -n 40 /tmp/xvfb.log 2>/dev/null >&2 || true
  return 1
}

ensure_x11vnc() {
  if port_listening "${VNC_PORT}"; then
    return 0
  fi
  # Drop a dead x11vnc that no longer binds the port.
  if process_running "x11vnc -display ${DISPLAY_NUM}"; then
    ps -eo pid=,args= 2>/dev/null | while read -r pid args; do
      case "$args" in
        *"x11vnc -display ${DISPLAY_NUM}"*) kill "$pid" 2>/dev/null || true ;;
      esac
    done
    sleep 0.5
  fi
  x11vnc -display "${DISPLAY_NUM}" -forever -shared -rfbport "${VNC_PORT}" -nopw -localhost \
    >/tmp/x11vnc.log 2>&1 &
  sleep 1
  if port_listening "${VNC_PORT}"; then
    return 0
  fi
  echo "hh-browser-runtime: x11vnc failed to bind :${VNC_PORT}" >&2
  tail -n 40 /tmp/x11vnc.log 2>/dev/null >&2 || true
  return 1
}

ensure_websockify() {
  if port_listening "${NOVNC_PORT}"; then
    return 0
  fi
  if process_running "websockify --web=${NOVNC_WEB}"; then
    ps -eo pid=,args= 2>/dev/null | while read -r pid args; do
      case "$args" in
        *"websockify --web=${NOVNC_WEB}"*) kill "$pid" 2>/dev/null || true ;;
      esac
    done
    sleep 0.5
  fi
  websockify --web="${NOVNC_WEB}" "0.0.0.0:${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" \
    >/tmp/websockify.log 2>&1 &
  sleep 1
  if port_listening "${NOVNC_PORT}"; then
    return 0
  fi
  echo "hh-browser-runtime: websockify failed to bind :${NOVNC_PORT}" >&2
  tail -n 40 /tmp/websockify.log 2>/dev/null >&2 || true
  return 1
}

ensure_interactive_stack() {
  ensure_xvfb || return 1
  ensure_x11vnc || return 1
  ensure_websockify || return 1
  return 0
}

ensure_interactive_stack || true

HH_API_PORT="${HH_API_PORT:-8092}"
python -m job_search_hh.api >/tmp/hh-api.log 2>&1 &

while true; do
  ensure_interactive_stack || true
  python -m job_search_hh.cli session status >/tmp/hh-session.json || true
  sleep 15
done
