# Agent Presence Animation — `display/layers/presence.js`

## Purpose

The ambient visual that represents Clyde on the 1080×360 display. Always visible. Responds to agent state and real-time TTS audio amplitude. When a content card is active it retreats to the left third of the display.

---

## Design Intent

A fluid, horizontal waveform — calm when idle, responsive when speaking. Feels like the vehicle has a presence rather than a screen showing a UI. Minimal, dark, slightly luminous. No literal faces, avatars, or icons.

States:
- **Idle** — slow, low-amplitude breathing wave. Soft glow.
- **Listening** — slightly more active, warm color shift, subtle pulse
- **Processing** — wave pauses, shimmer/scan effect left to right
- **Speaking** — fully audio-reactive, amplitude drives wave height in real time
- **Retreated** — compressed to left 30% of display, dims to 40% opacity

---

## Implementation

```javascript
// display/layers/presence.js
// Three.js audio-reactive waveform for Clyde presence layer

import * as THREE from 'three'

export class PresenceLayer {
  constructor(container) {
    this.container = container
    this.audioLevel = 0      // 0.0 – 1.0, set externally from ws_client.js
    this.state = 'idle'
    this.targetWidth = 1.0   // 1.0 = full width, 0.3 = retreated
    this.currentWidth = 1.0

    this._initRenderer()
    this._initScene()
    this._initWave()
    this._animate()
  }

  // --- Setup ---

  _initRenderer() {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    this.renderer.setPixelRatio(window.devicePixelRatio)
    this.renderer.setSize(window.innerWidth, window.innerHeight)
    this.renderer.setClearColor(0x000000, 0)
    this.container.appendChild(this.renderer.domElement)

    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10)
    this.camera.position.z = 1

    this.scene = new THREE.Scene()
  }

  _initScene() {
    // Clock for animation time uniform
    this.clock = new THREE.Clock()
  }

  _initWave() {
    // Wave rendered as a line of vertices driven by a GLSL shader
    const segmentCount = 256
    const geometry = new THREE.BufferGeometry()
    const positions = new Float32Array((segmentCount + 1) * 3)

    for (let i = 0; i <= segmentCount; i++) {
      positions[i * 3] = (i / segmentCount) * 2 - 1  // x: -1 to 1
      positions[i * 3 + 1] = 0                        // y: driven by shader
      positions[i * 3 + 2] = 0
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))

    this.waveUniforms = {
      uTime:       { value: 0.0 },
      uAmplitude:  { value: 0.0 },
      uState:      { value: 0.0 },   // 0=idle, 1=listening, 2=processing, 3=speaking
      uColor:      { value: new THREE.Color(0x1a6fff) },
      uWidth:      { value: 1.0 },   // 0.3–1.0 for retreated/full
    }

    const material = new THREE.ShaderMaterial({
      uniforms: this.waveUniforms,
      vertexShader: WAVE_VERT,
      fragmentShader: WAVE_FRAG,
      transparent: true,
    })

    this.waveLine = new THREE.Line(geometry, material)
    this.scene.add(this.waveLine)

    // Secondary glow line (same geometry, blurred via opacity)
    const glowMaterial = material.clone()
    glowMaterial.uniforms = { ...this.waveUniforms }
    glowMaterial.uniforms.uAmplitude = this.waveUniforms.uAmplitude  // shared ref
    this.glowLine = new THREE.Line(geometry.clone(), glowMaterial)
    this.glowLine.scale.y = 1.4
    this.scene.add(this.glowLine)
  }

  // --- Animation loop ---

  _animate() {
    requestAnimationFrame(() => this._animate())

    const elapsed = this.clock.getElapsedTime()

    // Smooth audio level
    this.waveUniforms.uTime.value = elapsed

    // Lerp amplitude toward target audio level
    const targetAmplitude = this._targetAmplitude()
    this.waveUniforms.uAmplitude.value = THREE.MathUtils.lerp(
      this.waveUniforms.uAmplitude.value,
      targetAmplitude,
      0.12
    )

    // Lerp width for retreat/expand
    this.currentWidth = THREE.MathUtils.lerp(this.currentWidth, this.targetWidth, 0.08)
    this.waveUniforms.uWidth.value = this.currentWidth

    // State uniform
    this.waveUniforms.uState.value = this._stateValue()

    this.renderer.render(this.scene, this.camera)
  }

  _targetAmplitude() {
    switch (this.state) {
      case 'idle':       return 0.04 + Math.sin(Date.now() * 0.001) * 0.01  // slow breath
      case 'listening':  return 0.08
      case 'processing': return 0.02
      case 'speaking':   return 0.05 + this.audioLevel * 0.35
      default:           return 0.04
    }
  }

  _stateValue() {
    return { idle: 0, listening: 1, processing: 2, speaking: 3 }[this.state] ?? 0
  }

  // --- Public API ---

  setState(state) {
    this.state = state
    this.targetWidth = state === 'content' ? 0.3 : 1.0

    // Color shifts by state
    const colors = {
      idle:       0x1a6fff,
      listening:  0x3d9eff,
      processing: 0x8855ff,
      speaking:   0x1a6fff,
      content:    0x1a4aaa,
    }
    this.waveUniforms.uColor.value.set(colors[state] ?? 0x1a6fff)
  }

  setAudioLevel(level) {
    // Called from ws_client.js on each audio_level message
    this.audioLevel = Math.max(0, Math.min(1, level))
  }

  resize() {
    this.renderer.setSize(window.innerWidth, window.innerHeight)
  }
}

// --- GLSL Shaders ---

const WAVE_VERT = `
  uniform float uTime;
  uniform float uAmplitude;
  uniform float uState;
  uniform float uWidth;

  void main() {
    vec3 pos = position;

    // Constrain x to current width (retreat effect)
    float xNorm = (pos.x + 1.0) * 0.5;         // 0–1
    float xScaled = xNorm * uWidth * 2.0 - 1.0; // remap to -1 to (uWidth*2-1)

    // Multi-frequency wave
    float y = 0.0;
    y += sin(xScaled * 6.28 * 2.0 + uTime * 1.8) * uAmplitude * 0.6;
    y += sin(xScaled * 6.28 * 5.0 + uTime * 2.4) * uAmplitude * 0.3;
    y += sin(xScaled * 6.28 * 1.0 + uTime * 0.9) * uAmplitude * 0.5;

    // Processing state: scan shimmer
    if (uState > 1.5 && uState < 2.5) {
      float scanPos = mod(uTime * 0.6, 1.0);
      float scanEffect = exp(-pow((xNorm - scanPos) * 8.0, 2.0));
      y += scanEffect * 0.06;
    }

    pos.x = xScaled;
    pos.y = y;

    gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
  }
`

const WAVE_FRAG = `
  uniform vec3 uColor;
  uniform float uAmplitude;

  void main() {
    float alpha = 0.85 + uAmplitude * 0.5;
    gl_FragColor = vec4(uColor, clamp(alpha, 0.4, 1.0));
  }
`
```

---

## Lottie State Controller — `display/layers/lottie_states.js`

Manages state-specific Lottie overlay animations (listening ring, processing pulse). These layer on top of the Three.js wave for moments that need a more intentional visual cue.

```javascript
// display/layers/lottie_states.js
import lottie from 'lottie-web'

const ANIMATIONS = {
  listening:  '/assets/lottie/listening.json',
  processing: '/assets/lottie/processing.json',
}

export class LottieStateController {
  constructor(container) {
    this.container = container
    this.current = null
    this.instance = null
  }

  setState(state) {
    if (state === this.current) return
    this.current = state

    if (this.instance) {
      this.instance.destroy()
      this.instance = null
    }

    if (ANIMATIONS[state]) {
      this.instance = lottie.loadAnimation({
        container: this.container,
        renderer: 'svg',
        loop: true,
        autoplay: true,
        path: ANIMATIONS[state],
      })
    }
  }

  clear() {
    this.setState(null)
  }
}
```

**Lottie asset guidance:**
- `listening.json` — a soft pulsing ring or arc, centered, suggests openness/receiving
- `processing.json` — a minimal rotating arc or dot sequence, suggests thinking
- Keep both monochromatic and use the brand accent color in the Lottie file
- Source from LottieFiles.com or author in After Effects / Rive

---

## WebSocket Integration — `display/ws_client.js`

Wires incoming messages to the presence layer and card manager:

```javascript
import { PresenceLayer } from './layers/presence.js'
import { LottieStateController } from './layers/lottie_states.js'
import { CardManager } from './cards/card_manager.js'
import { displayState } from './state.js'

const WS_URL = 'ws://127.0.0.1:8765'

const presenceContainer = document.getElementById('presence-layer')
const lottieContainer = document.getElementById('lottie-layer')
const cardContainer = document.getElementById('card-layer')

const presence = new PresenceLayer(presenceContainer)
const lottie = new LottieStateController(lottieContainer)
const cards = new CardManager(cardContainer)

function connect() {
  const ws = new WebSocket(WS_URL)

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data)

    if (msg.type === 'state') {
      displayState.set(msg.value)
      presence.setState(msg.value)
      lottie.setState(msg.value)

      if (msg.value === 'speaking' && msg.transcript) {
        cards.show('speaking', { transcript: msg.transcript })
      } else if (msg.value === 'idle') {
        cards.dismiss()
      }
    }

    if (msg.type === 'card') {
      presence.setState('content')
      lottie.clear()
      cards.show(msg.layout, msg.data)
    }

    if (msg.type === 'dismiss_card') {
      cards.dismiss()
      presence.setState(displayState.get())
    }

    if (msg.type === 'audio_level') {
      presence.setAudioLevel(msg.value)
    }
  }

  ws.onclose = () => setTimeout(connect, 2000)  // auto-reconnect
  ws.onerror = () => ws.close()
}

connect()
window.addEventListener('resize', () => presence.resize())
```

---

## `index.html` Structure

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Clyde Display</title>
  <link rel="stylesheet" href="styles/main.css">
</head>
<body>
  <!-- Layer order: presence behind, cards in front -->
  <div id="presence-layer"></div>   <!-- Three.js canvas -->
  <div id="lottie-layer"></div>     <!-- Lottie SVG overlays -->
  <div id="card-layer"></div>       <!-- HTML content cards -->

  <script type="module" src="ws_client.js"></script>
</body>
</html>
```

```css
/* styles/main.css */
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  width: 1080px;
  height: 360px;
  overflow: hidden;
  background: #0a0a0a;
  font-family: 'Inter', sans-serif;
  color: #ffffff;
}

#presence-layer {
  position: absolute;
  inset: 0;
  z-index: 1;
}

#lottie-layer {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  display: flex;
  align-items: center;
  justify-content: center;
}

#card-layer {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
}
```

---

## Python — Sending Audio Level During TTS

In `agent/audio_output.py`, emit amplitude values over WebSocket during playback so the presence animation is audio-reactive:

```python
async def _stream_and_play(text: str, ws_broadcast) -> None:
    # ... existing stream/play logic ...

    # During playback, sample amplitude and broadcast
    async def _emit_levels():
        while _is_speaking:
            level = _get_current_amplitude()   # sample sounddevice output stream
            await ws_broadcast({ "type": "audio_level", "value": level })
            await asyncio.sleep(0.033)         # ~30fps

    asyncio.create_task(_emit_levels())
```

---

## File Placement

```
display/
├── index.html
├── main.js
├── ws_client.js
├── state.js
├── layers/
│   ├── presence.js
│   └── lottie_states.js
├── cards/
│   └── card_manager.js
├── styles/
│   └── main.css
└── assets/
    └── lottie/
        ├── listening.json
        └── processing.json
```
