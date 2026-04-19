"use strict";
const electron = require("electron");
const invoke = (channel, ...args) => electron.ipcRenderer.invoke(channel, ...args);
const on = (channel, fn) => {
  const listener = (_, ...args) => fn(...args);
  electron.ipcRenderer.on(channel, listener);
  return () => electron.ipcRenderer.removeListener(channel, listener);
};
electron.contextBridge.exposeInMainWorld("kendrAPI", {
  // Window
  window: {
    minimize: () => invoke("window:minimize"),
    maximize: () => invoke("window:maximize"),
    close: () => invoke("window:close"),
    isMaximized: () => invoke("window:isMaximized")
  },
  // Settings
  settings: {
    get: (key) => invoke("settings:get", key),
    set: (key, value) => invoke("settings:set", key, value),
    getAll: () => invoke("settings:getAll")
  },
  // Backend
  backend: {
    status: () => invoke("backend:status"),
    start: () => invoke("backend:start"),
    stop: () => invoke("backend:stop"),
    restart: () => invoke("backend:restart"),
    getLogs: () => invoke("backend:getLogs"),
    /** Subscribe to live status pushes from the main process. Returns unsubscribe fn. */
    onStatusChange: (fn) => on("backend:status-push", fn)
  },
  updates: {
    status: () => invoke("updates:status"),
    check: () => invoke("updates:check"),
    download: () => invoke("updates:download"),
    install: () => invoke("updates:install"),
    onStatusChange: (fn) => on("updates:status-push", fn)
  },
  // File system
  fs: {
    readDir: (path) => invoke("fs:readDir", path),
    readFile: (path) => invoke("fs:readFile", path),
    writeFile: (path, content) => invoke("fs:writeFile", path, content),
    createFile: (path) => invoke("fs:createFile", path),
    createDir: (path) => invoke("fs:createDir", path),
    delete: (path) => invoke("fs:delete", path),
    rename: (oldPath, newPath) => invoke("fs:rename", oldPath, newPath),
    exists: (path) => invoke("fs:exists", path),
    stat: (path) => invoke("fs:stat", path)
  },
  // Dialog
  dialog: {
    openDirectory: () => invoke("dialog:openDirectory"),
    openFile: (filters) => invoke("dialog:openFile", filters),
    openFiles: (filters) => invoke("dialog:openFiles", filters),
    saveFile: (defaultPath) => invoke("dialog:saveFile", defaultPath)
  },
  clipboard: {
    saveImage: (payload) => invoke("clipboard:saveImage", payload)
  },
  // Git
  git: {
    status: (cwd) => invoke("git:status", cwd),
    diff: (cwd, file) => invoke("git:diff", cwd, file),
    log: (cwd, limit) => invoke("git:log", cwd, limit),
    stage: (cwd, files) => invoke("git:stage", cwd, files),
    unstage: (cwd, files) => invoke("git:unstage", cwd, files),
    commit: (cwd, message) => invoke("git:commit", cwd, message),
    push: (cwd) => invoke("git:push", cwd),
    pull: (cwd) => invoke("git:pull", cwd),
    branches: (cwd) => invoke("git:branches", cwd),
    checkout: (cwd, branch, create) => invoke("git:checkout", cwd, branch, create)
  },
  // PTY Terminal
  pty: {
    create: (opts) => invoke("pty:create", opts),
    write: (id, data) => invoke("pty:write", id, data),
    resize: (id, cols, rows) => invoke("pty:resize", id, cols, rows),
    kill: (id) => invoke("pty:kill", id),
    onData: (id, fn) => on(`pty:data:${id}`, fn),
    onExit: (id, fn) => on(`pty:exit:${id}`, fn)
  },
  // Shell
  shell: {
    exec: (cmd, cwd) => invoke("shell:exec", cmd, cwd),
    openExternal: (url) => invoke("shell:openExternal", url)
  }
});
