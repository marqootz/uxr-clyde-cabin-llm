/**
 * Presence circle: animates #presence-circle (the always-visible white button).
 *
 * Idle    : slow sinusoidal scale breathe ±2%, ~3.5 s period; soft white glow
 * Speaking: scale pulses with audio level (up to +10%); shifts to pale violet;
 *           corona glow grows with audio level
 *
 * Exposes window.presenceLayer with:
 *   setAudioLevel(0–1)  — called directly by ws_client.js
 *   setSpeaking(bool)   — called by main.js layout dispatcher
 */
class PresenceLayer {
  constructor(el) {
    this.el            = el;
    this.audioLevel    = 0;
    this.smoothedLevel = 0;
    this.isSpeaking    = false;
    this.t             = 0;
    this._last         = null;

    requestAnimationFrame(ts => this._tick(ts));
  }

  /** Called by ws_client.js — keep this name. */
  setAudioLevel(level) {
    this.audioLevel = Math.max(0, Math.min(1, level));
  }

  /** Called by main.js layout dispatcher. */
  setSpeaking(speaking) {
    this.isSpeaking = speaking;
  }

  _tick(ts) {
    const dt = this._last ? Math.min((ts - this._last) / 1000, 0.05) : 0.016;
    this._last = ts;
    this.t += dt;

    // Fast attack, slow decay
    const alpha = this.audioLevel > this.smoothedLevel ? 0.28 : 0.06;
    this.smoothedLevel += (this.audioLevel - this.smoothedLevel) * alpha;

    this._draw();
    requestAnimationFrame(ts => this._tick(ts));
  }

  _draw() {
    const { el, t, smoothedLevel, isSpeaking } = this;

    // ── Scale ────────────────────────────────────────────────────────────
    // Idle: sine breathe ±2%, ω=1.8 rad/s (~3.5 s period)
    // Speaking: audio pushes up to +10%
    const scale = isSpeaking
      ? 1.0 + smoothedLevel * 0.10
      : 0.98 + Math.sin(t * 1.8) * 0.02;

    // ── Colour ───────────────────────────────────────────────────────────
    // Idle: near-white (hue 220, sat 10%) → Speaking: pale violet (hue 270, sat 55%)
    const hue = isSpeaking ? 270 : 220;
    const sat = isSpeaking ?  55 :  10;
    const lit = isSpeaking ?  88 :  98;

    // ── Corona glow ──────────────────────────────────────────────────────
    const glowR = isSpeaking ? Math.round(4 + smoothedLevel * 18) : 4;
    const glowA = isSpeaking
      ? (0.12 + smoothedLevel * 0.45).toFixed(3)
      : '0.12';

    el.style.transform  = `scale(${scale.toFixed(4)})`;
    el.style.background = `hsl(${hue}, ${sat}%, ${lit}%)`;
    el.style.boxShadow  = `0 0 ${glowR}px ${Math.round(glowR / 2)}px hsla(${hue}, ${sat + 20}%, 70%, ${glowA})`;
  }
}

// Boot — runs immediately as a plain script (no module required)
(function () {
  const el = document.getElementById('presence-circle');
  if (!el) return;
  window.presenceLayer = new PresenceLayer(el);
}());
