import asyncio
import logging
import os
import sys

from pathlib import Path

import httpx

from a2a.client import A2ACardResolver, A2AClient
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent_core.a2a_utils import send_text_message
from agent_core.a2a_utils import resolve_polling_config
from agent_core.json_utils import parse_json_or_none, to_json
from agent_core.openai_utils import create_openai_client_from_env, extract_openai_text
from agent_core.task_repositories import AlphaTaskRepository


logger = logging.getLogger(__name__)


class AlphaAgentExecutor(AgentExecutor):
    def __init__(self) -> None:
        self.beta_url = os.environ.get("BETA_AGENT_URL", "http://127.0.0.1:8102")
        self.gamma_url = os.environ.get("GAMMA_AGENT_URL", os.environ.get("AGENT_GAMMA_URL", "http://127.0.0.1:8103"))
        self.worker_agent = os.environ.get("ALPHA_WORKER_AGENT", "beta").strip().lower() or "beta"
        self.ecosystem_db_path = os.environ.get(
            "ECOSYSTEM_DB_PATH",
            str((ROOT_DIR / "ecosystem" / "ecosystem.db").resolve()),
        )
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        self.client = create_openai_client_from_env()
        self.default_poll_interval_seconds = 20.0
        self.default_max_poll_attempts = int(os.environ.get("ALPHA_MAX_POLL_ATTEMPTS", "5"))
        db_path = os.environ.get("ALPHA_DB_PATH", os.path.join(os.path.dirname(__file__), "alpha_tasks.db"))
        self.repo = AlphaTaskRepository(db_path=db_path)

    def _resolve_worker_url(self, worker_agent: str) -> str:
        worker = worker_agent.strip().lower()
        if worker == "beta":
            return self.beta_url
        if worker == "gamma":
            return self.gamma_url
        resolved = os.environ.get(
            f"{worker.upper()}_AGENT_URL",
            os.environ.get(f"AGENT_{worker.upper()}_URL", ""),
        )
        return resolved or self.beta_url

    async def _create_plan(self, user_query: str) -> str:
        if not self.client:
            return (
                "Planner Brief:\n"
                f"- Topic: {user_query}\n"
                "- Audience: General readers\n"
                "- Tone: Engaging and clear\n"
                "- Story Goal: Explain the topic through a short narrative\n"
                "- Constraints: Keep it concise, coherent, and practical"
            )

        try:
            llm_response = await self.client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are Alpha, a planner agent. Convert user requests into a concise content brief "
                            "for a writing agent. Return plain text in exactly this format:\n"
                            "Planner Brief:\n"
                            "- Topic: ...\n"
                            "- Audience: ...\n"
                            "- Tone: ...\n"
                            "- Story Goal: ...\n"
                            "- Constraints: ..."
                        ),
                    },
                    {"role": "user", "content": user_query},
                ],
            )
            plan_text = extract_openai_text(llm_response)
            if plan_text:
                return plan_text
        except Exception:
            logger.exception("ALPHA_PLANNER_OPENAI_CALL_FAILED")

        return (
            "Planner Brief:\n"
            f"- Topic: {user_query}\n"
            "- Audience: General readers\n"
            "- Tone: Engaging and clear\n"
            "- Story Goal: Explain the topic through a short narrative\n"
            "- Constraints: Keep it concise, coherent, and practical"
        )

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_query = context.get_user_input() or ""
        logger.info("ALPHA_RECEIVED_USER_INPUT=%s", user_query)
        logger.info("ALPHA_OPENAI_MODEL=%s", self.model)

        planner_brief = await self._create_plan(user_query)
        logger.info("ALPHA_PLANNER_BRIEF=%s", planner_brief)

        final_status = "unknown"
        beta_task_id = ""
        beta_result = ""
        poll_attempts_used = 0
        latest_beta_payload: dict[str, object] = {}
        worker_agent = self.worker_agent
        worker_url = self._resolve_worker_url(worker_agent)
        poll_interval_seconds, max_poll_attempts = resolve_polling_config(
            env_map=os.environ,
            caller_agent="alpha",
            target_agent=worker_agent,
            default_interval_seconds=self.default_poll_interval_seconds,
            default_max_attempts=self.default_max_poll_attempts,
            ecosystem_db_path=self.ecosystem_db_path,
        )

        async with httpx.AsyncClient(timeout=30.0) as httpx_client:
            resolver = A2ACardResolver(httpx_client=httpx_client, base_url=worker_url)
            beta_card = await resolver.get_agent_card()
            logger.info(
                "ALPHA_RESOLVED_%s_AGENT_CARD=%s",
                worker_agent.upper(),
                beta_card.model_dump_json(indent=2, exclude_none=True),
            )

            client = A2AClient(httpx_client=httpx_client, agent_card=beta_card)

            submit_payload = {
                "action": "submit_task",
                "source_agent": "alpha",
                "user_query": user_query,
                "planner_brief": planner_brief,
            }
            submit_text = await send_text_message(
                client=client,
                text=to_json(submit_payload),
                logger=logger,
                request_log=f"ALPHA_TO_{worker_agent.upper()}_SEND_MESSAGE_REQUEST=%s",
                response_log=f"{worker_agent.upper()}_TO_ALPHA_SEND_MESSAGE_RESPONSE=%s",
            )
            submit_result = parse_json_or_none(submit_text) or {}
            latest_beta_payload = submit_result

            beta_task_id = str(submit_result.get("task_id", ""))
            final_status = str(submit_result.get("status", "invalid_response"))

            local_id = self.repo.insert_task(
                user_query=user_query,
                planner_brief=planner_brief,
                beta_task_id=beta_task_id,
                beta_status=final_status,
                beta_last_payload=submit_result,
            )

            if beta_task_id:
                for attempt in range(1, max_poll_attempts + 1):
                    poll_attempts_used = attempt
                    await asyncio.sleep(poll_interval_seconds)
                    poll_payload = {
                        "action": "get_task_status",
                        "task_id": beta_task_id,
                    }
                    poll_text = await send_text_message(
                        client=client,
                        text=to_json(poll_payload),
                        logger=logger,
                        request_log=f"ALPHA_TO_{worker_agent.upper()}_SEND_MESSAGE_REQUEST=%s",
                        response_log=f"{worker_agent.upper()}_TO_ALPHA_SEND_MESSAGE_RESPONSE=%s",
                    )
                    poll_result = parse_json_or_none(poll_text) or {}
                    latest_beta_payload = poll_result

                    final_status = str(poll_result.get("status", "invalid_response"))
                    if final_status == "completed":
                        beta_result = str(poll_result.get("result", ""))
                    self.repo.update_task(
                        local_id=local_id,
                        beta_status=final_status,
                        beta_last_payload=poll_result,
                        beta_result=beta_result or None,
                    )

                    if final_status in {"completed", "failed", "not_found", "invalid_request"}:
                        if final_status == "failed" and not beta_result:
                            beta_result = str(poll_result.get("error", "Task failed"))
                        break

        final_text = (
            "Alpha Agent response:\n"
            f"- Your input: {user_query}\n"
            f"- Planner brief:\n{planner_brief}\n"
            f"- Worker agent: {worker_agent}\n"
            f"- Worker task_id: {beta_task_id or '(missing)'}\n"
            f"- Final status: {final_status}\n"
            f"- Poll interval seconds: {poll_interval_seconds}\n"
            f"- Poll attempts used: {poll_attempts_used}/{max_poll_attempts}\n"
            f"- Worker created_at: {latest_beta_payload.get('created_at')}\n"
            f"- Worker updated_at: {latest_beta_payload.get('updated_at')}\n"
            f"- Worker completed_at: {latest_beta_payload.get('completed_at')}\n"
            f"- Worker result: {beta_result if beta_result else '(not ready yet)'}"
        )
        logger.info("ALPHA_FINAL_RESPONSE_TEXT=%s", final_text)
        await event_queue.enqueue_event(new_agent_text_message(final_text))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel not supported")
