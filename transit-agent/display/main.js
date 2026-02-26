/**
 * Display controller: listens for layout updates and renders idle | speaking | status | arrival.
 */

const LAYOUTS = ['idle', 'speaking', 'status', 'arrival'];
const root = document.getElementById('root');

function showLayout(layout, data = {}) {
  LAYOUTS.forEach(id => {
    const el = document.getElementById(`layout-${id}`);
    if (el) el.classList.toggle('active', id === layout);
  });

  switch (layout) {
    case 'idle':
      document.getElementById('idle-route').textContent = data.route_name || '—';
      document.getElementById('idle-next-stop').textContent = data.next_stop || '—';
      document.getElementById('idle-eta').textContent = formatEta(data.eta_seconds);
      document.getElementById('idle-progress').style.width = data.progress_pct != null ? `${data.progress_pct}%` : '0%';
      break;
    case 'speaking':
      document.getElementById('speaking-text').textContent = data.text || '';
      break;
    case 'status':
      document.getElementById('status-title').textContent = data.title || 'Done';
      document.getElementById('status-detail').textContent = data.detail || '';
      break;
    case 'arrival':
      document.getElementById('arrival-stop').textContent = data.stop_name || '—';
      document.getElementById('arrival-walk').textContent = data.walk_time != null ? `~${data.walk_time} min walk` : '';
      break;
    default:
      break;
  }
}

function formatEta(seconds) {
  if (seconds == null || seconds < 0) return '—';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}m ${s}s` : `${m} min`;
}

window.addEventListener('display-update', (e) => {
  const { layout, data } = e.detail;
  showLayout(layout, data);
});

// Default to idle with placeholder data
showLayout('idle', { route_name: '—', next_stop: '—', eta_seconds: null, progress_pct: 0 });
