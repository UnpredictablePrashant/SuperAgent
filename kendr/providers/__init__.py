from __future__ import annotations

from typing import Any


def _auth():
    from . import auth

    return auth


def build_google_oauth_config(*args: Any, **kwargs: Any):
    return _auth().build_google_oauth_config(*args, **kwargs)


def build_google_oauth_start_url(*args: Any, **kwargs: Any):
    return _auth().build_google_oauth_start_url(*args, **kwargs)


def build_microsoft_oauth_config(*args: Any, **kwargs: Any):
    return _auth().build_microsoft_oauth_config(*args, **kwargs)


def build_microsoft_oauth_start_url(*args: Any, **kwargs: Any):
    return _auth().build_microsoft_oauth_start_url(*args, **kwargs)


def build_slack_oauth_config(*args: Any, **kwargs: Any):
    return _auth().build_slack_oauth_config(*args, **kwargs)


def build_slack_oauth_start_url(*args: Any, **kwargs: Any):
    return _auth().build_slack_oauth_start_url(*args, **kwargs)


def exchange_google_oauth_code(*args: Any, **kwargs: Any):
    return _auth().exchange_google_oauth_code(*args, **kwargs)


def exchange_microsoft_oauth_code(*args: Any, **kwargs: Any):
    return _auth().exchange_microsoft_oauth_code(*args, **kwargs)


def exchange_slack_oauth_code(*args: Any, **kwargs: Any):
    return _auth().exchange_slack_oauth_code(*args, **kwargs)


def get_google_access_token(*args: Any, **kwargs: Any):
    return _auth().get_google_access_token(*args, **kwargs)


def get_microsoft_graph_access_token(*args: Any, **kwargs: Any):
    return _auth().get_microsoft_graph_access_token(*args, **kwargs)


def get_secret(*args: Any, **kwargs: Any):
    return _auth().get_secret(*args, **kwargs)


def get_slack_bot_token(*args: Any, **kwargs: Any):
    return _auth().get_slack_bot_token(*args, **kwargs)


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
