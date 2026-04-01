import os

from pathlib import Path


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cleaned = value.strip().strip('"').strip("'")
        out[key.strip()] = cleaned
    return out


def load_env_chain(agent_dir: Path, root_dir: Path) -> dict[str, str]:
    """
    Load environment keys with this precedence for missing OS vars:
    1) agent_dir/.env
    2) root_dir/.env (fallback)
    3) existing process environment wins over both
    """
    root_values = _parse_dotenv(root_dir / ".env")
    agent_values = _parse_dotenv(agent_dir / ".env")

    merged = dict(root_values)
    merged.update(agent_values)

    for key, value in merged.items():
        if key not in os.environ:
            os.environ[key] = value

    return merged
