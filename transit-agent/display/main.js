/**
 * Display controller: three-panel layout dispatcher.
 *
 * CENTER panel always shows ride progress — it is never replaced or covered.
 * RIGHT panel slides in from the right to show agent responses (speaking text,
 * info cards). It slides back off to the right when no longer needed, restoring
 * the center panel to its original width.
 *
 * Events consumed (dispatched by ws_client.js):
 *   display-update  { layout: 'idle'|'speaking'|'status'|'arrival', data: {} }
 *
 */

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatEta(seconds) {
  if (seconds == null || seconds < 0) return '—';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}m ${s}s` : `${m} min`;
}

// ─── Ride progress (center — always on) ──────────────────────────────────────

function updateRideProgress({ next_stop, eta_seconds, progress_pct } = {}) {
  document.getElementById('next-stop').textContent  = next_stop  || '—';
  document.getElementById('eta-badge').textContent  = formatEta(eta_seconds);

  const pct = progress_pct != null ? Math.max(0, Math.min(100, progress_pct)) : 0;
  document.getElementById('progress-track').style.setProperty('--pct', pct / 100);
}

// ─── Feedback container (presence circle + response content) ───────────────────

const feedbackContainer  = document.getElementById('feedback-container');
const feedbackContent    = document.getElementById('feedback-content');
const feedbackMedia      = document.getElementById('feedback-media');
const transcriptText     = document.getElementById('transcript-reveal-text');
const transcriptGradient = document.getElementById('text-reveal-gradient');
const infoPrimary        = document.getElementById('info-card-primary');
const infoSecondary      = document.getElementById('info-card-secondary');

function expandFeedback() {
  feedbackContent.classList.remove('fade-out');
  feedbackContainer.classList.add('expanded');
}
function collapseFeedback() {
  if (!feedbackContainer.classList.contains('expanded')) return;
  feedbackContent.classList.add('fade-out');
  function onFadeOut(e) {
    if (e.propertyName !== 'opacity') return;
    feedbackContainer.classList.remove('expanded');
    feedbackContent.classList.remove('fade-out');
  }
  feedbackContent.addEventListener('transitionend', onFadeOut, { once: true });
}

function setFeedbackMedia({ image_url, video_url } = {}) {
  feedbackMedia.innerHTML = '';
  if (video_url) {
    const v = document.createElement('video');
    v.src = video_url;
    v.controls = true;
    v.playsInline = true;
    feedbackMedia.appendChild(v);
  } else if (image_url) {
    const img = document.createElement('img');
    img.src = image_url;
    img.alt = '';
    feedbackMedia.appendChild(img);
  }
}

let typeoutTimer = null;

function cancelTypeout() {
  if (typeoutTimer !== null) {
    clearInterval(typeoutTimer);
    typeoutTimer = null;
  }
}

/** Transcript reveal: scroll speed (match TTS). Optional word timestamps from TTS for precise sync. */
const TRANSCRIPT_REVEAL_WORDS_PER_MINUTE = 150;
const TRANSCRIPT_REVEAL_WINDOW_BOTTOM_PCT = 0.884;  /* 88.4% — first line enters here */
const TRANSCRIPT_REVEAL_LINE_HEIGHT_PX = 24 * 1.6;

let transcriptRevealRafId = null;
let transcriptFadeTimer   = null;

/** Cancel RAF + fade timer without touching visibility (used before starting a new reveal). */
function _clearTranscriptAnimation() {
  if (transcriptRevealRafId != null) { cancelAnimationFrame(transcriptRevealRafId); transcriptRevealRafId = null; }
  if (transcriptFadeTimer   != null) { clearTimeout(transcriptFadeTimer);            transcriptFadeTimer   = null; }
}

/** Stop transcript reveal and fade text + gradient out over 400 ms. */
function cancelTranscriptReveal() {
  _clearTranscriptAnimation();
  if (!transcriptText || transcriptText.style.display === 'none') return;

  transcriptText.style.transition = 'opacity 0.4s ease';
  transcriptText.style.opacity    = '0';
  if (transcriptGradient) {
    transcriptGradient.style.transition = 'opacity 0.4s ease';
    transcriptGradient.style.opacity    = '0';
  }
  transcriptFadeTimer = setTimeout(() => {
    transcriptFadeTimer = null;
    transcriptText.style.display    = 'none';
    transcriptText.style.opacity    = '';
    transcriptText.style.transition = '';
    transcriptText.setAttribute('aria-hidden', 'true');
    if (transcriptGradient) {
      transcriptGradient.style.display    = 'none';
      transcriptGradient.style.opacity    = '';
      transcriptGradient.style.transition = '';
    }
  }, 400);
}

/**
 * Transcript reveal: full block scrolls up through a fixed gradient window.
 * @param {string} text - Full transcript
 * @param {{ wordTimestamps?: Array<{ start: number, end: number }> }} [options] - Optional TTS word timestamps (seconds) for precise scroll
 */
function startTranscriptReveal(text, options = {}) {
  _clearTranscriptAnimation();  // stop animation + cancel any in-progress fade
  cancelTypeout();
  const s = (text || '').trim();
  if (!s) return;

  const textEl = transcriptText;
  const gradEl = transcriptGradient;
  if (!textEl || !feedbackContent) return;

  // Reset opacity immediately (cancels any in-progress fade)
  textEl.style.transition = 'none';
  textEl.style.opacity    = '1';
  if (gradEl) { gradEl.style.transition = 'none'; gradEl.style.opacity = '1'; }

  textEl.textContent = s;
  textEl.style.display = 'block';
  textEl.setAttribute('aria-hidden', 'false');
  if (gradEl) gradEl.style.display = 'block';

  const wordCount = s.split(/\s+/).filter(Boolean).length;
  const wordTimestamps = options.wordTimestamps;

  const H = feedbackContent.clientHeight || 360;
  const initialY = TRANSCRIPT_REVEAL_WINDOW_BOTTOM_PCT * H - TRANSCRIPT_REVEAL_LINE_HEIGHT_PX;
  textEl.style.transform = `translateY(${initialY}px)`;
  textEl.offsetHeight;

  const textHeight = textEl.offsetHeight;

  // Align last line bottom with progress bar bottom, measured in feedbackContent-local coords.
  // feedbackContent starts 22px from viewport top (feedback-container padding);
  // progress bar bottom is 24px from viewport bottom — so the target differs from H by that delta.
  const feedbackTop     = feedbackContent.getBoundingClientRect().top;
  const progressTrackEl = document.getElementById('progress-track');
  const progressBottom  = progressTrackEl
    ? progressTrackEl.getBoundingClientRect().bottom
    : feedbackTop + H;
  const finalY = (progressBottom - feedbackTop) - textHeight;

  let durationMs;
  if (Array.isArray(wordTimestamps) && wordTimestamps.length > 0) {
    const first = wordTimestamps[0];
    const last = wordTimestamps[wordTimestamps.length - 1];
    if (typeof first === 'object' && first != null && typeof last === 'object' && last != null && 'start' in first && 'end' in last) {
      durationMs = (last.end - first.start) * 1000;
    } else {
      durationMs = (wordCount / TRANSCRIPT_REVEAL_WORDS_PER_MINUTE) * 60 * 1000;
    }
  } else {
    durationMs = (wordCount / TRANSCRIPT_REVEAL_WORDS_PER_MINUTE) * 60 * 1000;
  }

  const startTime = performance.now();

  function tick(now) {
    const elapsed  = now - startTime;
    const progress = durationMs <= 0 ? 1 : Math.min(elapsed / durationMs, 1);
    const eased    = 1 - Math.pow(1 - progress, 2);  // quadratic ease-out (softer than cubic)
    const y        = initialY + eased * (finalY - initialY);
    textEl.style.transform = `translateY(${y}px)`;
    if (progress < 1) {
      transcriptRevealRafId = requestAnimationFrame(tick);
    } else {
      transcriptRevealRafId = null;
    }
  }

  transcriptRevealRafId = requestAnimationFrame(tick);
}

/** Show the speaking-text section; hide info cards. Uses transcript reveal (gradient + scroll). */
function showSpeaking(text, data = {}) {
  setFeedbackMedia(data);
  infoPrimary.style.display   = 'none';
  infoSecondary.style.display = 'none';
  expandFeedback();
  const s = (text || '').trim();
  if (s) startTranscriptReveal(s, { wordTimestamps: data.word_timestamps });
}

/** Show info card(s); hide speaking text. Optional image/video in data. */
function showInfoCard({ label, value, detail, walk_time, image_url, video_url } = {}) {
  setFeedbackMedia({ image_url, video_url });
  cancelTypeout();
  cancelTranscriptReveal();

  if (value != null) {
    document.getElementById('info-label').textContent  = label  || 'Info';
    document.getElementById('info-value').textContent  = value  || '—';
    document.getElementById('info-detail').textContent = detail || '';
    infoPrimary.style.display = 'block';
  } else {
    infoPrimary.style.display = 'none';
  }

  if (walk_time != null) {
    document.getElementById('info-walk').textContent = `~${walk_time} min`;
    infoSecondary.style.display = 'block';
  } else {
    infoSecondary.style.display = 'none';
  }

  expandFeedback();
}

// ─── Dismiss: collapse feedback (presence circle stays visible) ───────────────

document.getElementById('presence-circle').addEventListener('click', () => {
  collapseFeedback();
});

// ─── Display-update dispatcher ───────────────────────────────────────────────

window.addEventListener('display-update', (e) => {
  const { layout, data = {} } = e.detail;

  // Keep presence circle aware of speaking state
  window.presenceLayer?.setSpeaking(layout === 'speaking');

  // Always refresh ride progress when the backend includes it
  if (data.next_stop != null || data.progress_pct != null) {
    updateRideProgress(data);
  }

  switch (layout) {

    case 'idle':
      cancelTypeout();
      cancelTranscriptReveal();
      collapseFeedback();
      break;

    case 'speaking':
      // Agent is speaking — expand feedback container with transcript (and optional media)
      showSpeaking(data.text || '', data);
      break;

    case 'status':
      // Tool result — expand feedback with info card (and optional media)
      showInfoCard({
        label:     data.title  || 'Status',
        value:     data.value  || data.detail || '—',
        detail:    data.detail || '',
        image_url: data.image_url,
        video_url: data.video_url,
      });
      break;

    case 'arrival':
      // Upcoming stop — expand feedback with arrival card
      showInfoCard({
        label:     'Next Stop',
        value:     data.stop_name || '—',
        walk_time: data.walk_time ?? null,
        image_url: data.image_url,
        video_url: data.video_url,
      });
      break;
  }
});

// ─── Initial state ────────────────────────────────────────────────────────────

updateRideProgress({ next_stop: '—', eta_seconds: null, progress_pct: 0 });
