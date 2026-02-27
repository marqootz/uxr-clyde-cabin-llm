/**
 * State overlays for listening/processing. CSS placeholders until Lottie assets are added.
 * Listens for 'display-update'; shows listening/processing only when layout implies them (future: backend can send state).
 */
(function () {
  const container = document.getElementById('lottie-layer');
  if (!container) return;

  const stateEl = document.createElement('div');
  stateEl.className = 'lottie-state';
  stateEl.setAttribute('aria-hidden', 'true');
  container.appendChild(stateEl);

  function setState(layout) {
    // Backend currently only sends layout (idle, speaking, status, arrival). No listening/processing yet.
    // When backend sends state: listening | processing, we can show the ring/pulse here.
    const show = layout === 'listening' || layout === 'processing';
    stateEl.classList.toggle('listening', layout === 'listening');
    stateEl.classList.toggle('processing', layout === 'processing');
    stateEl.classList.toggle('active', show);
  }

  window.addEventListener('display-update', (e) => {
    const layout = e.detail?.layout ?? 'idle';
    setState(layout);
  });
  setState('idle');
})();
