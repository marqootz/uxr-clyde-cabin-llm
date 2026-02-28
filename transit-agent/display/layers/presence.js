/**
 * Presence circle: animates #presence-circle (the always-visible button).
 *
 * Idle    : slow sinusoidal scale breathe ±5%, ~3.5 s period; color #793989
 * Speaking: mirrors words — quick grow on consonants, smaller on vowels;
 *           setWord(word) called from typeout drives the pulse
 *
 * Exposes window.presenceLayer with:
 *   setWord(word)      — called from main.js typeout; consonant start = grow, vowel = smaller
 *   setAudioLevel(0–1) — called by ws_client.js when backend sends audio_level
 *   setSpeaking(bool)  — called by main.js layout dispatcher
 */
const VOWELS = new Set('aeiouAEIOU');

class PresenceLayer {
  constructor(el) {
    this.el             = el;
    this.audioLevel     = 0;
    this.smoothedLevel  = 0;
    this.isSpeaking     = false;
    this.wordPulse      = 0;   // 0–1, smoothed; drives scale when speaking
    this.targetWordPulse = 0;
    this.t              = 0;
    this._last          = null;

    requestAnimationFrame(ts => this._tick(ts));
  }

  /** Called when a new word is shown in the typeout. Consonant start = grow, vowel start = smaller. */
  setWord(word) {
    if (typeof word !== 'string' || word.length === 0) return;
    const first = word.charAt(0);
    this.targetWordPulse = VOWELS.has(first) ? 0 : 1;
  }

  /** Called by ws_client.js — keep this name. */
  setAudioLevel(level) {
    this.audioLevel = Math.max(0, Math.min(1, level));
  }

  /** Called by main.js layout dispatcher. */
  setSpeaking(speaking) {
    this.isSpeaking = speaking;
    if (!speaking) this.targetWordPulse = 0;
  }

  _tick(ts) {
    const dt = this._last ? Math.min((ts - this._last) / 1000, 0.05) : 0.016;
    this._last = ts;
    this.t += dt;

    const alpha = this.audioLevel > this.smoothedLevel ? 0.28 : 0.06;
    this.smoothedLevel += (this.audioLevel - this.smoothedLevel) * alpha;

    // Word pulse: fast attack (consonants), slower decay (vowels)
    const wordAlpha = this.targetWordPulse > this.wordPulse ? 0.45 : 0.12;
    this.wordPulse += (this.targetWordPulse - this.wordPulse) * wordAlpha;

    this._draw();
    requestAnimationFrame(ts => this._tick(ts));
  }

  _draw() {
    const { el, t, smoothedLevel, isSpeaking, wordPulse } = this;

    // ── Scale ────────────────────────────────────────────────────────────
    // Idle: slow sine breathe ±5%, ~3.5 s period
    // Speaking: word-driven — quick grow on consonants (wordPulse→1), smaller on vowels (wordPulse→0)
    const scale = isSpeaking
      ? 1.0 + wordPulse * 0.14 + smoothedLevel * 0.20
      : 0.95 + Math.sin(t * 1.8) * 0.05;

    // ── Colour ───────────────────────────────────────────────────────────
    const idleColor  = '#793989';
    const speakColor = '#B851D2';
    const color      = isSpeaking ? speakColor : idleColor;

    // ── Corona glow ──────────────────────────────────────────────────────
    // Speaking: glow follows word pulse (bigger on consonants)
    const glowR = isSpeaking ? Math.round(6 + wordPulse * 14 + smoothedLevel * 18) : 4;
    const glowA = isSpeaking
      ? (0.18 + wordPulse * 0.28 + smoothedLevel * 0.45).toFixed(3)
      : '0.12';

    el.style.transform   = `scale(${scale.toFixed(4)})`;
    el.style.background  = color;
    el.style.boxShadow   = isSpeaking
      ? `0 0 ${glowR}px ${Math.round(glowR / 2)}px rgba(184, 81, 210, ${glowA})`
      : `0 0 ${glowR}px ${Math.round(glowR / 2)}px rgba(121, 57, 137, 0.25)`;
  }
}

// Boot — runs immediately as a plain script (no module required)
(function () {
  const el = document.getElementById('presence-circle');
  if (!el) return;
  window.presenceLayer = new PresenceLayer(el);
}());
