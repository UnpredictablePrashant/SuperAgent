import logging
import sys

import uvicorn

from pathlib import Path

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agent_executor import BetaAgentExecutor

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent_core.env_loader import load_env_chain


def build_agent_card() -> AgentCard:
    skill = AgentSkill(
        id="beta_story_generator",
        name="Beta Story Generator",
        description="Generates story-mode content from Alpha's planner brief.",
        tags=["story", "generator", "a2a"],
        examples=["turn this brief into a story", "write a narrative from planner inputs"],
    )

    return AgentCard(
        name="Beta Agent",
        description="Content generator that writes story-mode outputs from Alpha planner briefs.",
        url="http://127.0.0.1:8102/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )


if __name__ == "__main__":
    load_env_chain(agent_dir=Path(__file__).resolve().parent, root_dir=ROOT_DIR)
    logging.basicConfig(level=logging.INFO)
    card = build_agent_card()

    request_handler = DefaultRequestHandler(
        agent_executor=BetaAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    app = A2AStarletteApplication(agent_card=card, http_handler=request_handler)
    uvicorn.run(app.build(), host="0.0.0.0", port=8102, log_level="info")
