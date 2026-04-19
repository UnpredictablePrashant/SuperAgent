"""Built-in skill catalog for Kendr.

Each entry defines a system skill that users can install from the marketplace.
A skill is a reusable, composed capability — it may use LLM reasoning, code, or
multiple plugin actions to deliver a user-facing outcome.

Raw integration actions (send Slack message, create GitHub issue, etc.) live in
``kendr.plugin_manager``, not here.  A skill is higher-level than a plugin action.

Catalog skills have a fixed slug, category, description, and a built-in handler
that is invoked when agents call them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class CatalogSkill:
    id: str                          # unique catalog identifier (slug)
    name: str
    description: str
    category: str                    # Recommended | Documents | Communication | Planning | Travel
    icon: str                        # emoji
    tags: tuple[str, ...] = ()
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    requires_config: tuple[str, ...] = ()  # env vars needed
    example_input: dict = field(default_factory=dict)
    example_output: str = ""
    core: bool = False
    default_permissions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tags"] = list(d["tags"])
        d["requires_config"] = list(d["requires_config"])
        d["skill_type"] = "catalog"
        d["catalog_id"] = self.id
        d["is_core"] = bool(self.core)
        return d


# ---------------------------------------------------------------------------
# Catalog entries
# ---------------------------------------------------------------------------

CATALOG: tuple[CatalogSkill, ...] = (
    CatalogSkill(
        id="web-search",
        name="Web Search",
        description="Search the web for real-time information and return structured results with titles, snippets, and URLs.",
        category="Recommended",
        icon="🌐",
        tags=("search", "web", "research", "real-time"),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "default": 5, "description": "Number of results"},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "results": {"type": "array", "items": {"type": "object"}},
            },
        },
        example_input={"query": "latest version of a workplace leave policy"},
        example_output='{"query": "latest version of a workplace leave policy", "results": [{"title": "...", "url": "..."}]}',
        core=True,
        default_permissions={
            "requires_approval": False,
            "network": {"allow": True, "domains": ["duckduckgo.com"]},
        },
    ),
    CatalogSkill(
        id="desktop-automation",
        name="Desktop Automation",
        description="Preview or dispatch safe desktop actions for opening apps, chats, documents, and links.",
        category="Recommended",
        icon="🖥️",
        tags=("desktop", "automation", "apps", "local-first"),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list_apps", "open_app", "open_chat", "open_document", "open_url"],
                    "default": "list_apps",
                },
                "app": {
                    "type": "string",
                    "enum": ["generic", "whatsapp", "telegram", "microsoft_365"],
                    "default": "generic",
                },
                "access_mode": {"type": "string", "enum": ["sandbox", "full_access"], "default": "sandbox"},
                "app_name": {"type": "string"},
                "office_app": {"type": "string"},
                "phone_number": {"type": "string"},
                "handle": {"type": "string"},
                "message": {"type": "string"},
                "document_path": {"type": "string"},
                "url": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "access_mode": {"type": "string"},
                "preview_only": {"type": "boolean"},
                "dispatched": {"type": "boolean"},
                "plan": {"type": "object"},
            },
        },
        example_input={"action": "open_document", "document_path": "/path/to/meeting-notes.docx", "access_mode": "sandbox"},
        example_output='{"access_mode": "sandbox", "preview_only": true, "dispatched": false}',
        core=True,
        default_permissions={
            "requires_approval": False,
            "desktop": {
                "allow": True,
                "apps": ["generic", "whatsapp", "telegram", "microsoft_365"],
                "access_mode": "sandbox",
                "warn_on_full_access": True,
            },
        },
    ),
    CatalogSkill(
        id="pdf-reader",
        name="PDF Reader",
        description="Extract text from a PDF so it can be reviewed, summarized, or reused.",
        category="Documents",
        icon="📄",
        tags=("pdf", "documents", "extract", "text"),
        input_schema={
            "type": "object",
            "properties": {"file_path": {"type": "string", "description": "Path to the PDF file"}},
            "required": ["file_path"],
        },
        output_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}, "page_count": {"type": "integer"}},
        },
        example_input={"file_path": "/path/to/document.pdf"},
        example_output='{"text": "...", "page_count": 12}',
        core=True,
    ),
    CatalogSkill(
        id="file-reader",
        name="File Reader",
        description="Read local files such as text, markdown, JSON, CSV, PDF, DOCX, and office extracts.",
        category="Documents",
        icon="📂",
        tags=("files", "documents", "local", "read"),
        input_schema={
            "type": "object",
            "properties": {"file_path": {"type": "string", "description": "Path to the local file"}},
            "required": ["file_path"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "text": {"type": "string"},
                "metadata": {"type": "object"},
            },
        },
        example_input={"file_path": "/path/to/project-notes.md"},
        example_output='{"path": "/path/to/project-notes.md", "text": "# Notes\\n...", "metadata": {"type": "md"}}',
        core=True,
    ),
    CatalogSkill(
        id="file-finder",
        name="File Finder",
        description="Find local files by file name, path, or text content inside a chosen folder.",
        category="Documents",
        icon="🔎",
        tags=("files", "search", "local", "find"),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Filename, path, or text query"},
                "root_path": {"type": "string", "description": "Folder to search. Defaults to the current workspace."},
                "search_content": {"type": "boolean", "default": False, "description": "Also search inside text files."},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {"matches": {"type": "array", "items": {"type": "object"}}, "root_path": {"type": "string"}},
        },
        example_input={"query": "invoice", "root_path": "/path/to/documents", "search_content": True},
        example_output='{"root_path": "/path/to/documents", "matches": [{"path": "/path/to/documents/invoice-march.pdf"}]}',
        core=True,
    ),
    CatalogSkill(
        id="doc-summarizer",
        name="Doc Summarizer",
        description="Summarize local files and documents into a short brief, fuller summary, or action items.",
        category="Documents",
        icon="🗒️",
        tags=("summary", "documents", "pdf", "notes"),
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the local file"},
                "style": {"type": "string", "enum": ["short", "medium", "action_items"], "default": "medium"},
                "focus": {"type": "string", "description": "Optional focus or question for the summary"},
            },
            "required": ["file_path"],
        },
        output_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}, "path": {"type": "string"}},
        },
        example_input={"file_path": "/path/to/meeting-notes.pdf", "style": "action_items"},
        example_output='{"path": "/path/to/meeting-notes.pdf", "summary": "Action items:\\n1. ..."}',
        core=True,
    ),
    CatalogSkill(
        id="spreadsheet-basic",
        name="Spreadsheet Basic",
        description="Read CSV and Excel files, summarize sheets and totals, and answer simple spreadsheet questions.",
        category="Documents",
        icon="📊",
        tags=("spreadsheet", "csv", "excel", "totals"),
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the CSV or Excel file"},
                "question": {"type": "string", "description": "Optional question about the spreadsheet"},
                "max_rows": {"type": "integer", "default": 5},
            },
            "required": ["file_path"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "summary": {"type": "string"},
                "analysis": {"type": "string"},
            },
        },
        example_input={"file_path": "/path/to/budget.xlsx", "question": "Tell me the totals by category"},
        example_output='{"path": "/path/to/budget.xlsx", "analysis": "The largest category is ..."}',
        core=True,
    ),
    CatalogSkill(
        id="email-digest",
        name="Email Digest",
        description="Summarize recent inbox items and draft reply guidance when Gmail or Outlook is connected.",
        category="Communication",
        icon="📬",
        tags=("email", "digest", "gmail", "outlook"),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional inbox filter or search query"},
                "max_results": {"type": "integer", "default": 10},
                "draft_reply_to": {"type": "string", "description": "Optional sender or subject to draft a reply for"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}, "messages": {"type": "array", "items": {"type": "object"}}},
        },
        example_input={"query": "is:unread", "max_results": 8},
        example_output='{"summary": "You have 3 urgent emails ...", "messages": [{"subject": "..."}]}',
        core=True,
    ),
    CatalogSkill(
        id="calendar-agenda",
        name="Calendar Agenda",
        description="Show today or this week’s agenda and highlight conflicts, open blocks, and follow-ups.",
        category="Communication",
        icon="🗓️",
        tags=("calendar", "agenda", "schedule", "meetings"),
        input_schema={
            "type": "object",
            "properties": {
                "window": {"type": "string", "enum": ["today", "week"], "default": "today"},
                "timezone": {"type": "string", "description": "Optional timezone name or offset hint"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}, "events": {"type": "array", "items": {"type": "object"}}},
        },
        example_input={"window": "today"},
        example_output='{"summary": "You have 4 meetings today ...", "events": [{"title": "..."}]}',
        core=True,
    ),
    CatalogSkill(
        id="meeting-notes",
        name="Meeting Notes",
        description="Turn raw notes or a transcript into a clean summary, action items, and follow-up draft.",
        category="Communication",
        icon="📝",
        tags=("meetings", "notes", "action-items", "summary"),
        input_schema={
            "type": "object",
            "properties": {
                "notes": {"type": "string", "description": "Raw notes or transcript text"},
                "style": {"type": "string", "enum": ["summary", "action_items", "follow_up"], "default": "summary"},
            },
            "required": ["notes"],
        },
        output_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
        },
        example_input={"notes": "Met with Alex about launch timing...", "style": "action_items"},
        example_output='{"result": "1. Confirm launch date ..."}',
        core=True,
    ),
    CatalogSkill(
        id="todo-planner",
        name="Todo Planner",
        description="Turn a rough task list into a practical prioritized plan for today or this week.",
        category="Planning",
        icon="✅",
        tags=("tasks", "planning", "priorities", "todo"),
        input_schema={
            "type": "object",
            "properties": {
                "tasks": {"type": "string", "description": "Freeform task list"},
                "horizon": {"type": "string", "enum": ["today", "week"], "default": "today"},
            },
            "required": ["tasks"],
        },
        output_schema={
            "type": "object",
            "properties": {"plan": {"type": "string"}},
        },
        example_input={"tasks": "pay bills, finish report, call doctor, buy groceries", "horizon": "today"},
        example_output='{"plan": "Top priorities for today: ..."}',
        core=True,
    ),
    CatalogSkill(
        id="travel-helper",
        name="Travel Helper",
        description="Create a simple travel brief, checklist, and next steps for a trip or route.",
        category="Travel",
        icon="🧳",
        tags=("travel", "trip", "itinerary", "checklist"),
        input_schema={
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Trip details or travel question"},
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "date": {"type": "string", "description": "Travel date if known"},
                "provider": {"type": "string", "description": "Optional route data provider: planner or serpapi"},
            },
            "required": ["request"],
        },
        output_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}, "travel_data": {"type": "object"}},
        },
        example_input={"request": "Plan a simple weekend trip from Boston to New York by train", "origin": "Boston", "destination": "New York"},
        example_output='{"summary": "Best train options ...", "travel_data": {"source": "planner"}}',
        core=True,
    ),
    CatalogSkill(
        id="message-draft",
        name="Message Draft",
        description="Draft a message for email, WhatsApp, Telegram, or Slack without sending it.",
        category="Communication",
        icon="💬",
        tags=("message", "draft", "email", "chat"),
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "enum": ["email", "whatsapp", "telegram", "slack"], "default": "email"},
                "recipient": {"type": "string", "description": "Who the message is for"},
                "goal": {"type": "string", "description": "What the message should achieve"},
                "tone": {"type": "string", "default": "clear and polite"},
                "context": {"type": "string", "description": "Optional background details"},
            },
            "required": ["recipient", "goal"],
        },
        output_schema={
            "type": "object",
            "properties": {"draft": {"type": "string"}},
        },
        example_input={"channel": "email", "recipient": "team", "goal": "reschedule tomorrow's meeting", "tone": "friendly"},
        example_output="{\"draft\": \"Hi team, I need to move tomorrow's meeting ...\"}",
        core=True,
    ),
)

# Index by catalog id for O(1) lookup
CATALOG_BY_ID: dict[str, CatalogSkill] = {s.id: s for s in CATALOG}


def get_catalog_skill(catalog_id: str) -> CatalogSkill | None:
    return CATALOG_BY_ID.get(catalog_id)


def list_catalog_skills(category: str = "", q: str = "") -> list[dict]:
    results = []
    for skill in CATALOG:
        if category and skill.category != category:
            continue
        if q:
            ql = q.lower()
            if not any(ql in v for v in (skill.name.lower(), skill.description.lower(), skill.category.lower(), *skill.tags)):
                continue
        results.append(skill.to_dict())
    return results


def catalog_categories() -> list[str]:
    seen: dict[str, None] = {}
    for s in CATALOG:
        seen[s.category] = None
    return list(seen.keys())
