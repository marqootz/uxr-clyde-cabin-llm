/**
 * Electron main process: 1080×360 kiosk window for cabin display.
 * Run from display/: electron . (with package.json "main": "electron_main.js")
 */
const { app, BrowserWindow } = require('electron');
const path = require('path');

function createWindow() {
  const win = new BrowserWindow({
    width: 1080,
    height: 360,
    fullscreen: true,
    kiosk: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  win.loadFile(path.join(__dirname, 'index.html'));
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());
