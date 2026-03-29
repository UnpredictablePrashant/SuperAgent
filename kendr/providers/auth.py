from __future__ import annotations

from tasks.setup_registry import (
    build_google_oauth_config,
    build_google_oauth_start_url,
    build_microsoft_oauth_config,
    build_microsoft_oauth_start_url,
    build_slack_oauth_config,
    build_slack_oauth_start_url,
    exchange_google_oauth_code,
    exchange_microsoft_oauth_code,
    exchange_slack_oauth_code,
    get_google_access_token,
    get_microsoft_graph_access_token,
    get_secret,
    get_slack_bot_token,
)

__all__ = [
    "build_google_oauth_config",
    "build_google_oauth_start_url",
    "build_microsoft_oauth_config",
    "build_microsoft_oauth_start_url",
    "build_slack_oauth_config",
    "build_slack_oauth_start_url",
    "exchange_google_oauth_code",
    "exchange_microsoft_oauth_code",
    "exchange_slack_oauth_code",
    "get_google_access_token",
    "get_microsoft_graph_access_token",
    "get_secret",
    "get_slack_bot_token",
]
