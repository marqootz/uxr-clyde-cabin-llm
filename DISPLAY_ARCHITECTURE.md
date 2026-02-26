# Display UI Architecture — `display/`

## Overview

1080×360 fullscreen browser display driven entirely by WebSocket messages from the Python agent. No user interaction — output only. Two layers run simultaneously:

1. **Presence layer** — ambient agent animation, always visible, reflects agent state
2. **Content layer** — cards that appear on top when Clyde surfaces information

The presence layer never fully disappears. When a content card is active, the presence animation retreats to the left third of the display and dims. When the card dismisses, it expands back to full width.

---

## Stack

```
Three.js          — agent presence animation (audio-reactive)
Lottie-web        — state transition overlays (listening ring, processing pulse)
Mapbox GL JS      — route/map cards
Tailwind CSS      — card layout and typography
WebSocket         — all display state driven from Python agent
Web Audio API     — feeds TTS amplitude to the presence animation
```

---

## Project Structure

```
display/
├── index.html
├── main.js                  # Electron entry (or serve statically)
├── ws_client.js             # WebSocket client — receives commands, drives state
├── state.js                 # Display state machine
├── layers/
│   ├── presence.js          # Three.js agent presence animation
│   └── lottie_states.js     # Lottie state transition controller
├── cards/
│   ├── card_manager.js      # Mounts/unmounts cards, handles transitions
│   ├── IdleCard.js          # Route progress + ETA
│   ├── SpeakingCard.js      # Live transcript
│   ├── StatusCard.js        # Action confirmation
│   ├── ArrivalCard.js       # Stop name + walk time
│   ├── MapCard.js           # Mapbox route map
│   ├── InfoCard.js          # Text + optional image
│   └── ImageCard.js         # Full-bleed image + caption
├── styles/
│   └── main.css             # Tailwind base + custom display styles
└── assets/
    ├── lottie/
    │   ├── listening.json
    │   ├── processing.json
    │   └── speaking.json
    └── fonts/               # Brand typeface
```

---

## Display State Machine

```
states:
  IDLE          — presence full width, IdleCard overlay (route/ETA)
  LISTENING     — presence pulses, listening Lottie ring active
  PROCESSING    — presence dims, processing Lottie pulse active
  SPEAKING      — presence audio-reactive, SpeakingCard active
  CONTENT       — presence retreats left, content card fills right two-thirds
  ARRIVAL       — presence minimal, ArrivalCard full width
```

Transitions are driven by WebSocket messages. State machine lives in `state.js` and is the single source of truth — cards and the presence layer subscribe to it.

---

## WebSocket Message Schema

All messages from the Python agent follow this structure:

```json
{ "type": "state", "value": "listening" }
{ "type": "state", "value": "speaking", "transcript": "Heads up, arriving in 3 minutes." }
{ "type": "state", "value": "idle" }
{ "type": "card", "layout": "status", "data": { "message": "Lights dimmed · 72°F" } }
{ "type": "card", "layout": "map", "data": { "stop": "Civic Center", "eta": "3 min", "coords": [37.779, -122.414] } }
{ "type": "card", "layout": "info", "data": { "title": "Next Stop", "body": "Civic Center Station", "image_url": "..." } }
{ "type": "card", "layout": "image", "data": { "url": "...", "caption": "Destination preview" } }
{ "type": "card", "layout": "arrival", "data": { "stop": "Civic Center", "walk_time": "4 min walk" } }
{ "type": "audio_level", "value": 0.72 }
{ "type": "dismiss_card" }
```

`audio_level` messages are sent continuously during TTS playback (0.0–1.0) and drive the presence animation amplitude in real time.

---

## Layout Behavior

### Idle / Speaking state (no card)
```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│                    [Presence animation — full width]            │
│                                                                 │
│  Route: Line 3 · Civic Center          ETA: 4 min  ●●●●●○○○○  │
└─────────────────────────────────────────────────────────────────┘
```

### Content card active
```
┌─────────────────────────────────────────────────────────────────┐
│                    │                                            │
│  [Presence · 30%]  │         [Content card · 70%]              │
│                    │                                            │
└─────────────────────────────────────────────────────────────────┘
```

### Arrival state
```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│              CIVIC CENTER STATION                               │
│              4 min walk · Line 3                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Card Specs

### `IdleCard`
- Route name + line number
- Horizontal progress bar (elapsed / total ride)
- Next stop name
- ETA in minutes
- Always visible in IDLE state as a bottom strip overlay

### `SpeakingCard`
- Live transcript text of current agent speech
- Fades in word by word if possible (use streaming transcript)
- Accessibility-first — readable at distance in vehicle cabin

### `StatusCard`
- Single line confirmation: e.g. `Lights: Dimmed · Temp: 72°F`
- Auto-dismisses after 4 seconds
- Subtle entry animation (slide up from bottom)

### `ArrivalCard`
- Large stop name (dominant type)
- Walk time if available
- Soft full-width background — no presence animation competing

### `MapCard`
- Mapbox GL JS static or interactive map
- Centered on next stop with a pin
- Route line overlay if coords available
- ETA badge top-right

### `InfoCard`
- Title + body text
- Optional right-side image (max 40% width)
- Triggered when Clyde surfaces location or destination info

### `ImageCard`
- Full content-area image, object-fit cover
- Caption overlay bottom-left
- Auto-dismisses after 8 seconds or on next agent turn

---

## Transitions

All card transitions use CSS transitions + JS class toggling. Keep them fast and directional:

- Cards enter from the **right**, exit to the **right**
- Presence layer width animates with `transition: width 400ms ease`
- ArrivalCard fades in full-width (no slide)
- StatusCard slides up from bottom, fades out

No bouncy easing — use `ease` or `ease-out` throughout. The display should feel calm and precise.

---

## Fonts & Color

Design to Glydways brand. Placeholder values:

```css
--color-bg: #0a0a0a;
--color-presence: #1a6fff;   /* agent accent — adjust to brand */
--color-text-primary: #ffffff;
--color-text-secondary: #999999;
--color-card-bg: rgba(255,255,255,0.06);
--font-display: 'Inter', sans-serif;  /* replace with brand font */
```

The display lives in a dark cabin — use dark backgrounds, high contrast text, and avoid pure white large areas that create glare.

---

## Electron Config (`main.js`)

```javascript
const { app, BrowserWindow } = require('electron')

app.whenReady().then(() => {
  const win = new BrowserWindow({
    width: 1080,
    height: 360,
    frame: false,
    fullscreen: false,   // set true for physical display deployment
    backgroundColor: '#0a0a0a',
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  })
  win.loadFile('index.html')
  // win.setKiosk(true)  // uncomment for physical deployment
})
```

For Linux deployment replace Electron with:
```bash
chromium-browser --kiosk --window-size=1080,360 --app=http://localhost:3000
```

---

## Dev Notes

- During development, open `index.html` directly in Chrome at 1080×360 window size — no Electron needed
- Add a `?mock=true` URL param that replays a canned sequence of WebSocket messages for UI testing without the Python agent running
- Mapbox requires an API key — add `MAPBOX_TOKEN` to `.env` and inject via a build step or inline in `index.html` for prototype
