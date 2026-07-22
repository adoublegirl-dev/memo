const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('memoCompanion', {
  getSnapshot: () => ipcRenderer.invoke('memo:getSnapshot'),
  openDashboard: (hash) => ipcRenderer.invoke('memo:openDashboard', hash),
  hideWindow: () => ipcRenderer.invoke('memo:hideWindow'),
  startServices: () => ipcRenderer.invoke('memo:startServices'),
  stopServices: () => ipcRenderer.invoke('memo:stopServices'),
  restartServices: () => ipcRenderer.invoke('memo:restartServices'),
  setLoginItemEnabled: (enabled) => ipcRenderer.invoke('memo:setLoginItemEnabled', enabled),
  setSettingsExpanded: (expanded) => ipcRenderer.invoke('memo:setSettingsExpanded', expanded),
  onSnapshot: (callback) => {
    const listener = (_event, snapshot) => callback(snapshot);
    ipcRenderer.on('memo:snapshot', listener);
    return () => ipcRenderer.removeListener('memo:snapshot', listener);
  },
});
