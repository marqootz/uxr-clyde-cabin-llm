/**
 * WebSocket client for cabin display. Receives layout + data and updates the UI.
 */

const WS_URL = `ws://${location.hostname}:8765`;

let ws = null;
let reconnectTimer = null;

function connect() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    console.log('Display WS connected');
    if (reconnectTimer) clearTimeout(reconnectTimer);
  };
  ws.onmessage = (event) => {
    try {
      const { layout, data } = JSON.parse(event.data);
      window.dispatchEvent(new CustomEvent('display-update', { detail: { layout, data } }));
    } catch (e) {
      console.error('Invalid display message', e);
    }
  };
  ws.onclose = () => {
    console.log('Display WS closed, reconnecting in 3s');
    reconnectTimer = setTimeout(connect, 3000);
  };
  ws.onerror = () => {};
}

connect();
