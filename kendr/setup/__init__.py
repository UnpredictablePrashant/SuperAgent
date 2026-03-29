from __future__ import annotations

from typing import Any


def _integrations():
    from . import integrations

    return integrations


def build_google_oauth_config(*args: Any, **kwargs: Any):
    return _integrations().build_google_oauth_config(*args, **kwargs)


def build_microsoft_oauth_config(*args: Any, **kwargs: Any):
    return _integrations().build_microsoft_oauth_config(*args, **kwargs)


def build_setup_snapshot(*args: Any, **kwargs: Any):
    return _integrations().build_setup_snapshot(*args, **kwargs)


def build_slack_oauth_config(*args: Any, **kwargs: Any):
    return _integrations().build_slack_oauth_config(*args, **kwargs)


def issue_oauth_state_token(*args: Any, **kwargs: Any):
    return _integrations().issue_oauth_state_token(*args, **kwargs)


__all__ = [
    "build_google_oauth_config",
    "build_microsoft_oauth_config",
    "build_setup_snapshot",
    "build_slack_oauth_config",
    "issue_oauth_state_token",
]
