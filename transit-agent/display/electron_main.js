/**
 * Electron main process: 1920×1080 kiosk window for cabin display.
 * Content is 1920×360 anchored to bottom; physical display shows only bottom 360px.
 * Run from display/: electron . (with package.json "main": "electron_main.js")
 */
const { app, BrowserWindow } = require('electron');
const path = require('path');

function createWindow() {
  const win = new BrowserWindow({
    width: 1920,
    height: 1080,
    fullscreen: true,
    kiosk: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  win.loadFile(path.join(__dirname, 'index.html'));
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());
