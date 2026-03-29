from __future__ import annotations

from kendr import AgentRuntime, build_registry
from kendr.cli import main as cli_main


REGISTRY = build_registry()
RUNTIME = AgentRuntime(REGISTRY)
AGENT_CARDS = REGISTRY.agent_cards()


def build_workflow():
    return RUNTIME.build_workflow()


def run_cli() -> int:
    return cli_main(["run"])


def main() -> int:
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
