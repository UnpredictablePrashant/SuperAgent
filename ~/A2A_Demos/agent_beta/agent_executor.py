import logging
import os
import sys
import time

from pathlib import Path

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent_core.json_utils import parse_json_or_none, to_pretty_json
from agent_core.openai_utils import create_openai_client_from_env, extract_openai_text
from agent_core.task_repositories import BetaTaskRepository


logger = logging.getLogger(__name__)


def _fallback_story(user_query: str, planner_brief: str) -> str:
    topic = user_query.strip() or "an unknown topic"
    return (
        f"At sunrise, Mira opened a notebook labeled '{topic}'. "
        "The first page held a brief from Alpha, outlining who this story should help and why it mattered. "
        "By noon, she translated the plan into scenes, turning abstract ideas into choices and consequences. "
        "By dusk, the audience could see the topic clearly through the journey, and the goal was fulfilled with a practical ending.\n\n"
        f"Planner brief used:\n{planner_brief or '(none provided)'}"
    )


class BetaAgentExecutor(AgentExecutor):
    def __init__(self) -> None:
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        self.client = create_openai_client_from_env()
        self.task_delay_seconds = float(os.environ.get("BETA_TASK_DELAY_SECONDS", "3"))
        db_path = os.environ.get("BETA_DB_PATH", os.path.join(os.path.dirname(__file__), "beta_tasks.db"))
        self.repo = BetaTaskRepository(db_path=db_path, task_delay_seconds=self.task_delay_seconds)

    async def _generate_story(self, user_query: str, planner_brief: str, raw_request: str) -> str:
        if not self.client:
            return _fallback_story(user_query, planner_brief)

        prompt = (
            "Alpha planner payload:\n"
            f"{raw_request}\n\n"
            "Generate the final story-mode content from the payload."
        )
        return await self._generate_llm_response(prompt)

    async def _generate_llm_response(self, query: str) -> str:
        if not self.client:
            return _fallback_story(query, "")

        try:
            llm_response = await self.client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are Beta, a content generator agent. "
                            "You receive a planner brief from Alpha and must generate content in story mode. "
                            "Requirements: write an engaging narrative with a clear beginning, middle, and end; "
                            "incorporate the topic, audience, tone, goal, and constraints from the brief; "
                            "keep it coherent and practical."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
            )
            text = extract_openai_text(llm_response)
            if text:
                return text
            return "The model returned an empty response."
        except Exception:
            logger.exception("BETA_OPENAI_CALL_FAILED")
            return "I could not generate a model response due to an OpenAI API error."

    async def _refresh_and_get_task(self, task_id: str) -> dict[str, object] | None:
        task = self.repo.get_task(task_id)
        if task is None:
            return None

        status = str(task.get("status", "unknown"))
        now = time.time()
        if status in {"completed", "failed"}:
            return task

        if now < float(task.get("ready_at", now)):
            if status == "queued":
                self.repo.update_task_status(task_id, "in_progress")
            return self.repo.get_task(task_id)

        user_query = str(task.get("user_query", ""))
        planner_brief = str(task.get("planner_brief", ""))
        try:
            story_text = await self._generate_story(
                user_query=user_query,
                planner_brief=planner_brief,
                raw_request=str(task.get("request_text", "")),
            )
            self.repo.update_task_status(task_id, "completed", result_text=story_text)
        except Exception as exc:
            logger.exception("BETA_TASK_COMPLETION_FAILED task_id=%s", task_id)
            self.repo.update_task_status(task_id, "failed", error_text=str(exc))

        return self.repo.get_task(task_id)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        request_text = context.get_user_input() or ""
        logger.info("BETA_RECEIVED_USER_INPUT=%s", request_text)
        logger.info("BETA_OPENAI_MODEL=%s", self.model)

        payload = parse_json_or_none(request_text)
        action = (payload or {}).get("action")

        if action == "submit_task":
            user_query = str(payload.get("user_query", ""))
            planner_brief = str(payload.get("planner_brief", ""))
            source_agent = str(payload.get("source_agent", "alpha"))
            task_id, status = self.repo.insert_task(
                source_agent=source_agent,
                request_text=request_text,
                user_query=user_query,
                planner_brief=planner_brief,
            )
            task = self.repo.get_task(task_id) or {}
            response_payload = {
                "action": "submit_task_result",
                "task_id": task_id,
                "status": status,
                "poll_after_seconds": self.task_delay_seconds,
                "created_at": task.get("created_at"),
                "updated_at": task.get("updated_at"),
                "completed_at": task.get("completed_at"),
            }
        elif action == "get_task_status":
            task_id = str(payload.get("task_id", ""))
            if not task_id:
                response_payload = {
                    "action": "task_status_result",
                    "task_id": "",
                    "status": "invalid_request",
                    "error": "task_id is required",
                }
            else:
                task = await self._refresh_and_get_task(task_id)
                if task is None:
                    response_payload = {
                        "action": "task_status_result",
                        "task_id": task_id,
                        "status": "not_found",
                    }
                else:
                    response_payload = {
                        "action": "task_status_result",
                        "task_id": task_id,
                        "status": task["status"],
                        "created_at": task.get("created_at"),
                        "ready_at": task.get("ready_at"),
                        "updated_at": task.get("updated_at"),
                        "completed_at": task.get("completed_at"),
                    }
                    if task["status"] == "completed":
                        response_payload["result"] = task.get("result_text") or ""
                    if task["status"] == "failed":
                        response_payload["error"] = task.get("error_text") or "Task failed"
        else:
            task_id, status = self.repo.insert_task(
                source_agent="alpha",
                request_text=request_text,
                user_query=request_text,
                planner_brief="",
            )
            task = self.repo.get_task(task_id) or {}
            response_payload = {
                "action": "submit_task_result",
                "task_id": task_id,
                "status": status,
                "poll_after_seconds": self.task_delay_seconds,
                "created_at": task.get("created_at"),
                "updated_at": task.get("updated_at"),
                "completed_at": task.get("completed_at"),
                "note": "Input was treated as a task submission because action was missing.",
            }

        response_text = to_pretty_json(response_payload)
        logger.info("BETA_SENDING_RESPONSE_TEXT=%s", response_text)
        await event_queue.enqueue_event(new_agent_text_message(response_text))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel not supported")
