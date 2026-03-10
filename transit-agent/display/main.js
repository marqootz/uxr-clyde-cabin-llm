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

let expandTransitionEndListener = null;

function expandFeedback(onExpanded) {
  feedbackContent.classList.remove('fade-out');
  if (expandTransitionEndListener) {
    feedbackContent.removeEventListener('transitionend', expandTransitionEndListener);
    expandTransitionEndListener = null;
  }
  document.body.classList.add('feedback-expanding');
  feedbackContent.classList.add('content-pending');
  requestAnimationFrame(() => {
    feedbackContainer.classList.add('expanded');
  });

  expandTransitionEndListener = function onExpandTransitionEnd(e) {
    if (e.target !== feedbackContent) return;
    if (e.propertyName !== 'flex-basis' && e.propertyName !== 'max-width') return;
    document.body.classList.remove('feedback-expanding');
    feedbackContent.classList.remove('content-pending');
    feedbackContent.removeEventListener('transitionend', expandTransitionEndListener);
    expandTransitionEndListener = null;
    if (typeof onExpanded === 'function') onExpanded();
  };
  feedbackContent.addEventListener('transitionend', expandTransitionEndListener);
}
function collapseFeedback() {
  document.body.classList.remove('feedback-expanding');
  feedbackContent.classList.remove('content-pending');
  if (expandTransitionEndListener) {
    feedbackContent.removeEventListener('transitionend', expandTransitionEndListener);
    expandTransitionEndListener = null;
  }
  if (!feedbackContainer.classList.contains('expanded')) return;
  document.body.classList.add('feedback-collapsing');
  feedbackContent.classList.add('fade-out');
  feedbackContainer.classList.remove('expanded');
  function onTransitionEnd(e) {
    if (e.target !== feedbackContent) return;
    if (e.propertyName === 'opacity') feedbackContent.classList.remove('fade-out');
    if (e.propertyName === 'flex-basis' || e.propertyName === 'max-width') {
      document.body.classList.remove('feedback-collapsing');
      feedbackContent.removeEventListener('transitionend', onTransitionEnd);
    }
  }
  feedbackContent.addEventListener('transitionend', onTransitionEnd);
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

/** Transcript scroll: duration from ElevenLabs alignment; fallback WPM when absent. */
const TRANSCRIPT_REVEAL_WORDS_PER_MINUTE = 150;

let transcriptFadeTimer = null;
let transcriptRafId = null;

/** Cancel fade timer and RAF. */
function _clearTranscriptAnimation() {
  if (transcriptFadeTimer != null) {
    clearTimeout(transcriptFadeTimer);
    transcriptFadeTimer = null;
  }
  if (transcriptRafId != null) {
    cancelAnimationFrame(transcriptRafId);
    transcriptRafId = null;
  }
}

/** Reset text block for next utterance. Call after fade-out completes. */
function resetTranscriptScroll() {
  if (!transcriptText) return;
  transcriptText.style.transition = 'none';
  transcriptText.style.transform = 'translateY(0)';
  transcriptText.textContent = '';
}

/** Stop transcript reveal and fade text + gradient out over 400 ms. Reset on completion. */
function cancelTranscriptReveal() {
  _clearTranscriptAnimation();
  if (!transcriptText || transcriptText.style.display === 'none') return;

  transcriptText.style.transition = 'opacity 0.4s ease';
  transcriptText.style.opacity = '0';
  if (transcriptGradient) {
    transcriptGradient.style.transition = 'opacity 0.4s ease';
    transcriptGradient.style.opacity = '0';
  }
  transcriptFadeTimer = setTimeout(() => {
    transcriptFadeTimer = null;
    transcriptText.style.display = 'none';
    transcriptText.style.opacity = '';
    transcriptText.style.transition = '';
    transcriptText.setAttribute('aria-hidden', 'true');
    if (transcriptGradient) {
      transcriptGradient.style.display = 'none';
      transcriptGradient.style.opacity = '';
      transcriptGradient.style.transition = '';
    }
    resetTranscriptScroll();
  }, 450);
}

/**
 * Transcript scroll: text block starts at bottom, scrolls up linearly over duration.
 * Uses CSS transition for GPU-composited motion. Duration from ElevenLabs alignment or WPM fallback.
 * @param {string} text - Full transcript (must be set before calling so textBlockHeight is correct)
 * @param {number} [durationMs] - Speech duration in ms from ElevenLabs alignment
 */
function startTranscriptScroll(text, durationMs) {
  _clearTranscriptAnimation();
  cancelTypeout();
  const s = (text || '').trim();
  if (!s) return;

  const textEl = transcriptText;
  const gradEl = transcriptGradient;
  if (!textEl || !feedbackContent) return;

  textEl.style.transition = 'none';
  textEl.style.opacity = '1';
  if (gradEl) { gradEl.style.transition = 'none'; gradEl.style.opacity = '1'; }

  textEl.textContent = s;
  textEl.style.display = 'block';
  textEl.setAttribute('aria-hidden', 'false');
  if (gradEl) gradEl.style.display = 'block';

  const containerHeight = feedbackContent.getBoundingClientRect().height;
  textEl.getBoundingClientRect();
  const textHeight = textEl.getBoundingClientRect().height;

  const startY = containerHeight;
  const endY = containerHeight - textHeight;

  textEl.style.transform = `translateY(${startY}px)`;
  textEl.getBoundingClientRect();

  const dur = (typeof durationMs === 'number' && durationMs > 0)
    ? durationMs
    : (s.split(/\s+/).filter(Boolean).length / TRANSCRIPT_REVEAL_WORDS_PER_MINUTE) * 60 * 1000;

  const startTime = performance.now();

  function tick(now) {
    const elapsed = now - startTime;
    const progress = dur <= 0 ? 1 : Math.min(elapsed / dur, 1);
    const y = startY + progress * (endY - startY);
    textEl.style.transform = `translateY(${y}px)`;
    if (progress < 1) {
      transcriptRafId = requestAnimationFrame(tick);
    } else {
      transcriptRafId = null;
    }
  }
  transcriptRafId = requestAnimationFrame(tick);
}

/** Build words with timestamps for presence syllable pulse. data.word_timestamps = [{start, end}, ...], text = full sentence. */
function buildWordsWithTimestamps(text, wordTimestamps) {
  const words = (text || '').trim().split(/\s+/).filter(Boolean);
  if (!Array.isArray(wordTimestamps) || wordTimestamps.length !== words.length) return [];
  return words.map((word, i) => ({
    start: wordTimestamps[i].start,
    end: wordTimestamps[i].end,
    text: word,
  }));
}

/** Show the speaking-text section; hide info cards. Uses transcript scroll (gradient + CSS transition). */
function showSpeaking(text, data = {}) {
  setFeedbackMedia(data);
  infoPrimary.style.display = 'none';
  infoSecondary.style.display = 'none';
  const s = (text || '').trim();
  const wordsWithTimes = buildWordsWithTimestamps(s, data.word_timestamps);
  expandFeedback(() => {
    if (s) {
      startTranscriptScroll(s, data.duration_ms);
    }
    window.presenceLayer?.setWordTimestamps(wordsWithTimes);
  });
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

  // Presence circle: idle | listening | speaking
  const presenceState = layout === 'speaking' ? 'speaking' : layout === 'listening' ? 'listening' : 'idle';
  window.presenceLayer?.setState(presenceState);

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
