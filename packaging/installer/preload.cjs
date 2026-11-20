const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('memoInstaller', {
  detect: (options) => ipcRenderer.invoke('memo-installer:detect', options || {}),
  install: (options) => ipcRenderer.invoke('memo-installer:install', options || {}),
  startMemo: (options) => ipcRenderer.invoke('memo-installer:startMemo', options || {}),
  openDashboard: () => ipcRenderer.invoke('memo-installer:openDashboard'),
  openUserRoot: (options) => ipcRenderer.invoke('memo-installer:openUserRoot', options || {}),
  chooseLegacyRoot: () => ipcRenderer.invoke('memo-installer:chooseLegacyRoot'),
  chooseTargetRoot: (options) => ipcRenderer.invoke('memo-installer:chooseTargetRoot', options || {}),
  openSetup: () => ipcRenderer.invoke('memo-installer:openSetup'),
  openCompanion: (options) => ipcRenderer.invoke('memo-installer:openCompanion', options || {}),
  quit: () => ipcRenderer.invoke('memo-installer:quit'),
});
