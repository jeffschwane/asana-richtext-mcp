"""
Asana MCP server with full task CRUD and rich text support.

Wraps Asana's REST API using an OAuth access token or Personal Access Token.
Provides rich text comment/notes support (html_text) that the official Asana
MCP server lacks, plus task read/search/update operations for headless
automation.
"""

import html
import json
import os
import re
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("asana")

ASANA_API_BASE = "https://app.asana.com/api/1.0"


def _get_token() -> str:
    token = os.environ.get("ASANA_ACCESS_TOKEN") or os.environ.get("ASANA_PAT")
    if not token:
        raise ValueError(
            "No Asana token found. Set ASANA_ACCESS_TOKEN (OAuth) or "
            "ASANA_PAT (Personal Access Token)."
        )
    return token


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }


def _fix_double_encoded_html(text: str) -> str:
    """Unescape HTML entities when the caller has entity-encoded the markup.

    LLMs sometimes send ``&lt;strong&gt;`` instead of ``<strong>``.  Detect
    this by looking for encoded angle brackets and unescape once so the
    Asana API receives real HTML tags.
    """
    if "&lt;" in text and "&gt;" in text:
        text = html.unescape(text)
    return text


def _strip_unsupported_tags(text: str) -> str:
    """Replace <br>, <br/>, and <br /> with newlines.

    Asana's story API does not support <br> tags in html_text — their
    presence causes the entire comment to be entity-encoded and rendered
    as raw text.
    """
    return re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)


def _error_response(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except Exception:
        body = response.text
    return {"error": True, "status_code": response.status_code, "message": body}


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------


@mcp.tool()
def get_task(task_id: str, opt_fields: str = "") -> dict:
    """
    Get full task details by ID.

    Returns name, description, assignee, due dates, custom fields, projects,
    and dependencies. Use opt_fields to request specific fields.

    :param task_id: The Asana task GID.
    :param opt_fields: Comma-separated list of optional fields to include.
    :return: Task data from Asana.
    """
    params: dict[str, str] = {}
    if opt_fields:
        params["opt_fields"] = opt_fields

    response = httpx.get(
        f"{ASANA_API_BASE}/tasks/{task_id}",
        headers=_headers(),
        params=params,
        timeout=30.0,
    )
    if response.status_code != 200:
        return _error_response(response)
    return response.json()


@mcp.tool()
def get_tasks(
    project: str = "",
    section: str = "",
    tag: str = "",
    assignee: str = "",
    completed_since: str = "",
    modified_since: str = "",
    opt_fields: str = "",
    limit: int = 100,
    offset: str = "",
) -> dict:
    """
    List tasks filtered by project, section, tag, or assignee.

    At least one filter context (project, section, tag) is required.

    :param project: Project GID to list tasks from.
    :param section: Section GID to list tasks from.
    :param tag: Tag GID to list tasks from.
    :param assignee: User GID, email, or "me".
    :param completed_since: ISO 8601 datetime; only tasks completed after this.
    :param modified_since: ISO 8601 datetime; only tasks modified after this.
    :param opt_fields: Comma-separated optional fields.
    :param limit: Results per page (1-100).
    :param offset: Pagination offset token.
    :return: List of tasks from Asana.
    """
    if not any([project, section, tag]):
        return {"error": True, "status_code": 400, "message": "At least one of project, section, or tag is required"}

    params: dict[str, Any] = {"limit": min(max(limit, 1), 100)}
    if project:
        params["project"] = project
    if section:
        params["section"] = section
    if tag:
        params["tag"] = tag
    if assignee:
        params["assignee"] = assignee
    if completed_since:
        params["completed_since"] = completed_since
    if modified_since:
        params["modified_since"] = modified_since
    if opt_fields:
        params["opt_fields"] = opt_fields
    if offset:
        params["offset"] = offset

    response = httpx.get(
        f"{ASANA_API_BASE}/tasks",
        headers=_headers(),
        params=params,
        timeout=30.0,
    )
    if response.status_code != 200:
        return _error_response(response)
    return response.json()


@mcp.tool()
def search_tasks(
    workspace_id: str,
    text: str = "",
    projects_any: str = "",
    sections_any: str = "",
    assignee_any: str = "",
    completed: bool | None = None,
    custom_fields: str = "",
    sort_by: str = "modified_at",
    sort_ascending: bool = False,
    opt_fields: str = "",
    limit: int = 25,
) -> dict:
    """
    Advanced task search with filters.

    Supports text search, project/section/assignee filters, custom field
    filters, and sorting. The workspace_id is required.

    :param workspace_id: Workspace GID to search in.
    :param text: Text to search for in task name or description.
    :param projects_any: Comma-separated project GIDs.
    :param sections_any: Comma-separated section GIDs.
    :param assignee_any: Comma-separated user GIDs or "me".
    :param completed: Filter completed (True) or incomplete (False) tasks.
    :param custom_fields: JSON string of custom field filters, e.g. '{"field_gid": "value"}'.
    :param sort_by: Sort field: due_date, created_at, completed_at, likes, modified_at.
    :param sort_ascending: Sort ascending if True.
    :param opt_fields: Comma-separated optional fields.
    :param limit: Results to return (1-100).
    :return: Matching tasks from Asana.
    """
    params: dict[str, Any] = {
        "sort_by": sort_by,
        "sort_ascending": str(sort_ascending).lower(),
        "limit": min(max(limit, 1), 100),
    }
    if text:
        params["text"] = text
    if projects_any:
        params["projects.any"] = projects_any
    if sections_any:
        params["sections.any"] = sections_any
    if assignee_any:
        params["assignee.any"] = assignee_any
    if completed is not None:
        params["completed"] = str(completed).lower()
    if opt_fields:
        params["opt_fields"] = opt_fields

    if custom_fields:
        try:
            cf = json.loads(custom_fields)
            for field_gid, value in cf.items():
                params[f"custom_fields.{field_gid}.value"] = value
        except (json.JSONDecodeError, AttributeError):
            return {"error": True, "status_code": 400, "message": "Invalid custom_fields JSON"}

    response = httpx.get(
        f"{ASANA_API_BASE}/workspaces/{workspace_id}/tasks/search",
        headers=_headers(),
        params=params,
        timeout=30.0,
    )
    if response.status_code != 200:
        return _error_response(response)
    return response.json()


@mcp.tool()
def update_task(
    task_id: str,
    name: str = "",
    notes: str = "",
    html_notes: str = "",
    assignee: str = "",
    completed: bool | None = None,
    due_on: str = "",
    due_at: str = "",
    custom_fields: str = "",
) -> dict:
    """
    Update an existing Asana task.

    Supports changing name, notes, assignee, completion status, due dates,
    and custom fields. Only provided fields are updated.

    :param task_id: The Asana task GID to update.
    :param name: New task name.
    :param notes: New plain-text description.
    :param html_notes: New HTML description (wrapped in <body> tags).
    :param assignee: User GID, email, or "me".
    :param completed: Mark task as completed (True) or incomplete (False).
    :param due_on: Due date in YYYY-MM-DD format.
    :param due_at: Due datetime in ISO 8601 format.
    :param custom_fields: JSON string of custom fields, e.g. '{"field_gid": "value"}'.
    :return: Updated task data from Asana.
    """
    data: dict[str, Any] = {}
    if name:
        data["name"] = name
    if notes:
        data["notes"] = notes
    if html_notes:
        if not html_notes.strip().startswith("<body>"):
            html_notes = f"<body>{html_notes}</body>"
        data["html_notes"] = html_notes
    if assignee:
        data["assignee"] = assignee
    if completed is not None:
        data["completed"] = completed
    if due_on:
        data["due_on"] = due_on
    if due_at:
        data["due_at"] = due_at
    if custom_fields:
        try:
            data["custom_fields"] = json.loads(custom_fields)
        except json.JSONDecodeError:
            return {"error": True, "status_code": 400, "message": "Invalid custom_fields JSON"}

    response = httpx.put(
        f"{ASANA_API_BASE}/tasks/{task_id}",
        headers=_headers(),
        json={"data": data},
        timeout=30.0,
    )
    if response.status_code != 200:
        return _error_response(response)
    return response.json()


# ---------------------------------------------------------------------------
# Stories / Comments
# ---------------------------------------------------------------------------


@mcp.tool()
def get_stories_for_task(
    task_id: str, opt_fields: str = "", limit: int = 100, offset: str = ""
) -> dict:
    """
    Get task activity history (comments, status changes, system events).

    Returns chronological stories with authors and timestamps.

    :param task_id: The Asana task GID.
    :param opt_fields: Comma-separated optional fields.
    :param limit: Results per page (1-100).
    :param offset: Pagination offset token.
    :return: Stories/comments for the task.
    """
    params: dict[str, Any] = {"limit": min(max(limit, 1), 100)}
    if opt_fields:
        params["opt_fields"] = opt_fields
    if offset:
        params["offset"] = offset

    response = httpx.get(
        f"{ASANA_API_BASE}/tasks/{task_id}/stories",
        headers=_headers(),
        params=params,
        timeout=30.0,
    )
    if response.status_code != 200:
        return _error_response(response)
    return response.json()


@mcp.tool()
def create_rich_comment(task_id: str, html_text: str) -> dict:
    """
    Create a comment on an Asana task with rich text formatting.

    Uses Asana's html_text field to support formatting like:
    - Bold: <strong>text</strong>
    - Italic: <em>text</em>
    - Code: <code>text</code>
    - Links: <a href="url">text</a>
    - Lists: <ul><li>item</li></ul>

    The html_text should be wrapped in <body> tags.

    :param task_id: The Asana task GID to comment on.
    :param html_text: HTML-formatted comment text wrapped in <body> tags.
    :return: The created story/comment data from Asana.
    """
    html_text = _fix_double_encoded_html(html_text)
    html_text = _strip_unsupported_tags(html_text)

    if not html_text.strip().startswith("<body>"):
        html_text = f"<body>{html_text}</body>"

    response = httpx.post(
        f"{ASANA_API_BASE}/tasks/{task_id}/stories",
        headers=_headers(),
        json={"data": {"html_text": html_text}},
        timeout=30.0,
    )
    if response.status_code != 201:
        return _error_response(response)
    return response.json()


# ---------------------------------------------------------------------------
# Task Notes (rich text description)
# ---------------------------------------------------------------------------


@mcp.tool()
def update_task_notes(task_id: str, html_notes: str) -> dict:
    """
    Update an Asana task's notes/description with rich text formatting.

    Uses Asana's html_notes field to support formatting.

    :param task_id: The Asana task GID to update.
    :param html_notes: HTML-formatted notes wrapped in <body> tags.
    :return: The updated task data from Asana.
    """
    html_notes = _fix_double_encoded_html(html_notes)
    html_notes = _strip_unsupported_tags(html_notes)

    if not html_notes.strip().startswith("<body>"):
        html_notes = f"<body>{html_notes}</body>"

    response = httpx.put(
        f"{ASANA_API_BASE}/tasks/{task_id}",
        headers=_headers(),
        json={"data": {"html_notes": html_notes}},
        timeout=30.0,
    )
    if response.status_code != 200:
        return _error_response(response)
    return response.json()


# ---------------------------------------------------------------------------
# Typeahead Search
# ---------------------------------------------------------------------------


@mcp.tool()
def typeahead_search(
    workspace_id: str,
    query: str,
    resource_type: str = "task",
    count: int = 10,
    opt_fields: str = "",
) -> dict:
    """
    Typeahead search across an Asana workspace.

    Fast prefix-based search for tasks, projects, users, etc.

    :param workspace_id: Workspace GID to search in.
    :param query: Search query string.
    :param resource_type: Resource type: task, project, user, tag, portfolio.
    :param count: Max results (1-100).
    :param opt_fields: Comma-separated optional fields.
    :return: Matching resources from Asana.
    """
    params: dict[str, Any] = {
        "query": query,
        "resource_type": resource_type,
        "count": min(max(count, 1), 100),
    }
    if opt_fields:
        params["opt_fields"] = opt_fields

    response = httpx.get(
        f"{ASANA_API_BASE}/workspaces/{workspace_id}/typeahead",
        headers=_headers(),
        params=params,
        timeout=30.0,
    )
    if response.status_code != 200:
        return _error_response(response)
    return response.json()
