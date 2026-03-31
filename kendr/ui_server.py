from __future__ import annotations

import json
import os
import queue
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tasks.setup_config_store import (
    apply_setup_env_defaults,
    get_setup_component_snapshot,
    save_component_values,
    set_component_enabled,
    setup_overview,
    export_env_lines,
)

_UI_PORT = int(os.getenv("KENDR_UI_PORT", "2151"))
_UI_HOST = os.getenv("KENDR_UI_HOST", "0.0.0.0")

_GATEWAY_HOST = os.getenv("GATEWAY_HOST", "127.0.0.1")
_GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8790"))
_GATEWAY_URL = f"http://{_GATEWAY_HOST}:{_GATEWAY_PORT}"

_TEAL = "#00C9A7"
_AMBER = "#FFB347"
_CRIMSON = "#FF4757"
_BLUE = "#5352ED"

_pending_runs: dict[str, dict] = {}
_run_event_queues: dict[str, queue.Queue] = {}
_pending_lock = threading.Lock()


def _gateway_ready(timeout: float = 1.0) -> bool:
    try:
        req = urllib.request.Request(f"{_GATEWAY_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _gateway_ingest(payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{_GATEWAY_URL}/ingest",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _gateway_get(path: str, timeout: float = 5.0) -> dict | list:
    req = urllib.request.Request(f"{_GATEWAY_URL}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _start_run_background(run_id: str, payload: dict) -> None:
    q = _run_event_queues.get(run_id)

    def _push(event_type: str, data: dict) -> None:
        if q:
            q.put({"type": event_type, "data": data})

    def _run() -> None:
        try:
            _push("status", {"status": "running", "message": "Run started, agents mobilizing..."})
            payload["run_id"] = run_id
            result = _gateway_ingest(payload)
            with _pending_lock:
                _pending_runs[run_id] = {"status": "completed", "result": result}
            _push("result", result)
            _push("done", {"run_id": run_id, "status": "completed"})
        except urllib.error.URLError as exc:
            err = str(exc)
            with _pending_lock:
                _pending_runs[run_id] = {"status": "failed", "error": err}
            _push("error", {"message": err})
            _push("done", {"run_id": run_id, "status": "failed"})
        except Exception as exc:
            err = traceback.format_exc()
            with _pending_lock:
                _pending_runs[run_id] = {"status": "failed", "error": err}
            _push("error", {"message": str(exc)})
            _push("done", {"run_id": run_id, "status": "failed"})

    t = threading.Thread(target=_run, daemon=True)
    t.start()


_CHAT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr — Chat</title>
<style>
:root {
  --teal: #00C9A7;
  --amber: #FFB347;
  --crimson: #FF4757;
  --blue: #5352ED;
  --bg: #0d0f14;
  --surface: #161b22;
  --surface2: #1e2530;
  --border: #2a3140;
  --text: #e6edf3;
  --muted: #7d8590;
  --sidebar-w: 280px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); height: 100vh; display: flex; overflow: hidden; }
a { color: var(--teal); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Sidebar */
.sidebar {
  width: var(--sidebar-w);
  min-width: var(--sidebar-w);
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-header {
  padding: 20px 16px 12px;
  border-bottom: 1px solid var(--border);
}
.logo {
  font-size: 22px;
  font-weight: 800;
  color: var(--teal);
  letter-spacing: 0.05em;
}
.logo span { color: var(--amber); }
.tagline { font-size: 11px; color: var(--muted); margin-top: 4px; }
.sidebar-nav {
  padding: 12px 8px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.nav-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--muted);
  cursor: pointer;
  border: none;
  background: transparent;
  width: 100%;
  text-align: left;
  text-decoration: none;
  transition: background 0.15s, color 0.15s;
}
.nav-btn:hover { background: var(--surface2); color: var(--text); }
.nav-btn.active { background: rgba(0, 201, 167, 0.12); color: var(--teal); }
.nav-btn .icon { font-size: 16px; width: 20px; text-align: center; }

.sidebar-section { padding: 10px 16px 6px; font-size: 10px; font-weight: 700; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; }
.run-list { overflow-y: auto; flex: 1; padding: 0 8px 16px; }
.run-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
  border: 1px solid transparent;
  transition: background 0.15s;
}
.run-item:hover { background: var(--surface2); }
.run-item.active { background: rgba(83, 82, 237, 0.12); border-color: rgba(83, 82, 237, 0.3); }
.run-item-title { font-size: 12px; font-weight: 500; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.run-item-meta { font-size: 11px; color: var(--muted); margin-top: 2px; }
.run-badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; }
.run-badge.completed { background: rgba(0, 201, 167, 0.15); color: var(--teal); }
.run-badge.failed { background: rgba(255, 71, 87, 0.15); color: var(--crimson); }
.run-badge.running { background: rgba(255, 179, 71, 0.15); color: var(--amber); }
.new-chat-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin: 12px 8px 4px;
  padding: 10px;
  background: rgba(0, 201, 167, 0.1);
  border: 1px solid rgba(0, 201, 167, 0.3);
  color: var(--teal);
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.new-chat-btn:hover { background: rgba(0, 201, 167, 0.2); }

/* Main chat */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg);
}
.chat-header {
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--surface);
}
.chat-title { font-size: 15px; font-weight: 600; color: var(--text); }
.chat-subtitle { font-size: 12px; color: var(--muted); }
.header-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--muted);
}
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--crimson); }
.status-dot.online { background: var(--teal); animation: pulse 2s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  scroll-behavior: smooth;
}
.message-row { display: flex; gap: 12px; max-width: 900px; }
.message-row.user { flex-direction: row-reverse; margin-left: auto; }
.message-row.user .bubble { background: rgba(83, 82, 237, 0.2); border-color: rgba(83, 82, 237, 0.4); border-radius: 18px 4px 18px 18px; }
.avatar { width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
.avatar.kendr { background: rgba(0, 201, 167, 0.15); border: 1px solid rgba(0, 201, 167, 0.3); }
.avatar.user { background: rgba(83, 82, 237, 0.2); border: 1px solid rgba(83, 82, 237, 0.3); }
.bubble {
  padding: 14px 18px;
  border-radius: 4px 18px 18px 18px;
  border: 1px solid var(--border);
  background: var(--surface);
  max-width: 680px;
  font-size: 14px;
  line-height: 1.65;
}
.bubble-meta { font-size: 11px; color: var(--muted); margin-top: 8px; }
.bubble pre {
  background: rgba(0,0,0,0.3);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  font-size: 13px;
  margin: 8px 0;
  white-space: pre-wrap;
}

/* Agent step cards */
.steps-wrapper { display: flex; flex-direction: column; gap: 8px; }
.step-card {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.step-card.running { border-color: rgba(255, 179, 71, 0.4); }
.step-card.done { border-color: rgba(0, 201, 167, 0.3); }
.step-card.failed { border-color: rgba(255, 71, 87, 0.4); }
.step-icon { font-size: 14px; flex-shrink: 0; }
.step-info { flex: 1; }
.step-name { font-weight: 600; color: var(--text); }
.step-desc { color: var(--muted); font-size: 11px; margin-top: 2px; }

/* Typing indicator */
.typing-indicator { display: flex; align-items: center; gap: 4px; padding: 8px 12px; }
.typing-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); animation: typing 1.4s infinite; }
.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing { 0%,100% { transform: translateY(0); opacity: 0.5; } 50% { transform: translateY(-4px); opacity: 1; } }

/* Welcome */
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 20px;
  padding: 40px;
  text-align: center;
}
.welcome-logo { font-size: 56px; color: var(--teal); filter: drop-shadow(0 0 20px rgba(0,201,167,0.4)); }
.welcome h2 { font-size: 24px; font-weight: 700; color: var(--text); }
.welcome p { font-size: 14px; color: var(--muted); max-width: 480px; line-height: 1.7; }
.suggestions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 8px; }
.suggest-chip {
  padding: 8px 16px;
  border: 1px solid var(--border);
  border-radius: 20px;
  font-size: 13px;
  color: var(--muted);
  cursor: pointer;
  transition: all 0.15s;
  background: var(--surface);
}
.suggest-chip:hover { border-color: var(--teal); color: var(--teal); background: rgba(0,201,167,0.06); }

/* Input area */
.input-area {
  padding: 16px 24px 20px;
  border-top: 1px solid var(--border);
  background: var(--surface);
}
.input-row { display: flex; gap: 12px; align-items: flex-end; }
.input-box {
  flex: 1;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px 18px;
  color: var(--text);
  font-size: 14px;
  font-family: inherit;
  resize: none;
  min-height: 52px;
  max-height: 200px;
  overflow-y: auto;
  line-height: 1.5;
  transition: border-color 0.15s;
  outline: none;
}
.input-box:focus { border-color: var(--teal); }
.input-box::placeholder { color: var(--muted); }
.send-btn {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: var(--teal);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
  transition: background 0.15s, opacity 0.15s;
  color: #0d0f14;
}
.send-btn:hover { background: #00b396; }
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.input-hint { font-size: 11px; color: var(--muted); margin-top: 8px; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--muted); }

/* Working directory warning */
.wd-warning {
  background: rgba(255,179,71,0.08);
  border: 1px solid rgba(255,179,71,0.3);
  border-radius: 10px;
  padding: 10px 16px;
  font-size: 12px;
  color: var(--amber);
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.wd-input-row {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.wd-input {
  flex: 1;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 7px 10px;
  color: var(--text);
  font-size: 12px;
  font-family: monospace;
}
.wd-btn {
  padding: 7px 14px;
  border: none;
  border-radius: 8px;
  background: var(--amber);
  color: #0d0f14;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.error-banner {
  background: rgba(255,71,87,0.1);
  border: 1px solid rgba(255,71,87,0.3);
  color: var(--crimson);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  display: flex;
  gap: 8px;
  align-items: flex-start;
}
</style>
</head>
<body>

<div class="sidebar">
  <div class="sidebar-header">
    <div class="logo">kendr<span>.</span></div>
    <div class="tagline">Multi-agent intelligence runtime</div>
  </div>
  <div class="sidebar-nav">
    <a href="/" class="nav-btn active"><span class="icon">💬</span> Chat</a>
    <a href="/setup" class="nav-btn"><span class="icon">⚙️</span> Setup & Config</a>
    <a href="/runs" class="nav-btn"><span class="icon">📋</span> Run History</a>
  </div>
  <button class="new-chat-btn" onclick="newChat()">+ New Chat</button>
  <div class="sidebar-section">Recent Runs</div>
  <div class="run-list" id="runList"></div>
</div>

<div class="chat-main">
  <div class="chat-header">
    <div>
      <div class="chat-title" id="chatTitle">New Chat</div>
      <div class="chat-subtitle">Powered by kendr multi-agent runtime</div>
    </div>
    <div class="header-status">
      <div class="status-dot" id="gatewayDot"></div>
      <span id="gatewayStatus">Checking gateway...</span>
    </div>
  </div>
  <div class="messages" id="messages">
    <div class="welcome" id="welcome">
      <div class="welcome-logo">⚡</div>
      <h2>What would you like to research or build?</h2>
      <p>Kendr orchestrates specialized AI agents to research, generate code, deploy applications, analyze data, and automate complex workflows — all from a single query.</p>
      <div class="suggestions">
        <div class="suggest-chip" onclick="fillInput('Create a competitive intelligence brief on Stripe')">📊 Stripe competitive brief</div>
        <div class="suggest-chip" onclick="fillInput('Build a FastAPI REST API with JWT authentication and PostgreSQL')">🏗️ FastAPI + JWT + PostgreSQL</div>
        <div class="suggest-chip" onclick="fillInput('Write API tests for https://jsonplaceholder.typicode.com')">🧪 API test generation</div>
        <div class="suggest-chip" onclick="fillInput('Summarize my unread emails and Slack messages from today')">📬 Communications digest</div>
        <div class="suggest-chip" onclick="fillInput('Dockerize a Node.js app and push to Docker Hub')">🐳 Dockerize + push</div>
        <div class="suggest-chip" onclick="fillInput('Deploy a React app to AWS S3 and CloudFront')">☁️ Deploy to AWS</div>
      </div>
    </div>
  </div>
  <div class="input-area">
    <div class="wd-warning" id="wdWarning" style="display:none">
      ⚠️ No working directory set. Artifacts cannot be saved until you set one.
      <div class="wd-input-row">
        <input type="text" class="wd-input" id="wdInput" placeholder="/home/user/kendr-work">
        <button class="wd-btn" onclick="saveWorkdir()">Set</button>
      </div>
    </div>
    <div class="input-row">
      <textarea class="input-box" id="userInput" placeholder="Ask kendr anything — research, code, deploy, analyze..." rows="1" onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
      <button class="send-btn" id="sendBtn" onclick="sendMessage()" title="Send (Ctrl+Enter)">➤</button>
    </div>
    <div class="input-hint">Press Enter to send · Shift+Enter for new line · Gateway required for runs</div>
  </div>
</div>

<script>
const API = '';
let currentRunId = null;
let isRunning = false;
let gatewayOnline = false;
let workingDir = '';

async function checkGateway() {
  try {
    const r = await fetch(API + '/api/gateway/status');
    const d = await r.json();
    gatewayOnline = d.online;
    workingDir = d.working_dir || '';
    const dot = document.getElementById('gatewayDot');
    const status = document.getElementById('gatewayStatus');
    if (gatewayOnline) {
      dot.classList.add('online');
      status.textContent = 'Gateway online';
    } else {
      dot.classList.remove('online');
      status.textContent = 'Gateway offline — run: kendr gateway start';
    }
    if (!workingDir) {
      document.getElementById('wdWarning').style.display = 'flex';
    }
  } catch(e) {
    document.getElementById('gatewayDot').classList.remove('online');
    document.getElementById('gatewayStatus').textContent = 'API unavailable';
  }
}

async function loadRuns() {
  try {
    const r = await fetch(API + '/api/runs');
    const runs = await r.json();
    const list = document.getElementById('runList');
    list.innerHTML = '';
    (runs || []).slice(0, 20).forEach(run => {
      const div = document.createElement('div');
      div.className = 'run-item' + (run.run_id === currentRunId ? ' active' : '');
      const text = (run.query || run.text || 'Run').substring(0, 50);
      const ts = run.created_at ? new Date(run.created_at).toLocaleTimeString() : '';
      const status = (run.status || 'completed').toLowerCase();
      div.innerHTML = `
        <div class="run-item-title">${esc(text)}</div>
        <div class="run-item-meta"><span class="run-badge ${status}">${status}</span>${ts ? ' · ' + ts : ''}</div>
      `;
      div.onclick = () => loadRun(run.run_id);
      list.appendChild(div);
    });
  } catch(e) {}
}

async function loadRun(runId) {
  try {
    const r = await fetch(API + '/api/runs/' + runId);
    const d = await r.json();
    const output = d.final_output || d.output || '';
    const query = d.query || d.text || '';
    if (query) {
      clearMessages();
      appendUserMsg(query);
      if (output) appendKendrMsg(output, runId);
    }
  } catch(e) {}
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function newChat() {
  currentRunId = null;
  clearMessages();
  document.getElementById('chatTitle').textContent = 'New Chat';
  document.getElementById('userInput').focus();
}

function clearMessages() {
  const msgs = document.getElementById('messages');
  msgs.innerHTML = '';
}

function fillInput(text) {
  const input = document.getElementById('userInput');
  input.value = text;
  autoResize(input);
  input.focus();
  document.getElementById('welcome') && (document.getElementById('welcome').style.display = 'none');
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function scrollDown() {
  const msgs = document.getElementById('messages');
  msgs.scrollTop = msgs.scrollHeight;
}

function appendUserMsg(text) {
  const welcome = document.getElementById('welcome');
  if (welcome) welcome.remove();
  const msgs = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'message-row user';
  row.innerHTML = `
    <div class="avatar user">🧑</div>
    <div class="bubble"><div style="white-space:pre-wrap">${esc(text)}</div></div>
  `;
  msgs.appendChild(row);
  scrollDown();
}

function appendKendrMsg(output, runId) {
  const msgs = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'message-row kendr';
  const formattedOutput = formatOutput(output);
  row.innerHTML = `
    <div class="avatar kendr">⚡</div>
    <div class="bubble">
      <div>${formattedOutput}</div>
      ${runId ? '<div class="bubble-meta">Run ID: ' + esc(runId) + ' · <a href="/api/runs/' + esc(runId) + '" target="_blank">View artifacts</a></div>' : ''}
    </div>
  `;
  msgs.appendChild(row);
  scrollDown();
}

function formatOutput(text) {
  if (!text) return '';
  let html = esc(text);
  html = html.replace(/```([\\s\\S]*?)```/g, '<pre>$1</pre>');
  html = html.replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.3);padding:2px 6px;border-radius:4px;font-family:monospace">$1</code>');
  html = html.replace(/\\n/g, '<br>');
  return html;
}

function appendTypingIndicator() {
  const msgs = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'message-row kendr';
  row.id = 'typing-row';
  row.innerHTML = `
    <div class="avatar kendr">⚡</div>
    <div class="bubble" id="typing-bubble">
      <div class="typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
      <div class="steps-wrapper" id="step-cards"></div>
    </div>
  `;
  msgs.appendChild(row);
  scrollDown();
  return row;
}

function addStepCard(step) {
  const steps = document.getElementById('step-cards');
  if (!steps) return;
  const div = document.createElement('div');
  div.className = 'step-card ' + (step.status || 'running');
  div.id = 'step-' + (step.agent || step.name || Math.random());
  const icons = { running: '⚙️', done: '✓', failed: '✗' };
  const icon = icons[step.status] || '⚙️';
  div.innerHTML = `
    <div class="step-icon">${icon}</div>
    <div class="step-info">
      <div class="step-name">${esc(step.agent || step.name || 'agent')}</div>
      <div class="step-desc">${esc(step.message || '')}</div>
    </div>
  `;
  steps.appendChild(div);
  scrollDown();
}

function removeTypingIndicator() {
  const row = document.getElementById('typing-row');
  if (row) row.remove();
}

async function sendMessage() {
  const input = document.getElementById('userInput');
  const text = input.value.trim();
  if (!text || isRunning) return;

  input.value = '';
  autoResize(input);
  isRunning = true;
  document.getElementById('sendBtn').disabled = true;

  appendUserMsg(text);
  const typing = appendTypingIndicator();

  const title = text.substring(0, 40) + (text.length > 40 ? '...' : '');
  document.getElementById('chatTitle').textContent = title;

  try {
    const payload = { text, working_directory: workingDir, channel: 'webchat', sender_id: 'ui_user', chat_id: 'web_chat_1' };
    const runId = 'ui-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
    currentRunId = runId;

    const resp = await fetch(API + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...payload, run_id: runId })
    });
    const result = await resp.json();

    removeTypingIndicator();

    if (result.error) {
      const msgs = document.getElementById('messages');
      const row = document.createElement('div');
      row.className = 'message-row kendr';
      row.innerHTML = `<div class="avatar kendr">⚡</div><div class="bubble"><div class="error-banner">⚠️ ${esc(result.error + (result.detail ? ': ' + result.detail : ''))}</div></div>`;
      msgs.appendChild(row);
    } else {
      const output = result.final_output || result.output || result.draft_response || '';
      appendKendrMsg(output || '(Run completed — check artifacts)', result.run_id || runId);
    }
    loadRuns();
  } catch(err) {
    removeTypingIndicator();
    const msgs = document.getElementById('messages');
    const row = document.createElement('div');
    row.className = 'message-row kendr';
    row.innerHTML = `<div class="avatar kendr">⚡</div><div class="bubble"><div class="error-banner">⚠️ Request failed: ${esc(String(err))}</div></div>`;
    msgs.appendChild(row);
  }

  isRunning = false;
  document.getElementById('sendBtn').disabled = false;
  scrollDown();
}

async function saveWorkdir() {
  const val = document.getElementById('wdInput').value.trim();
  if (!val) return;
  try {
    await fetch(API + '/api/setup/workdir', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({path: val}) });
    workingDir = val;
    document.getElementById('wdWarning').style.display = 'none';
  } catch(e) { alert('Failed to set working directory: ' + e); }
}

checkGateway();
loadRuns();
setInterval(checkGateway, 30000);
setInterval(loadRuns, 10000);
</script>
</body>
</html>"""


_SETUP_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr — Setup & Config</title>
<style>
:root {
  --teal: #00C9A7;
  --amber: #FFB347;
  --crimson: #FF4757;
  --blue: #5352ED;
  --bg: #0d0f14;
  --surface: #161b22;
  --surface2: #1e2530;
  --border: #2a3140;
  --text: #e6edf3;
  --muted: #7d8590;
  --sidebar-w: 280px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; }
a { color: var(--teal); text-decoration: none; }

.sidebar {
  width: var(--sidebar-w);
  min-width: var(--sidebar-w);
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  position: fixed;
  top: 0; bottom: 0; left: 0;
}
.sidebar-header { padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }
.logo { font-size: 22px; font-weight: 800; color: var(--teal); letter-spacing: 0.05em; }
.logo span { color: var(--amber); }
.tagline { font-size: 11px; color: var(--muted); margin-top: 4px; }
.sidebar-nav { padding: 12px 8px; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; }
.nav-btn {
  display: flex; align-items: center; gap: 10px; padding: 9px 12px;
  border-radius: 8px; font-size: 13px; font-weight: 500; color: var(--muted);
  cursor: pointer; border: none; background: transparent; width: 100%;
  text-align: left; text-decoration: none; transition: background 0.15s, color 0.15s;
}
.nav-btn:hover { background: var(--surface2); color: var(--text); }
.nav-btn.active { background: rgba(0,201,167,0.12); color: var(--teal); }
.nav-btn .icon { font-size: 16px; width: 20px; text-align: center; }
.category-nav { overflow-y: auto; flex: 1; padding: 8px; }
.cat-btn {
  width: 100%; padding: 8px 12px; background: transparent; border: none;
  color: var(--muted); font-size: 12px; text-align: left; border-radius: 6px;
  cursor: pointer; transition: all 0.15s;
}
.cat-btn:hover { background: var(--surface2); color: var(--text); }
.cat-btn.active { color: var(--teal); font-weight: 600; }

.main { flex: 1; margin-left: var(--sidebar-w); padding: 32px; max-width: 1100px; }
.page-header { margin-bottom: 32px; }
.page-title { font-size: 26px; font-weight: 700; color: var(--text); }
.page-sub { color: var(--muted); font-size: 14px; margin-top: 6px; }

.section-title {
  font-size: 11px; font-weight: 700; color: var(--muted);
  letter-spacing: 0.08em; text-transform: uppercase; margin: 28px 0 12px;
  padding-bottom: 8px; border-bottom: 1px solid var(--border);
}

.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
.int-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px;
  transition: border-color 0.15s;
}
.int-card:hover { border-color: var(--blue); }
.int-card.configured { border-color: rgba(0,201,167,0.35); }
.int-card.expanded { border-color: var(--blue); }
.card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; cursor: pointer; }
.card-title-row { flex: 1; }
.card-title { font-size: 15px; font-weight: 600; color: var(--text); }
.card-desc { font-size: 12px; color: var(--muted); margin-top: 4px; line-height: 1.5; }
.card-badges { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }
.badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.badge.ok { background: rgba(0,201,167,0.15); color: var(--teal); }
.badge.warn { background: rgba(255,179,71,0.15); color: var(--amber); }
.badge.err { background: rgba(255,71,87,0.15); color: var(--crimson); }
.badge.muted { background: rgba(125,133,144,0.15); color: var(--muted); }
.toggle {
  width: 38px; height: 22px; border-radius: 11px;
  background: var(--border); border: none; cursor: pointer;
  position: relative; flex-shrink: 0; transition: background 0.2s;
}
.toggle::after {
  content: '';
  position: absolute;
  top: 3px; left: 3px;
  width: 16px; height: 16px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.2s;
}
.toggle.on { background: var(--teal); }
.toggle.on::after { transform: translateX(16px); }

.card-body { margin-top: 16px; display: none; }
.card-body.open { display: block; }
.field-row { margin-bottom: 12px; }
.field-label { font-size: 12px; font-weight: 600; color: var(--text); margin-bottom: 5px; display: flex; align-items: center; gap: 6px; }
.field-desc { font-size: 11px; color: var(--muted); margin-bottom: 5px; }
.secret-badge { font-size: 9px; padding: 1px 5px; border-radius: 3px; background: rgba(255,71,87,0.15); color: var(--crimson); font-weight: 700; }
.required-badge { font-size: 9px; padding: 1px 5px; border-radius: 3px; background: rgba(255,179,71,0.15); color: var(--amber); font-weight: 700; }
.field-input {
  width: 100%; padding: 9px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px; color: var(--text);
  font-size: 13px; font-family: monospace;
  transition: border-color 0.15s; outline: none;
}
.field-input:focus { border-color: var(--teal); }
.card-actions { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
.btn { padding: 8px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: all 0.15s; }
.btn.primary { background: var(--teal); color: #0d0f14; }
.btn.primary:hover { background: #00b396; }
.btn.secondary { background: var(--surface2); color: var(--text); border: 1px solid var(--border); }
.btn.secondary:hover { border-color: var(--muted); }
.btn.danger { background: rgba(255,71,87,0.15); color: var(--crimson); border: 1px solid rgba(255,71,87,0.3); }
.btn.oauth { background: rgba(83,82,237,0.15); color: var(--blue); border: 1px solid rgba(83,82,237,0.3); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.save-msg { font-size: 12px; padding: 4px 10px; border-radius: 6px; display: inline-flex; align-items: center; }
.save-msg.ok { background: rgba(0,201,167,0.1); color: var(--teal); }
.save-msg.err { background: rgba(255,71,87,0.1); color: var(--crimson); }

.summary-bar {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 20px;
  display: flex; gap: 24px; flex-wrap: wrap;
  margin-bottom: 28px;
}
.summary-stat { text-align: center; }
.stat-val { font-size: 24px; font-weight: 700; }
.stat-val.teal { color: var(--teal); }
.stat-val.amber { color: var(--amber); }
.stat-val.crimson { color: var(--crimson); }
.stat-label { font-size: 11px; color: var(--muted); margin-top: 2px; }

.env-export {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  margin-top: 32px;
}
.env-export pre { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; font-size: 12px; overflow-x: auto; white-space: pre-wrap; max-height: 300px; }

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>

<div class="sidebar">
  <div class="sidebar-header">
    <div class="logo">kendr<span>.</span></div>
    <div class="tagline">Multi-agent intelligence runtime</div>
  </div>
  <div class="sidebar-nav">
    <a href="/" class="nav-btn"><span class="icon">💬</span> Chat</a>
    <a href="/setup" class="nav-btn active"><span class="icon">⚙️</span> Setup & Config</a>
    <a href="/runs" class="nav-btn"><span class="icon">📋</span> Run History</a>
  </div>
  <div class="category-nav" id="categoryNav"></div>
</div>

<div class="main">
  <div class="page-header">
    <div class="page-title">Setup & Configuration</div>
    <div class="page-sub">Configure integrations, API keys, and runtime settings. All values are stored locally.</div>
  </div>
  <div class="summary-bar" id="summaryBar">
    <div class="summary-stat"><div class="stat-val teal" id="statConfigured">-</div><div class="stat-label">Configured</div></div>
    <div class="summary-stat"><div class="stat-val amber" id="statPartial">-</div><div class="stat-label">Partial</div></div>
    <div class="summary-stat"><div class="stat-val crimson" id="statMissing">-</div><div class="stat-label">Missing</div></div>
    <div class="summary-stat"><div class="stat-val" id="statTotal" style="color:var(--muted)">-</div><div class="stat-label">Total</div></div>
  </div>
  <div id="integrations"></div>
  <div class="env-export">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div style="font-size:14px;font-weight:600">Export .env</div>
      <button class="btn secondary" onclick="loadEnvExport()">Refresh</button>
    </div>
    <pre id="envExport">Loading...</pre>
  </div>
</div>

<script>
const API = '';
let allComponents = [];
let expandedCards = new Set();

async function loadSetup() {
  try {
    const r = await fetch(API + '/api/setup/overview');
    const d = await r.json();
    allComponents = d.components || [];
    renderStats(allComponents);
    renderCategories(d.categories || {});
    renderIntegrations(allComponents);
  } catch(e) {
    document.getElementById('integrations').innerHTML = '<div style="color:var(--crimson);padding:16px">Failed to load setup data: ' + String(e) + '</div>';
  }
}

function renderStats(components) {
  let configured = 0, partial = 0, missing = 0;
  components.forEach(c => {
    const total = c.total_fields || 0;
    const filled = c.filled_fields || 0;
    if (total === 0) { configured++; return; }
    if (filled === total) configured++;
    else if (filled > 0) partial++;
    else missing++;
  });
  document.getElementById('statConfigured').textContent = configured;
  document.getElementById('statPartial').textContent = partial;
  document.getElementById('statMissing').textContent = missing;
  document.getElementById('statTotal').textContent = components.length;
}

function renderCategories(categories) {
  const nav = document.getElementById('categoryNav');
  nav.innerHTML = '<div style="padding:10px 12px 4px;font-size:10px;font-weight:700;color:var(--muted);letter-spacing:0.08em;text-transform:uppercase">Categories</div>';
  Object.keys(categories).forEach(cat => {
    const btn = document.createElement('button');
    btn.className = 'cat-btn';
    btn.textContent = cat + ' (' + categories[cat].length + ')';
    btn.onclick = () => {
      document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('sec-' + slugify(cat))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    nav.appendChild(btn);
  });
}

function slugify(s) { return s.toLowerCase().replace(/[^a-z0-9]+/g, '-'); }

function renderIntegrations(components) {
  const byCategory = {};
  components.forEach(c => {
    const cat = c.category || 'Other';
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(c);
  });

  const container = document.getElementById('integrations');
  container.innerHTML = '';

  Object.entries(byCategory).forEach(([cat, comps]) => {
    const section = document.createElement('div');
    section.id = 'sec-' + slugify(cat);
    section.innerHTML = '<div class="section-title">' + esc(cat) + '</div>';
    const grid = document.createElement('div');
    grid.className = 'card-grid';
    comps.forEach(c => grid.appendChild(makeCard(c)));
    section.appendChild(grid);
    container.appendChild(section);
  });
}

function makeCard(comp) {
  const total = comp.total_fields || 0;
  const filled = comp.filled_fields || 0;
  const isConfigured = total === 0 || filled === total;
  const isPartial = filled > 0 && filled < total;
  const enabled = comp.enabled !== false;

  const div = document.createElement('div');
  div.className = 'int-card' + (isConfigured ? ' configured' : '');
  div.id = 'card-' + comp.id;

  let statusBadge = '';
  if (total === 0) statusBadge = '<span class="badge ok">✓ Ready</span>';
  else if (isConfigured) statusBadge = '<span class="badge ok">✓ Configured</span>';
  else if (isPartial) statusBadge = '<span class="badge warn">⚡ Partial</span>';
  else statusBadge = '<span class="badge err">○ Not set</span>';

  div.innerHTML = `
    <div class="card-header" onclick="toggleCard('${esc(comp.id)}')">
      <div class="card-title-row">
        <div class="card-title">${esc(comp.title)}</div>
        <div class="card-desc">${esc(comp.description)}</div>
      </div>
      <div class="card-badges">
        ${statusBadge}
        <button class="toggle ${enabled ? 'on' : ''}" title="${enabled ? 'Disable' : 'Enable'}" onclick="event.stopPropagation();toggleEnabled('${esc(comp.id)}', this)" data-comp="${esc(comp.id)}"></button>
      </div>
    </div>
    <div class="card-body" id="body-${esc(comp.id)}"></div>
  `;
  return div;
}

async function toggleCard(compId) {
  const body = document.getElementById('body-' + compId);
  if (!body) return;
  const card = document.getElementById('card-' + compId);
  if (body.classList.contains('open')) {
    body.classList.remove('open');
    card.classList.remove('expanded');
    expandedCards.delete(compId);
    return;
  }
  body.classList.add('open');
  card.classList.add('expanded');
  expandedCards.add(compId);
  body.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px">Loading...</div>';
  try {
    const r = await fetch(API + '/api/setup/component/' + compId);
    const d = await r.json();
    renderCardBody(body, d, compId);
  } catch(e) {
    body.innerHTML = '<div style="color:var(--crimson);font-size:12px">Failed to load: ' + String(e) + '</div>';
  }
}

function renderCardBody(body, snapshot, compId) {
  const fields = (snapshot.component || {}).fields || [];
  const values = snapshot.values || {};
  const comp = snapshot.component || {};

  let html = '';
  if (fields.length > 0) {
    fields.forEach(f => {
      const val = values[f.key] || '';
      const type = f.secret ? 'password' : 'text';
      const badges = [
        f.secret ? '<span class="secret-badge">SECRET</span>' : '',
        f.required ? '<span class="required-badge">REQUIRED</span>' : '',
      ].filter(Boolean).join(' ');
      html += `
        <div class="field-row">
          <div class="field-label">${esc(f.label)} ${badges}</div>
          ${f.description ? '<div class="field-desc">' + esc(f.description) + '</div>' : ''}
          <input class="field-input" type="${type}" id="fld-${esc(compId)}-${esc(f.key)}" value="${esc(val)}" placeholder="${esc(f.key)}" autocomplete="off">
        </div>
      `;
    });
  } else {
    html = '<div style="font-size:12px;color:var(--muted);margin-bottom:12px">No configurable fields — this integration uses local dependencies or policy settings.</div>';
  }

  const oauthProv = comp.oauth_provider || '';
  let actionsHtml = '';
  if (fields.length > 0) {
    actionsHtml += `<button class="btn primary" onclick="saveComponent('${esc(compId)}')">Save</button>`;
  }
  if (oauthProv) {
    actionsHtml += `<button class="btn oauth" onclick="startOAuth('${esc(oauthProv)}')">Connect via OAuth</button>`;
  }
  actionsHtml += `<span class="save-msg" id="save-msg-${esc(compId)}" style="display:none"></span>`;

  body.innerHTML = html + `<div class="card-actions">${actionsHtml}</div>`;
}

async function saveComponent(compId) {
  const fields = allComponents.find(c => c.id === compId);
  if (!fields) return;
  const compDetail = await fetch(API + '/api/setup/component/' + compId).then(r => r.json()).catch(() => ({}));
  const compFields = (compDetail.component || {}).fields || [];
  const values = {};
  compFields.forEach(f => {
    const el = document.getElementById('fld-' + compId + '-' + f.key);
    if (el) values[f.key] = el.value;
  });
  const msg = document.getElementById('save-msg-' + compId);
  try {
    const r = await fetch(API + '/api/setup/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ component_id: compId, values })
    });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    if (msg) { msg.style.display = 'inline-flex'; msg.className = 'save-msg ok'; msg.textContent = '✓ Saved'; setTimeout(() => { msg.style.display = 'none'; }, 2500); }
    loadSetup();
  } catch(e) {
    if (msg) { msg.style.display = 'inline-flex'; msg.className = 'save-msg err'; msg.textContent = '✗ ' + String(e); }
  }
}

async function toggleEnabled(compId, btn) {
  const isOn = btn.classList.contains('on');
  const newState = !isOn;
  try {
    await fetch(API + '/api/setup/enabled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ component_id: compId, enabled: newState })
    });
    btn.classList.toggle('on', newState);
  } catch(e) { alert('Failed: ' + e); }
}

function startOAuth(provider) {
  window.open('/oauth/' + provider + '/start', '_blank', 'width=600,height=700');
}

async function loadEnvExport() {
  try {
    const r = await fetch(API + '/api/setup/env-export');
    const d = await r.json();
    document.getElementById('envExport').textContent = (d.lines || []).join('\\n') || '# No configuration stored yet.';
  } catch(e) {
    document.getElementById('envExport').textContent = '# Error: ' + e;
  }
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

loadSetup();
loadEnvExport();
</script>
</body>
</html>"""


_RUNS_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr — Run History</title>
<style>
:root { --teal: #00C9A7; --amber: #FFB347; --crimson: #FF4757; --blue: #5352ED; --bg: #0d0f14; --surface: #161b22; --surface2: #1e2530; --border: #2a3140; --text: #e6edf3; --muted: #7d8590; --sidebar-w: 280px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; }
a { color: var(--teal); }
.sidebar { width: var(--sidebar-w); min-width: var(--sidebar-w); background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; position: fixed; top: 0; bottom: 0; left: 0; }
.sidebar-header { padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }
.logo { font-size: 22px; font-weight: 800; color: var(--teal); }
.logo span { color: var(--amber); }
.tagline { font-size: 11px; color: var(--muted); margin-top: 4px; }
.sidebar-nav { padding: 12px 8px; display: flex; flex-direction: column; gap: 4px; }
.nav-btn { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 8px; font-size: 13px; font-weight: 500; color: var(--muted); cursor: pointer; border: none; background: transparent; width: 100%; text-align: left; text-decoration: none; transition: background 0.15s, color 0.15s; }
.nav-btn:hover { background: var(--surface2); color: var(--text); }
.nav-btn.active { background: rgba(0,201,167,0.12); color: var(--teal); }
.nav-btn .icon { font-size: 16px; width: 20px; text-align: center; }
.main { flex: 1; margin-left: var(--sidebar-w); padding: 32px; }
.page-title { font-size: 26px; font-weight: 700; margin-bottom: 24px; }
.run-table { width: 100%; border-collapse: collapse; }
.run-table th { text-align: left; padding: 10px 16px; font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; border-bottom: 1px solid var(--border); }
.run-table td { padding: 12px 16px; border-bottom: 1px solid var(--border); font-size: 13px; vertical-align: top; }
.run-table tr:hover td { background: var(--surface); }
.query-cell { max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge.completed { background: rgba(0,201,167,0.15); color: var(--teal); }
.badge.failed { background: rgba(255,71,87,0.15); color: var(--crimson); }
.badge.running { background: rgba(255,179,71,0.15); color: var(--amber); }
::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>
<div class="sidebar">
  <div class="sidebar-header"><div class="logo">kendr<span>.</span></div><div class="tagline">Multi-agent intelligence runtime</div></div>
  <div class="sidebar-nav">
    <a href="/" class="nav-btn"><span class="icon">💬</span> Chat</a>
    <a href="/setup" class="nav-btn"><span class="icon">⚙️</span> Setup & Config</a>
    <a href="/runs" class="nav-btn active"><span class="icon">📋</span> Run History</a>
  </div>
</div>
<div class="main">
  <div class="page-title">Run History</div>
  <table class="run-table">
    <thead><tr><th>Query</th><th>Run ID</th><th>Status</th><th>Agent</th><th>Created</th></tr></thead>
    <tbody id="runBody"><tr><td colspan="5" style="color:var(--muted);text-align:center;padding:24px">Loading...</td></tr></tbody>
  </table>
</div>
<script>
function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
async function load() {
  try {
    const r = await fetch('/api/runs');
    const runs = await r.json();
    const body = document.getElementById('runBody');
    if (!runs || !runs.length) { body.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center;padding:24px">No runs yet. Start a chat to create your first run.</td></tr>'; return; }
    body.innerHTML = runs.map(run => {
      const status = (run.status || 'completed').toLowerCase();
      return `<tr>
        <td class="query-cell" title="${esc(run.query||run.text||'')}">${esc((run.query||run.text||'—').substring(0,80))}</td>
        <td style="font-family:monospace;font-size:11px;color:var(--muted)">${esc(run.run_id||'')}</td>
        <td><span class="badge ${status}">${status}</span></td>
        <td style="color:var(--muted)">${esc(run.last_agent||'')}</td>
        <td style="color:var(--muted);white-space:nowrap">${esc(run.created_at||'')}</td>
      </tr>`;
    }).join('');
  } catch(e) { document.getElementById('runBody').innerHTML = '<tr><td colspan="5" style="color:var(--crimson)">Error: ' + String(e) + '</td></tr>'; }
}
load();
</script>
</body>
</html>"""


class KendrUIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _html(self, status: int, content: str) -> None:
        self._send(status, "text/html; charset=utf-8", content.encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/" or path == "/chat":
            self._html(200, _CHAT_HTML)
            return
        if path == "/setup":
            self._html(200, _SETUP_HTML)
            return
        if path == "/runs":
            self._html(200, _RUNS_HTML)
            return
        if path == "/api/gateway/status":
            working_dir = os.getenv("KENDR_WORKING_DIR", "").strip()
            self._json(200, {
                "online": _gateway_ready(),
                "gateway_url": _GATEWAY_URL,
                "working_dir": working_dir,
                "ui_url": f"http://localhost:{_UI_PORT}",
            })
            return
        if path == "/api/runs":
            try:
                runs = _gateway_get("/runs", timeout=5.0)
            except Exception:
                runs = []
            self._json(200, runs)
            return
        if path.startswith("/api/runs/"):
            run_id = path[len("/api/runs/"):]
            try:
                data = _gateway_get(f"/runs/{run_id}")
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            self._json(200, data)
            return
        if path == "/api/setup/overview":
            try:
                apply_setup_env_defaults()
                overview = setup_overview()
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            self._json(200, overview)
            return
        if path.startswith("/api/setup/component/"):
            comp_id = path[len("/api/setup/component/"):]
            try:
                snap = get_setup_component_snapshot(comp_id)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            if not snap:
                self._json(404, {"error": "component_not_found"})
                return
            self._json(200, snap)
            return
        if path == "/api/setup/env-export":
            try:
                lines = export_env_lines(include_secrets=False)
            except Exception as exc:
                lines = []
            self._json(200, {"lines": lines})
            return
        if path == "/api/stream":
            params = parse_qs(parsed.query or "")
            run_id = (params.get("run_id") or [""])[0]
            if not run_id:
                self._json(400, {"error": "missing_run_id"})
                return
            self._handle_sse(run_id)
            return
        self._json(404, {"error": "not_found", "path": path})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length)
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as exc:
            self._json(400, {"error": "invalid_json", "detail": str(exc)})
            return

        if path == "/api/chat":
            self._handle_chat(body)
            return
        if path == "/api/setup/save":
            self._handle_setup_save(body)
            return
        if path == "/api/setup/enabled":
            self._handle_setup_enabled(body)
            return
        if path == "/api/setup/workdir":
            self._handle_workdir(body)
            return
        self._json(404, {"error": "not_found"})

    def _handle_chat(self, body: dict) -> None:
        text = str(body.get("text") or body.get("message") or "").strip()
        if not text:
            self._json(400, {"error": "missing_text"})
            return
        if not _gateway_ready():
            self._json(503, {
                "error": "Gateway not running",
                "detail": "Start it with: kendr gateway start",
            })
            return
        working_directory = str(
            body.get("working_directory") or os.getenv("KENDR_WORKING_DIR", "")
        ).strip()
        if not working_directory:
            self._json(400, {
                "error": "working_directory_required",
                "detail": "Set KENDR_WORKING_DIR or configure it in Setup.",
            })
            return
        payload = {
            "text": text,
            "channel": str(body.get("channel", "webchat")),
            "sender_id": str(body.get("sender_id", "ui_user")),
            "chat_id": str(body.get("chat_id", "web_chat_1")),
            "working_directory": working_directory,
        }
        run_id = str(body.get("run_id") or "").strip() or f"ui-{uuid.uuid4().hex[:8]}"
        payload["run_id"] = run_id

        q: queue.Queue = queue.Queue()
        with _pending_lock:
            _run_event_queues[run_id] = q
            _pending_runs[run_id] = {"status": "running"}

        _start_run_background(run_id, payload)

        try:
            while True:
                try:
                    event = q.get(timeout=300)
                except queue.Empty:
                    self._json(504, {"error": "run_timeout"})
                    return
                if event["type"] == "done":
                    break
                if event["type"] == "error":
                    pass

            with _pending_lock:
                run_data = _pending_runs.get(run_id, {})
                _run_event_queues.pop(run_id, None)

            if run_data.get("status") == "failed":
                self._json(500, {"error": run_data.get("error", "Run failed")})
                return
            result = run_data.get("result", {})
            self._json(200, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_sse(self, run_id: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def write_event(event_type: str, data: dict) -> bool:
            try:
                msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
                return True
            except Exception:
                return False

        write_event("status", {"status": "waiting", "run_id": run_id})
        q = _run_event_queues.get(run_id)
        if not q:
            with _pending_lock:
                run_data = _pending_runs.get(run_id)
            if run_data:
                write_event("result", run_data.get("result", {}))
                write_event("done", {"run_id": run_id})
            else:
                write_event("error", {"message": "Run not found"})
            return

        while True:
            try:
                event = q.get(timeout=1.0)
                if not write_event(event["type"], event["data"]):
                    break
                if event["type"] == "done":
                    break
            except queue.Empty:
                if not write_event("ping", {"ts": int(time.time())}):
                    break

    def _handle_setup_save(self, body: dict) -> None:
        comp_id = str(body.get("component_id", "")).strip()
        values = body.get("values", {})
        if not comp_id:
            self._json(400, {"error": "missing_component_id"})
            return
        try:
            result = save_component_values(comp_id, values)
            apply_setup_env_defaults()
            self._json(200, {"saved": True, "snapshot": result})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_setup_enabled(self, body: dict) -> None:
        comp_id = str(body.get("component_id", "")).strip()
        enabled = bool(body.get("enabled", True))
        if not comp_id:
            self._json(400, {"error": "missing_component_id"})
            return
        try:
            set_component_enabled(comp_id, enabled)
            self._json(200, {"component_id": comp_id, "enabled": enabled})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_workdir(self, body: dict) -> None:
        path_val = str(body.get("path", "")).strip()
        if not path_val:
            self._json(400, {"error": "missing_path"})
            return
        try:
            from pathlib import Path
            resolved = Path(path_val).expanduser().resolve()
            resolved.mkdir(parents=True, exist_ok=True)
            os.environ["KENDR_WORKING_DIR"] = str(resolved)
            save_component_values("core_runtime", {"KENDR_WORKING_DIR": str(resolved)})
            self._json(200, {"path": str(resolved)})
        except Exception as exc:
            self._json(500, {"error": str(exc)})


def main() -> None:
    apply_setup_env_defaults()
    ui_url = f"http://localhost:{_UI_PORT}"
    server = ThreadingHTTPServer((_UI_HOST, _UI_PORT), KendrUIHandler)
    print(f"Kendr UI running at {ui_url}")
    print(f"  Chat:   {ui_url}/")
    print(f"  Setup:  {ui_url}/setup")
    print(f"  Runs:   {ui_url}/runs")
    server.serve_forever()


if __name__ == "__main__":
    main()
