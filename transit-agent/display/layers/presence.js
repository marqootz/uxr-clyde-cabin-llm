/**
 * Presence circle: three states (idle, listening, speaking).
 * Idle: 40px, 40% opacity, no animation.
 * Listening: same size, slow scale pulse 0.92–1.15 (below and above baseline), ~2s ease-in-out.
 * Speaking: amplitude-driven scale (0.9–1.6) + syllable impulse (add 0.3, decay ~120ms); clamp min 0.85, max 2.2.
 * Syllable onsets: non-uniform within word (first syllable gets more time); random jitter per onset so timing is less mechanical.
 * Scale-only animation; opacity set by state (idle 0.4, listening/speaking 1). No color animation during speech.
 *
 * API: setState(state), setAudioNode(analyserNode), setAudioLevel(level), setWordTimestamps(words).
 */
(function () {
  const LISTENING_PERIOD = 2.0;       // seconds for one full pulse
  const LISTENING_SCALE_MIN = 0.92;
  const LISTENING_SCALE_MAX = 1.15;
  /** 1 = instant follow (no smoothing); lower = more lethargic. */
  const AMP_LERP = 1;
  const SYLLABLE_PULSE_DECAY = 0.85;  // per frame (~120ms to near zero at 60fps)
  const SYLLABLE_PULSE_ADD = 0.3;
  const FALLBACK_SYLLABLES_PER_SEC = 4;
  const MIN_SCALE = 0.85;
  const MAX_SCALE = 2.2;
  /** First syllable (accent) gets this fraction of word duration; rest split evenly. */
  const FIRST_SYLLABLE_RATIO = 0.4;
  /** Random jitter (±ms) on each syllable onset so timing feels less mechanical. */
  const SYLLABLE_JITTER_MS = 45;
  const MIN_SYLLABLE_GAP_MS = 25;
  /** Debug: set false to disable amplitude layer in speaking state. */
  const AMPLITUDE_LAYER_ENABLED = true;
  /** Debug: set false to disable syllable pulse layer in speaking state. */
  const SYLLABLE_LAYER_ENABLED = false;

  let frequencyData = null;

  function getRMS(analyserNode) {
    if (!analyserNode) return 0;
    const fftSize = analyserNode.fftSize || 256;
    if (!frequencyData || frequencyData.length !== analyserNode.frequencyBinCount) {
      frequencyData = new Uint8Array(analyserNode.frequencyBinCount);
    }
    analyserNode.getByteFrequencyData(frequencyData);
    let sumSq = 0;
    for (let i = 0; i < frequencyData.length; i++) {
      const n = frequencyData[i] / 255;
      sumSq += n * n;
    }
    return Math.sqrt(sumSq / frequencyData.length);
  }

  function buildSyllableOnsets(words) {
    if (!Array.isArray(words) || words.length === 0) return [];
    const jitterSec = SYLLABLE_JITTER_MS / 1000;
    const minGapSec = MIN_SYLLABLE_GAP_MS / 1000;
    const out = [];
    for (let i = 0; i < words.length; i++) {
      const w = words[i];
      const start = typeof w.start === 'number' ? w.start : 0;
      const end = typeof w.end === 'number' ? w.end : start + 0.2;
      const text = (w.text || '').trim() || ' ';
      const syllables = Math.max(1, Math.floor(text.length / 3));
      const duration = end - start;
      if (syllables === 1) {
        out.push(start);
      } else {
        const firstDuration = duration * FIRST_SYLLABLE_RATIO;
        const remainingDuration = duration - firstDuration;
        let prev = start;
        out.push(start);
        for (let s = 1; s < syllables; s++) {
          let t = start + firstDuration + (remainingDuration * (s - 1)) / (syllables - 1);
          t += (Math.random() - 0.5) * 2 * jitterSec;
          const maxT = s === syllables - 1 ? end : end - minGapSec * (syllables - 1 - s);
          t = Math.max(prev + minGapSec, Math.min(maxT, t));
          out.push(t);
          prev = t;
        }
      }
    }
    out.sort((a, b) => a - b);
    return out;
  }

  class PresenceLayer {
    constructor(el) {
      this.el = el;
      this.state = 'idle';
      this.analyserNode = null;
      this.audioLevel = 0;
      this.currentAmplitudeScale = 1.0;
      this.syllablePulse = 0;
      this.syllableOnsets = [];
      this.syllableOnsetIndex = 0;
      this.speakingStartTime = 0;
      this.fallbackLastPulseTime = 0;
      this.t = 0;
      this._last = null;

      requestAnimationFrame(ts => this._tick(ts));
    }

    setState(state) {
      this.state = state === 'listening' || state === 'speaking' ? state : 'idle';
      if (this.state === 'speaking') {
        this.speakingStartTime = 0;
        this.fallbackLastPulseTime = 0;
      } else {
        this.syllableOnsets = [];
        this.syllableOnsetIndex = 0;
        this.syllablePulse = 0;
      }
    }

    setAudioNode(analyserNode) {
      this.analyserNode = analyserNode || null;
    }

    setAudioLevel(level) {
      this.audioLevel = Math.max(0, Math.min(1, typeof level === 'number' ? level : 0));
    }

    /** words: array of { start, end, text }. Builds syllable onset times for speaking state. */
    setWordTimestamps(words) {
      this.syllableOnsets = buildSyllableOnsets(words || []);
      this.syllableOnsetIndex = 0;
      this.speakingStartTime = performance.now() / 1000; // so elapsed 0 = now (timestamps are 0-based)
    }

    _tick(ts) {
      const dt = this._last != null ? Math.min((ts - this._last) / 1000, 0.05) : 0.016;
      this._last = ts;
      this.t += dt;

      if (this.state === 'speaking') {
        if (this.speakingStartTime === 0) this.speakingStartTime = ts / 1000;
        const elapsed = ts / 1000 - this.speakingStartTime;
        if (SYLLABLE_LAYER_ENABLED) {
          if (this.syllableOnsets.length > 0) {
            while (this.syllableOnsetIndex < this.syllableOnsets.length && elapsed >= this.syllableOnsets[this.syllableOnsetIndex]) {
              this.syllablePulse += SYLLABLE_PULSE_ADD;
              this.syllableOnsetIndex++;
            }
          } else {
            const interval = 1 / FALLBACK_SYLLABLES_PER_SEC;
            if (elapsed - this.fallbackLastPulseTime >= interval) {
              this.syllablePulse += SYLLABLE_PULSE_ADD;
              this.fallbackLastPulseTime = elapsed;
            }
          }
          this.syllablePulse *= SYLLABLE_PULSE_DECAY;
          if (this.syllablePulse < 0.001) this.syllablePulse = 0;
        }

        const targetScale = AMPLITUDE_LAYER_ENABLED
          ? (() => { let level = this.audioLevel; if (this.analyserNode) level = getRMS(this.analyserNode); return 0.9 + level * 0.7; })()
          : 1.0;
        this.currentAmplitudeScale += (targetScale - this.currentAmplitudeScale) * AMP_LERP;
      } else {
        this.currentAmplitudeScale += (1.0 - this.currentAmplitudeScale) * AMP_LERP;
      }

      this._draw();
      requestAnimationFrame(ts => this._tick(ts));
    }

    _draw() {
      const { el, state, t, currentAmplitudeScale, syllablePulse } = this;

      let scale = 1.0;
      let opacity = 0.4;

      if (state === 'idle') {
        scale = 1.0;
        opacity = 0.4;
      } else if (state === 'listening') {
        const progress = (t % LISTENING_PERIOD) / LISTENING_PERIOD;
        let e;
        if (progress < 0.5) {
          const p = progress * 2;
          e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
          e *= 0.5;
        } else {
          const p = (progress - 0.5) * 2;
          e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
          e = 0.5 + 0.5 * e;
        }
        scale = LISTENING_SCALE_MIN + (LISTENING_SCALE_MAX - LISTENING_SCALE_MIN) * e;
        opacity = 1;
      } else if (state === 'speaking') {
        const syllableContrib = SYLLABLE_LAYER_ENABLED ? syllablePulse : 0;
        scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, currentAmplitudeScale + syllableContrib));
        opacity = 1;
      }

      el.style.transform = `scale(${scale.toFixed(4)})`;
      el.style.opacity = String(opacity);
    }
  }

  const el = document.getElementById('presence-circle');
  if (el) {
    window.presenceLayer = new PresenceLayer(el);
  }
})();
