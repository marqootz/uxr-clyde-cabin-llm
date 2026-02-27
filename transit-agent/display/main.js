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

function updateRideProgress({ route_name, next_stop, eta_seconds, progress_pct } = {}) {
  document.getElementById('route-name').textContent = route_name || '—';
  document.getElementById('next-stop').textContent  = next_stop  || '—';
  document.getElementById('eta-badge').textContent  = formatEta(eta_seconds);

  const pct = progress_pct != null ? Math.max(0, Math.min(100, progress_pct)) : 0;
  document.getElementById('progress-fill').style.width = `${pct}%`;
  document.getElementById('progress-knob').style.setProperty('--pct', pct / 100);
}

// ─── Feedback container (presence circle + response content) ───────────────────

const feedbackContainer = document.getElementById('feedback-container');
const feedbackMedia     = document.getElementById('feedback-media');
const infoSpeaking      = document.getElementById('info-speaking');
const infoPrimary       = document.getElementById('info-card-primary');
const infoSecondary     = document.getElementById('info-card-secondary');

function expandFeedback() { feedbackContainer.classList.add('expanded'); }
function collapseFeedback() { feedbackContainer.classList.remove('expanded'); }

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

function startTypeout(text) {
  cancelTypeout();
  const p = document.getElementById('info-speaking-p');
  if (!p) return;
  const words = (text || '').trim().split(/\s+/).filter(Boolean);
  p.textContent = '';
  if (!words.length) return;
  p.textContent = words[0];
  let i = 1;
  const stepMs = 200;
  typeoutTimer = setInterval(() => {
    if (i >= words.length) {
      cancelTypeout();
      return;
    }
    p.textContent += ' ' + words[i];
    i += 1;
  }, stepMs);
}

/** Show the speaking-text section; hide info cards. Optional image/video in data. */
function showSpeaking(text, data = {}) {
  setFeedbackMedia(data);
  infoPrimary.style.display   = 'none';
  infoSecondary.style.display = 'none';
  expandFeedback();
  infoSpeaking.style.display = 'block';
  const p = document.getElementById('info-speaking-p');
  if (p) {
    const s = (text || '').trim();
    p.textContent = s;
    if (s) startTypeout(s);
  }
}

/** Show info card(s); hide speaking text. Optional image/video in data. */
function showInfoCard({ label, value, detail, walk_time, image_url, video_url } = {}) {
  setFeedbackMedia({ image_url, video_url });
  cancelTypeout();
  infoSpeaking.style.display = 'none';

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
  if (data.route_name != null || data.next_stop != null || data.progress_pct != null) {
    updateRideProgress(data);
  }

  switch (layout) {

    case 'idle':
      // Center stays as-is; feedback container collapses (circle stays visible)
      cancelTypeout();
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

updateRideProgress({ route_name: '—', next_stop: '—', eta_seconds: null, progress_pct: 0 });
