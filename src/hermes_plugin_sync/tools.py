"""Claude Code tool name → Hermes toolset translation.

The mapping covers Claude Code's standard tool surface as of the source
script's last revision. Unknown tool names are surfaced to the caller so the
delegation skill can mention them in a warning footnote; explicitly dropped
tools (currently just ``Task``) are silently elided.
"""

from __future__ import annotations

from typing import Any

# Claude Code tool → Hermes toolset. Covers the common CC tools; unknowns are
# logged and dropped. Extend as plugins reveal new tools.
TOOL_MAP: dict[str, str] = {
    "Read": "file",
    "Grep": "file",
    "Glob": "file",
    "Edit": "file",
    "Write": "file",
    "NotebookEdit": "file",
    "Bash": "terminal",
    "WebFetch": "web",
    "WebSearch": "web",
}

# Tools that map to nothing actionable in Hermes - log and skip.
TOOL_DROP: set[str] = {
    "Task",  # Hermes sub-agents cannot delegate further.
}


def translate_tools(cc_tools: Any) -> tuple[list[str], list[str]]:
    """Translate a Claude Code ``tools`` field into Hermes toolsets.

    Accepts the three real-world shapes: a comma-separated string, a list of
    strings, or ``None``/empty. Returns ``(toolsets, unknown_tool_names)``.
    Toolsets are deduplicated while preserving first-seen order. If after
    translation no toolsets remain (e.g. all inputs were dropped or unknown)
    the default ``["file", "web"]`` is returned so the resulting delegation
    skill is still usable.
    """
    if not cc_tools:
        return ["file", "web"], []

    if isinstance(cc_tools, str):
        names = [t.strip() for t in cc_tools.split(",") if t.strip()]
    elif isinstance(cc_tools, list):
        names = [str(t).strip() for t in cc_tools if str(t).strip()]
    else:
        return ["file", "web"], []

    toolsets: list[str] = []
    unknown: list[str] = []
    for name in names:
        if name in TOOL_DROP:
            continue
        mapped = TOOL_MAP.get(name)
        if mapped:
            if mapped not in toolsets:
                toolsets.append(mapped)
        else:
            unknown.append(name)
    if not toolsets:
        toolsets = ["file", "web"]
    return toolsets, unknown
