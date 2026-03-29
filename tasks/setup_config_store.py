from __future__ import annotations

import os
from datetime import datetime, timezone

from kendr.persistence import (
    delete_setup_config_value,
    get_setup_component,
    get_setup_config_value,
    list_setup_components,
    list_setup_config_values,
    upsert_setup_component,
    upsert_setup_config_value,
)
from kendr.setup.catalog import setup_component_catalog


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def component_catalog() -> list[dict]:
    return setup_component_catalog()


def component_index() -> dict[str, dict]:
    return {item["id"]: item for item in component_catalog()}


def get_component(component_id: str) -> dict:
    return component_index().get(component_id, {})


def _field_secret_map(component: dict) -> dict[str, bool]:
    fields = component.get("fields", []) if isinstance(component, dict) else []
    return {field["key"]: bool(field.get("secret", False)) for field in fields}


def apply_setup_env_defaults() -> None:
    for item in list_setup_config_values(include_secrets=True):
        key = str(item.get("config_key", "")).strip()
        value = str(item.get("config_value", ""))
        if key and value and not os.getenv(key, "").strip():
            os.environ[key] = value


def set_component_enabled(component_id: str, enabled: bool, notes: str = "") -> dict:
    upsert_setup_component(component_id, enabled=enabled, notes=notes, updated_at=_utc_now())
    return get_setup_component(component_id)


def get_component_values(component_id: str, *, include_secrets: bool = False) -> list[dict]:
    values = []
    for item in list_setup_config_values(include_secrets=include_secrets):
        if item.get("component_id") == component_id:
            values.append(item)
    return values


def save_component_values(component_id: str, values: dict[str, str]) -> dict:
    component = get_component(component_id)
    if not component:
        raise ValueError(f"Unknown component: {component_id}")
    secrets = _field_secret_map(component)
    updated = _utc_now()
    for key, value in values.items():
        raw = "" if value is None else str(value)
        if raw.strip() == "":
            delete_setup_config_value(component_id, key)
            continue
        upsert_setup_config_value(
            component_id,
            key,
            raw,
            is_secret=bool(secrets.get(key, False)),
            updated_at=updated,
        )
    return get_setup_component_snapshot(component_id)


def get_setup_component_snapshot(component_id: str) -> dict:
    component = get_component(component_id)
    if not component:
        return {}
    state = get_setup_component(component_id)
    values = get_component_values(component_id, include_secrets=True)
    current = {item["config_key"]: item["config_value"] for item in values}
    masked = {}
    secrets = _field_secret_map(component)
    filled = 0
    for field in component.get("fields", []):
        key = field["key"]
        raw_value = current.get(key, "")
        if raw_value:
            filled += 1
        if secrets.get(key, False):
            masked[key] = "********" if raw_value else ""
        else:
            masked[key] = raw_value
    enabled = True if not state else bool(state.get("enabled", 1))
    return {
        "component": component,
        "enabled": enabled,
        "notes": state.get("notes", "") if state else "",
        "updated_at": state.get("updated_at", "") if state else "",
        "values": masked,
        "raw_values": current,
        "filled_fields": filled,
        "total_fields": len(component.get("fields", [])),
    }


def setup_overview() -> dict:
    component_rows = []
    states = {item["component_id"]: item for item in list_setup_components()}
    for component in component_catalog():
        component_id = component["id"]
        row = get_setup_component_snapshot(component_id)
        env_status = []
        for field in component.get("fields", []):
            key = field["key"]
            env_present = bool(os.getenv(key, "").strip())
            db_present = bool(row.get("raw_values", {}).get(key, "").strip())
            env_status.append({"key": key, "env": env_present, "db": db_present})
        component_rows.append(
            {
                "id": component_id,
                "title": component.get("title", component_id),
                "category": component.get("category", "Other"),
                "description": component.get("description", ""),
                "enabled": row.get("enabled", True if component_id not in states else bool(states[component_id].get("enabled", 1))),
                "filled_fields": row.get("filled_fields", 0),
                "total_fields": row.get("total_fields", 0),
                "env_status": env_status,
            }
        )

    categories: dict[str, list[dict]] = {}
    for item in component_rows:
        categories.setdefault(item["category"], []).append(item)

    return {
        "generated_at": _utc_now(),
        "components": component_rows,
        "categories": categories,
    }


def export_env_lines(include_secrets: bool = False) -> list[str]:
    lines = []
    all_values = list_setup_config_values(include_secrets=True)
    for item in all_values:
        key = str(item.get("config_key", "")).strip()
        value = str(item.get("config_value", ""))
        is_secret = bool(int(item.get("is_secret", 0) or 0))
        if not key or not value:
            continue
        if is_secret and not include_secrets:
            lines.append(f"# {key}=********")
        else:
            escaped = value.replace("\n", "\\n")
            lines.append(f"{key}={escaped}")
    return sorted(set(lines))


def resolve_config_value(component_id: str, key: str, default: str = "") -> str:
    env_value = os.getenv(key, "").strip()
    if env_value:
        return env_value
    row = get_setup_config_value(component_id, key)
    value = str(row.get("config_value", "")).strip() if row else ""
    return value or default
