/**
 * WebSocket client for cabin display. Receives layout + data and updates the UI.
 */

const WS_URL = `ws://${location.hostname}:8765`;

let ws = null;
let reconnectTimer = null;

function setConnectionStatus(status, isError) {
  const el = document.getElementById('ws-status');
  if (el) {
    el.textContent = status;
    el.className = 'ws-status' + (isError ? ' error' : '');
  }
}

function connect() {
  setConnectionStatus('Connecting…');
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    console.log('Display WS connected');
    setConnectionStatus('');
    if (reconnectTimer) clearTimeout(reconnectTimer);
  };
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'audio_level') {
        if (window.presenceLayer && typeof msg.value === 'number') {
          window.presenceLayer.setAudioLevel(msg.value);
        }
        return;
      }
      if (msg.type === 'state') {
        window.dispatchEvent(new CustomEvent('display-update', { detail: { layout: msg.value, data: msg.data || {} } }));
        return;
      }
      const { layout, data } = msg;
      window.dispatchEvent(new CustomEvent('display-update', { detail: { layout, data } }));
    } catch (e) {
      console.error('Invalid display message', e);
    }
  };
  ws.onclose = () => {
    console.log('Display WS closed, reconnecting in 3s');
    setConnectionStatus('Disconnected — reconnecting…', true);
    reconnectTimer = setTimeout(connect, 3000);
  };
  ws.onerror = () => {
    setConnectionStatus('Connection failed — check agent is running and reachable', true);
  };
}

connect();
