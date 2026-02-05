"""
Minimal Asana MCP server that supports html_text for rich text comments.

This wraps Asana's REST API to provide html_text support that the official
Asana MCP server currently lacks.
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("asana-richtext")

ASANA_API_BASE = "https://app.asana.com/api/1.0"


def _get_token() -> str:
    """Get Asana PAT from environment variable."""
    token = os.environ.get("ASANA_PAT")
    if not token:
        raise ValueError(
            "ASANA_PAT environment variable not set. "
            "Create a Personal Access Token at https://app.asana.com/0/my-apps"
        )
    return token


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
    token = _get_token()

    # Ensure html_text is wrapped in body tags
    if not html_text.strip().startswith("<body>"):
        html_text = f"<body>{html_text}</body>"

    response = httpx.post(
        f"{ASANA_API_BASE}/tasks/{task_id}/stories",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"data": {"html_text": html_text}},
        timeout=30.0,
    )

    if response.status_code != 201:
        return {
            "error": True,
            "status_code": response.status_code,
            "message": response.json(),
        }

    return response.json()


@mcp.tool()
def update_task_notes(task_id: str, html_notes: str) -> dict:
    """
    Update an Asana task's notes/description with rich text formatting.

    Uses Asana's html_notes field to support formatting.

    :param task_id: The Asana task GID to update.
    :param html_notes: HTML-formatted notes wrapped in <body> tags.
    :return: The updated task data from Asana.
    """
    token = _get_token()

    # Ensure html_notes is wrapped in body tags
    if not html_notes.strip().startswith("<body>"):
        html_notes = f"<body>{html_notes}</body>"

    response = httpx.put(
        f"{ASANA_API_BASE}/tasks/{task_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"data": {"html_notes": html_notes}},
        timeout=30.0,
    )

    if response.status_code != 200:
        return {
            "error": True,
            "status_code": response.status_code,
            "message": response.json(),
        }

    return response.json()
