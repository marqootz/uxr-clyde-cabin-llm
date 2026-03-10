# Cabin Display Setup — gdf-concept-cabin-1

## Display Layout (xrandr)

The cabin client has **6 monitors** in a horizontal strip (total 7040×1080):

| Monitor | Output   | Resolution | Position | Notes                    |
|---------|----------|------------|----------|--------------------------|
| 0 (primary) | HDMI-1-3 | 1920×1080 | (0, 0)      | Left 1920×1080 display   |
| 1       | DP-2     | 480×800    | (1920, 0)   | Portrait strip           |
| 2       | DP-4     | 480×800    | (2720, 0)   | Portrait strip           |
| 3       | DP-6     | 480×800    | (3520, 0)   | Portrait strip           |
| 4       | HDMI-1-2 | 480×800   | (4320, 0)   | Portrait strip           |
| 5       | HDMI-1-4 | 1920×1080 | (5120, 0)   | Right 1920×1080 display  |

The **agent display** (1920×360 content) should run on one of the 1920×1080 displays (HDMI-1-3 or HDMI-1-4). Only the bottom 360px are physically visible on the cabin strip.

## Chromium on Cabin

- **Chromium**: Snap package v145 (`/snap/bin/chromium`), also `chromium-browser` wrapper
- **Display**: X11 `:0` (use `DISPLAY=:0` when launching from SSH)

### Launching Chromium Remotely

**Important**: Chromium's `--kiosk` flag **ignores** `--window-position`. Use `--app` without `--kiosk` to position on a specific monitor, or use `--kiosk` and accept fullscreen on the primary display.

#### Option A: App mode (positioned, no kiosk)

For **HDMI-1-3** (left 1920×1080 at 0,0):

```bash
ssh glydways@100.75.121.27 "DISPLAY=:0 chromium-browser \
  --app='http://<AGENT_IP>:3000' \
  --window-size=1920,1080 \
  --window-position=0,0 \
  --no-first-run \
  --no-default-browser-check \
  --disable-infobars \
  --disable-session-crashed-bubble \
  &"
```

For **HDMI-1-4** (right 1920×1080 at 5120,0):

```bash
ssh glydways@100.75.121.27 "DISPLAY=:0 chromium-browser \
  --app='http://<AGENT_IP>:3000' \
  --window-size=1920,1080 \
  --window-position=5120,0 \
  --no-first-run \
  --no-default-browser-check \
  --disable-infobars \
  --disable-session-crashed-bubble \
  &"
```

Replace `<AGENT_IP>` with your local machine's Tailscale IP (e.g. `100.80.210.50`).

#### Option B: Kiosk mode (fullscreen)

Uses primary display; cannot target a specific monitor:

```bash
ssh glydways@100.75.121.27 "DISPLAY=:0 chromium-browser \
  --kiosk \
  --window-size=1920,1080 \
  --app='http://<AGENT_IP>:3000' \
  --no-first-run \
  --no-default-browser-check \
  &"
```

### Snap Chromium Sandbox

Snap Chromium may require `--no-sandbox` when launched from SSH without a proper session. If you see permission errors:

```bash
DISPLAY=:0 chromium-browser --app='http://<AGENT_IP>:3000' --no-sandbox --window-position=0,0 ...
```

### Environment

Ensure the agent is running and serving the display:

1. Local machine: `PYTHONPATH=. python -m agent.main`
2. Cabin loads: `http://<agent-tailscale-ip>:3000`
3. WebSocket connects to `ws://<agent-ip>:8765` using `location.hostname`

## Troubleshooting: Blank Display

1. **Connection status** — The display shows "Connecting…" or "Connection failed" when the WebSocket can't reach the agent. If you see "Connection failed", check:
   - Agent is running: `PYTHONPATH=. python -m agent.main`
   - **macOS firewall**: System Settings → Network → Firewall → allow Python (or temporarily disable to test)
   - Cabin can reach agent: from cabin run `curl -s -o /dev/null -w "%{http_code}" http://<agent-ip>:3000/` (should return 200)

2. **Agent logs** — When the cabin connects, the agent logs "Display client connected (total=1)". If you never see this, the WebSocket isn't reaching the agent.

3. **Script load errors** — Open DevTools (F12) on the cabin browser if possible, or test locally: open `http://localhost:3000` on the agent machine to verify the display works.

## Quick Reference

```bash
# List displays
ssh glydways@100.75.121.27 "DISPLAY=:0 xrandr --listmonitors"

# Launch on left 1920×1080 (replace 100.80.210.50 with your agent IP)
ssh glydways@100.75.121.27 "DISPLAY=:0 chromium-browser --app='http://100.80.210.50:3000' --window-size=1920,1080 --window-position=0,0 --no-first-run --disable-infobars &"

# Kill existing Chromium
ssh glydways@100.75.121.27 "pkill -f chromium" || true
```
