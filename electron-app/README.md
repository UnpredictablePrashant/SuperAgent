# Kendr Desktop

A VS Code–inspired Electron app for the Kendr AI Agent Orchestration platform.

## Features

- **Monaco Editor** — VS Code's editor with syntax highlighting for 50+ languages, multi-tab support
- **Agent Orchestration** — Live view of agent runs, streaming output, artifacts
- **AI Chat** — Stream responses from the Kendr backend; multi-agent support
- **File Explorer** — Full workspace tree with create, rename, delete
- **Source Control** — Stage, commit, push, pull, branch switching
- **Integrated Terminal** — Real PTY terminal (node-pty + xterm.js)
- **Model Manager** — Browse and pull Ollama models
- **Settings** — Backend URL, Python path, editor font, Git config, GitHub PAT
- **Command Palette** — `Ctrl+Shift+P` for keyboard-driven commands

## End-User Install

Published desktop installers are self-contained:

- Windows: `Kendr Setup <version>.exe`
- macOS: `Kendr-<version>-mac-*.dmg`
- Linux: `Kendr-<version>.AppImage` or `kendr-desktop_<version>_amd64.deb`

They bundle the Electron UI and the Kendr backend together, so users do not need to install Python separately.

## Development Prerequisites

1. **Node.js 18+** and **npm**
2. **Python 3.10+** with the parent Kendr project installed
3. Optional: **Ollama** for local models

## Setup

```bash
cd electron-app
npm install
```

> **Windows note**: `node-pty` requires native compilation. If `npm install` fails, install
> [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
> and run: `npm install --python=python3`

## Development

```bash
# Start the kendr Python backend first (from parent directory):
python app.py  # or: python gateway_server.py

# Then in electron-app/:
npm run dev
```

## Production build

```bash
python -m pip install -e ".[bundle]"
npm run package
# Output goes to: dist/
```

Per-platform packaging shortcuts:

```bash
npm run package:win
npm run package:mac
npm run package:linux
```

The packaging step builds a standalone backend bundle first, then embeds it into the Electron installer.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+P` | Command Palette |
| `Ctrl+\`` | Toggle Terminal |
| `Ctrl+B` | Toggle Sidebar |
| `Ctrl+S` | Save current file |
| `Ctrl+Enter` | Send chat message |

## Configuration

Settings are stored via `electron-store` and persisted across sessions.
Edit via **Settings panel** (gear icon in Activity Bar) or Command Palette → `View: Settings`.

Key settings:
- **Backend URL**: default `http://127.0.0.1:2151`
- **Python Path**: only used in development or when falling back to source mode
- **Project Root**: default workspace folder shown in File Explorer
- **Auto-start backend**: start Kendr Python server on app launch
