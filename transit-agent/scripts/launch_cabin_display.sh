#!/usr/bin/env bash
# Launch Chromium on the cabin display, loading the agent UI from the local machine.
#
# Usage:
#   ./scripts/launch_cabin_display.sh [cabin_host] [agent_ip] [monitor]
#
# Examples:
#   ./scripts/launch_cabin_display.sh                    # defaults: glydways@100.75.121.27, auto-detect agent IP, monitor 0
#   ./scripts/launch_cabin_display.sh glydways@100.75.121.27 100.80.210.50 0
#   ./scripts/launch_cabin_display.sh glydways@100.75.121.27 100.80.210.50 5  # right 1920x1080
#
# Monitors (from xrandr):
#   0 = HDMI-1-3 at (0,0)     - left 1920x1080
#   5 = HDMI-1-4 at (5120,0)  - right 1920x1080
#
# Note: --kiosk hides the desktop toolbar. It may ignore --window-position on some
# Chromium versions; if the window appears on the wrong monitor, remove --kiosk.

set -e

CABIN_HOST="${1:-glydways@100.75.121.27}"
AGENT_IP="${2:-}"
MONITOR="${3:-0}"

# Default monitor positions (x, y)
declare -A MONITOR_POS
MONITOR_POS[0]="0,0"      # HDMI-1-3
MONITOR_POS[5]="5120,0"   # HDMI-1-4

if [[ -z "$AGENT_IP" ]]; then
  # Try to get this machine's Tailscale IP
  if command -v tailscale &>/dev/null; then
    AGENT_IP=$(tailscale ip -4 2>/dev/null || true)
  fi
  if [[ -z "$AGENT_IP" ]]; then
    echo "Error: Could not detect agent IP. Pass it as second argument or ensure tailscale is installed."
    echo "Usage: $0 [cabin_host] [agent_ip] [monitor]"
    exit 1
  fi
fi

POS="${MONITOR_POS[$MONITOR]:-0,0}"
URL="http://${AGENT_IP}:3000"

echo "Launching cabin display: $CABIN_HOST"
echo "  URL: $URL"
echo "  Monitor: $MONITOR (position $POS)"
echo ""

# Kill existing Chromium first (separate ssh to avoid pkill affecting the launch)
ssh "$CABIN_HOST" "pkill -9 -f 'chromium-browser/chrome' 2>/dev/null" || true

sleep 1

# Launch Chromium
ssh "$CABIN_HOST" "DISPLAY=:0 nohup chromium-browser --kiosk --app='$URL' --window-size=1920,1080 --window-position=$POS --no-first-run --no-default-browser-check --disable-infobars --disable-session-crashed-bubble </dev/null >/dev/null 2>&1 &"

echo "Chromium launched. Ensure the agent is running: PYTHONPATH=. python -m agent.main"
