#!/bin/sh
# Open the desktop application on $DISPLAY, type into its first window, and check it is still
# running. 0.4.0 crashed on the first key press (half of a keyboard library pair bundled), which
# every check that ran the command line passed.
#
#   DISPLAY=:99 packaging/linux/window_smoke.sh dist/installers/ELI_Legal-*.AppImage
#
# Needs xdotool and an X display (CI: xvfb-run). Exit 1 if no window appears or the process dies.
set -u
APP="$1"
LOG="${TMPDIR:-/tmp}/eli-legal-window-smoke.log"
# its own session, so stopping it stops the AppImage launcher and the window together
setsid "$APP" --appimage-extract-and-run >"$LOG" 2>&1 &
PID=$!
WIN="$(timeout 120 xdotool search --sync --onlyvisible --name 'ELI Legal' 2>/dev/null | head -n 1)"
if [ -z "$WIN" ]; then
  echo "window_smoke: no ELI Legal window within 120 s" >&2
  kill -- "-$PID" 2>/dev/null; cat "$LOG" >&2; exit 1
fi
xdotool windowfocus "$WIN" 2>/dev/null
sleep 1
xdotool type --delay 50 'a1 Zz'
xdotool key Tab BackSpace
sleep 3
if kill -0 "$PID" 2>/dev/null; then
  echo "window_smoke: the window opened, took key presses and is still running"
  kill -- "-$PID" 2>/dev/null; wait "$PID" 2>/dev/null; exit 0
fi
echo "window_smoke: the application died after the key presses" >&2
cat "$LOG" >&2; exit 1
