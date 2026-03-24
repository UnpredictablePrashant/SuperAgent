from __future__ import annotations

import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tasks.setup_config_store import (
    apply_setup_env_defaults,
    export_env_lines,
    get_component,
    get_setup_component_snapshot,
    save_component_values,
    set_component_enabled,
    setup_overview,
)
from tasks.setup_registry import (
    build_google_oauth_config,
    build_google_oauth_start_url,
    build_microsoft_oauth_config,
    build_microsoft_oauth_start_url,
    build_setup_snapshot,
    build_slack_oauth_config,
    build_slack_oauth_start_url,
    exchange_google_oauth_code,
    exchange_microsoft_oauth_code,
    exchange_slack_oauth_code,
    issue_oauth_state_token,
)


PENDING_STATES: dict[str, str] = {}


def _page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f4f7f3;
      --text: #111818;
      --muted: #5d6968;
      --line: #d6e0df;
      --card: #ffffff;
      --brand: #145a56;
      --brand-2: #1e7f79;
      --warn: #9f2900;
      --ok: #0f7a43;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif; color: var(--text); background: radial-gradient(circle at 0% 0%, #e8f2ec 0%, var(--bg) 60%); }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    h1, h2, h3 {{ margin: 0 0 8px; font-family: "Space Grotesk", "Segoe UI", sans-serif; letter-spacing: 0.01em; }}
    .muted {{ color: var(--muted); }}
    .bar {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; }}
    .button {{ display: inline-block; background: var(--brand); color: #fff; text-decoration: none; border: 0; border-radius: 10px; padding: 8px 12px; font-weight: 600; cursor: pointer; }}
    .button.alt {{ background: #e4eeee; color: #1d3a39; }}
    .button.warn {{ background: var(--warn); }}
    .button.ok {{ background: var(--ok); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 14px; box-shadow: 0 4px 12px rgba(17, 24, 24, 0.04); }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 3px 10px; font-size: 12px; background: #ebf1f0; color: #2c4140; }}
    .pill.ok {{ background: #e8f7ee; color: #0a6f3d; }}
    .pill.bad {{ background: #feede8; color: #8c2600; }}
    .row {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; }}
    .field {{ margin-bottom: 10px; }}
    .field label {{ display: block; font-size: 13px; margin-bottom: 4px; color: #354948; font-weight: 600; }}
    .field input, .field textarea {{ width: 100%; padding: 9px 10px; border: 1px solid #c9d7d6; border-radius: 8px; background: #fbfdfc; font-family: "IBM Plex Sans", "Segoe UI", sans-serif; }}
    .field textarea {{ min-height: 70px; resize: vertical; }}
    .helper {{ font-size: 12px; color: var(--muted); margin-top: 3px; }}
    code, pre {{ background: #f2f6f5; border: 1px solid #d5e0df; border-radius: 8px; padding: 3px 6px; }}
    pre {{ white-space: pre-wrap; padding: 10px; max-height: 300px; overflow: auto; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td, th {{ border-bottom: 1px solid var(--line); text-align: left; padding: 8px 6px; font-size: 13px; vertical-align: top; }}
  </style>
</head>
<body>
<div class=\"wrap\">{body}</div>
</body>
</html>""".encode("utf-8")


def _safe(value: str) -> str:
    return html.escape(value or "")


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict | list) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class SetupHandler(BaseHTTPRequestHandler):
    def _send_html(self, status: int, title: str, body: str) -> None:
        page = _page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def _redirect(self, path: str) -> None:
        self.send_response(302)
        self.send_header("Location", path)
        self.end_headers()

    def _read_form(self) -> dict[str, str]:
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(content_length).decode("utf-8") if content_length else ""
        parsed = parse_qs(raw)
        return {key: (values[0] if values else "") for key, values in parsed.items()}

    def do_GET(self) -> None:
        apply_setup_env_defaults()
        parsed = urlparse(self.path)

        if parsed.path == "/":
            self._handle_home()
            return
        if parsed.path == "/status":
            self._handle_status_page()
            return
        if parsed.path.startswith("/component/"):
            component_id = parsed.path.split("/", 2)[2].strip()
            self._handle_component(component_id)
            return
        if parsed.path == "/env-preview":
            self._handle_env_preview()
            return
        if parsed.path == "/api/setup/overview":
            _json_response(self, 200, setup_overview())
            return
        if parsed.path == "/api/setup/status":
            try:
                from superagent.discovery import build_registry

                registry = build_registry()
                snapshot = build_setup_snapshot(registry.agent_cards())
            except Exception:
                snapshot = build_setup_snapshot([])
            _json_response(self, 200, snapshot)
            return
        if parsed.path == "/oauth/google/start":
            self._handle_oauth_start("google")
            return
        if parsed.path == "/oauth/microsoft/start":
            self._handle_oauth_start("microsoft")
            return
        if parsed.path == "/oauth/slack/start":
            self._handle_oauth_start("slack")
            return
        if parsed.path == "/oauth/google/callback":
            self._handle_oauth_callback("google", parse_qs(parsed.query))
            return
        if parsed.path == "/oauth/microsoft/callback":
            self._handle_oauth_callback("microsoft", parse_qs(parsed.query))
            return
        if parsed.path == "/oauth/slack/callback":
            self._handle_oauth_callback("slack", parse_qs(parsed.query))
            return
        self._send_html(404, "Not Found", "<h1>Not Found</h1>")

    def do_POST(self) -> None:
        apply_setup_env_defaults()
        parsed = urlparse(self.path)
        if parsed.path.startswith("/component/") and parsed.path.endswith("/save"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 3:
                component_id = parts[1]
                self._handle_component_save(component_id)
                return
        if parsed.path.startswith("/component/") and parsed.path.endswith("/toggle"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 3:
                component_id = parts[1]
                self._handle_component_toggle(component_id)
                return
        self._send_html(404, "Not Found", "<h1>Not Found</h1>")

    def _handle_home(self) -> None:
        overview = setup_overview()
        rows = overview["components"]
        cards = []
        oauth_links = []
        for item in rows:
            enabled_badge = '<span class="pill ok">enabled</span>' if item["enabled"] else '<span class="pill bad">disabled</span>'
            component = get_component(item["id"])
            oauth_path = str(component.get("oauth_start_path", "")).strip() if isinstance(component, dict) else ""
            oauth_button = ""
            if oauth_path:
                oauth_button = f' <a class="button ok" href="{_safe(oauth_path)}">OAuth Connect</a>'
                oauth_links.append(
                    f'<a class="button ok" href="{_safe(oauth_path)}">{_safe(item["title"])} OAuth</a>'
                )
            cards.append(
                f"""
                <div class="card">
                  <div class="row"><h3>{_safe(item['title'])}</h3>{enabled_badge}</div>
                  <p class="muted">{_safe(item['description'])}</p>
                  <p><span class="pill">{_safe(item['category'])}</span></p>
                  <p>Configured fields: <strong>{item['filled_fields']}/{item['total_fields']}</strong></p>
                  <a class="button" href="/component/{_safe(item['id'])}">Configure</a>
                  {oauth_button}
                </div>
                """
            )

        oauth_bar = ""
        if oauth_links:
            oauth_bar = '<div class="bar">' + "".join(oauth_links) + "</div>"

        body = f"""
        <h1>Superagent Setup Console</h1>
        <p class="muted">Complete setup for every platform component from one local web console with DB-backed persistence.</p>
        <div class="bar">
          <a class="button" href="/status">Service Status</a>
          <a class="button alt" href="/env-preview">Export Env Preview</a>
          <a class="button alt" href="/api/setup/overview">API: Overview</a>
          <a class="button alt" href="/api/setup/status">API: Runtime Status</a>
        </div>
        {oauth_bar}
        <div class="grid">{''.join(cards)}</div>
        """
        self._send_html(200, "Setup Console", body)

    def _handle_component(self, component_id: str) -> None:
        component = get_component(component_id)
        if not component:
            self._send_html(404, "Unknown Component", f"<h1>Unknown component: {_safe(component_id)}</h1>")
            return

        snapshot = get_setup_component_snapshot(component_id)
        values = snapshot.get("raw_values", {})
        fields_html = []
        for field in component.get("fields", []):
            key = field["key"]
            label = field.get("label", key)
            desc = field.get("description", "")
            secret = bool(field.get("secret", False))
            value = values.get(key, "")
            input_type = "password" if secret else "text"
            masked = "********" if secret and value else value
            fields_html.append(
                f"""
                <div class="field">
                  <label for="{_safe(key)}">{_safe(label)} <code>{_safe(key)}</code></label>
                  <input id="{_safe(key)}" name="{_safe(key)}" type="{input_type}" value="{_safe(masked)}" autocomplete="off" />
                  <div class="helper">{_safe(desc)}</div>
                </div>
                """
            )

        oauth_button = ""
        if component.get("oauth_start_path"):
            oauth_button = f'<a class="button ok" href="{_safe(component["oauth_start_path"])}">Run OAuth Connect</a>'

        toggle_label = "Disable Component" if snapshot.get("enabled", True) else "Enable Component"
        toggle_class = "warn" if snapshot.get("enabled", True) else "ok"
        body = f"""
        <div class="bar">
          <a class="button alt" href="/">Back to Setup Home</a>
          <a class="button alt" href="/status">Service Status</a>
          {oauth_button}
        </div>
        <h1>{_safe(component['title'])}</h1>
        <p class="muted">{_safe(component.get('description', ''))}</p>

        <div class="grid">
          <div class="card">
            <h2>Configuration</h2>
            <form method="post" action="/component/{_safe(component_id)}/save">
              {''.join(fields_html)}
              <button class="button" type="submit">Save Configuration</button>
            </form>
          </div>
          <div class="card">
            <h2>Component State</h2>
            <p>Enabled: <strong>{_safe(str(bool(snapshot.get('enabled', True))).lower())}</strong></p>
            <p>Configured fields: <strong>{snapshot.get('filled_fields', 0)}/{snapshot.get('total_fields', 0)}</strong></p>
            <form method="post" action="/component/{_safe(component_id)}/toggle">
              <input type="hidden" name="enabled" value="{'0' if snapshot.get('enabled', True) else '1'}" />
              <button class="button {toggle_class}" type="submit">{_safe(toggle_label)}</button>
            </form>
          </div>
        </div>
        """
        self._send_html(200, f"Setup - {component['title']}", body)

    def _handle_component_save(self, component_id: str) -> None:
        component = get_component(component_id)
        if not component:
            self._send_html(404, "Unknown Component", f"<h1>Unknown component: {_safe(component_id)}</h1>")
            return
        form = self._read_form()
        updates: dict[str, str] = {}
        for field in component.get("fields", []):
            key = field["key"]
            value = form.get(key, "")
            if field.get("secret", False) and value == "********":
                continue
            updates[key] = value
        save_component_values(component_id, updates)
        self._redirect(f"/component/{component_id}")

    def _handle_component_toggle(self, component_id: str) -> None:
        component = get_component(component_id)
        if not component:
            self._send_html(404, "Unknown Component", f"<h1>Unknown component: {_safe(component_id)}</h1>")
            return
        form = self._read_form()
        enabled = str(form.get("enabled", "1")).strip() == "1"
        set_component_enabled(component_id, enabled)
        self._redirect(f"/component/{component_id}")

    def _handle_status_page(self) -> None:
        try:
            from superagent.discovery import build_registry

            registry = build_registry()
            snapshot = build_setup_snapshot(registry.agent_cards())
        except Exception:
            snapshot = build_setup_snapshot([])
        services = snapshot.get("services", {})
        rows = []
        for name, item in services.items():
            badge = '<span class="pill ok">configured</span>' if item.get("configured") else '<span class="pill bad">not configured</span>'
            rows.append(
                f"<tr><td><code>{_safe(name)}</code></td><td>{badge}</td><td>{_safe(item.get('details', ''))}</td><td>{_safe(item.get('setup_hint', ''))}</td></tr>"
            )
        body = f"""
        <div class="bar"><a class="button alt" href="/">Back to Setup Home</a></div>
        <h1>Runtime Service Status</h1>
        <p class="muted">Live setup check against current environment, DB config, local binaries, and provider connectivity.</p>
        <div class="card">
          <p>Available agents: <strong>{len(snapshot.get('available_agents', []))}</strong></p>
          <p>Disabled agents: <strong>{len(snapshot.get('disabled_agents', {}))}</strong></p>
        </div>
        <div class="card">
          <table>
            <thead><tr><th>Service</th><th>Status</th><th>Details</th><th>Setup Hint</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
        """
        self._send_html(200, "Service Status", body)

    def _handle_env_preview(self) -> None:
        lines = export_env_lines(include_secrets=False)
        body = f"""
        <div class="bar"><a class="button alt" href="/">Back to Setup Home</a></div>
        <h1>Environment Export Preview</h1>
        <p class="muted">Preview DB-backed settings as dotenv lines (secrets masked by default).</p>
        <div class="card"><pre>{_safe(chr(10).join(lines) if lines else '# No DB settings found')}</pre></div>
        """
        self._send_html(200, "Env Export Preview", body)

    def _handle_oauth_start(self, provider: str) -> None:
        missing: list[str] = []
        if provider == "google":
            config = build_google_oauth_config()
            if not str(config.get("client_id", "")).strip():
                missing.append("GOOGLE_CLIENT_ID")
            if not str(config.get("client_secret", "")).strip():
                missing.append("GOOGLE_CLIENT_SECRET")
            if not str(config.get("redirect_uri", "")).strip():
                missing.append("GOOGLE_REDIRECT_URI")
            if not str(config.get("scopes", "")).strip():
                missing.append("GOOGLE_OAUTH_SCOPES")
        elif provider == "microsoft":
            config = build_microsoft_oauth_config()
            if not str(config.get("client_id", "")).strip():
                missing.append("MICROSOFT_CLIENT_ID")
            if not str(config.get("client_secret", "")).strip():
                missing.append("MICROSOFT_CLIENT_SECRET")
            if not str(config.get("redirect_uri", "")).strip():
                missing.append("MICROSOFT_REDIRECT_URI")
            if not str(config.get("scopes", "")).strip():
                missing.append("MICROSOFT_OAUTH_SCOPES")
        else:
            config = build_slack_oauth_config()
            if not str(config.get("client_id", "")).strip():
                missing.append("SLACK_CLIENT_ID")
            if not str(config.get("client_secret", "")).strip():
                missing.append("SLACK_CLIENT_SECRET")
            if not str(config.get("redirect_uri", "")).strip():
                missing.append("SLACK_REDIRECT_URI")
            if not str(config.get("scopes", "")).strip():
                missing.append("SLACK_OAUTH_SCOPES")

        if missing:
            body = (
                f"<h1>{html.escape(provider.title())} OAuth is not configured</h1>"
                "<p>Set the following environment variables in Setup UI or .env before connecting:</p>"
                f"<pre>{html.escape(chr(10).join(missing))}</pre>"
                '<p><a class="button" href="/">Return to setup home</a></p>'
            )
            self._send_html(400, "OAuth Not Configured", body)
            return

        state_token = issue_oauth_state_token()
        PENDING_STATES[state_token] = provider
        if provider == "google":
            url = build_google_oauth_start_url(state_token)
        elif provider == "microsoft":
            url = build_microsoft_oauth_start_url(state_token)
        else:
            url = build_slack_oauth_start_url(state_token)
        self.send_response(302)
        self.send_header("Location", url)
        self.end_headers()

    def _handle_oauth_callback(self, provider: str, query: dict) -> None:
        state_token = (query.get("state") or [""])[0]
        code = (query.get("code") or [""])[0]
        error = (query.get("error") or [""])[0]
        if error:
            self._send_html(400, "OAuth Error", f"<h1>OAuth failed</h1><p>{html.escape(error)}</p>")
            return
        if not code:
            self._send_html(400, "OAuth Error", "<h1>OAuth failed</h1><p>Missing authorization code.</p>")
            return
        if PENDING_STATES.get(state_token) != provider:
            self._send_html(400, "OAuth Error", "<h1>OAuth failed</h1><p>Invalid or expired state token.</p>")
            return
        try:
            if provider == "google":
                exchange_google_oauth_code(code)
            elif provider == "microsoft":
                exchange_microsoft_oauth_code(code)
            else:
                exchange_slack_oauth_code(code)
            PENDING_STATES.pop(state_token, None)
            body = (
                f"<h1>{html.escape(provider.title())} connected</h1>"
                "<p>Provider tokens are stored in the local SQLite setup database (and compatibility JSON output).</p>"
                '<p><a class="button" href="/">Return to setup home</a></p>'
            )
            self._send_html(200, "OAuth Complete", body)
        except Exception as exc:
            self._send_html(500, "OAuth Error", f"<h1>OAuth failed</h1><p>{html.escape(str(exc))}</p>")


def main() -> None:
    host = os.getenv("SETUP_UI_HOST", "127.0.0.1")
    port = int(os.getenv("SETUP_UI_PORT", "8787"))
    server = ThreadingHTTPServer((host, port), SetupHandler)
    print(f"Setup UI running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
