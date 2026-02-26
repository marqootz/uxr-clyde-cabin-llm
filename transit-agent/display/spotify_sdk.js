/**
 * Load Spotify Web Playback SDK and register this page as a device.
 * Fetches access token from the agent's token server (http://localhost:8766/spotify_token).
 * Requires the agent to be running with Spotify configured.
 */
(function () {
  const TOKEN_URL = 'http://127.0.0.1:8766/spotify_token';

  window.initSpotifyDevice = function initSpotifyDevice(onReady, onError) {
    fetch(TOKEN_URL)
      .then(function (r) {
        if (!r.ok) throw new Error('Token failed: ' + r.status);
        return r.json();
      })
      .then(function (data) {
        if (data.error) throw new Error(data.error);
        const token = data.access_token;
        if (!token) throw new Error('No access_token');
        if (!window.Spotify) {
          const script = document.createElement('script');
          script.src = 'https://sdk.scdn.co/spotify-player.js';
          script.async = true;
          document.head.appendChild(script);
          script.onload = function () { createPlayer(token, onReady, onError); };
        } else {
          createPlayer(token, onReady, onError);
        }
      })
      .catch(function (err) {
        if (onError) onError(err);
        else console.error('Spotify init:', err);
      });
  };

  function createPlayer(token, onReady, onError) {
    const player = new window.Spotify.Player({
      name: 'Clyde Cabin',
      getOAuthToken: function (cb) { cb(token); },
      volume: 0.8
    });
    player.addListener('ready', function (data) {
      console.log('Spotify device ready:', data.device_id);
      if (onReady) onReady(data.device_id);
    });
    player.addListener('not_ready', function () {
      if (onError) onError(new Error('Spotify player not ready'));
    });
    player.addListener('initialization_error', function (e) {
      if (onError) onError(e);
    });
    player.addListener('authentication_error', function (e) {
      if (onError) onError(e);
    });
    player.connect();
  }
})();
