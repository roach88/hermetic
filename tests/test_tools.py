"""Tests for ``hermes_plugin_sync.tools``."""

from __future__ import annotations

from hermes_plugin_sync.tools import TOOL_DROP, TOOL_MAP, translate_tools


def test_tool_map_contents_match_source_script() -> None:
    # Pin TOOL_MAP - drift here breaks parity with the source script.
    assert TOOL_MAP == {
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


def test_tool_drop_contains_task() -> None:
    assert TOOL_DROP == {"Task"}


def test_translate_known_comma_string() -> None:
    toolsets, unknown = translate_tools("Read, Grep, Glob, Bash")
    assert toolsets == ["file", "terminal"]
    assert unknown == []


def test_translate_known_list() -> None:
    # Gap coverage: list-form input alongside the comma-string-form.
    toolsets, unknown = translate_tools(["Read", "Bash", "WebSearch"])
    assert toolsets == ["file", "terminal", "web"]
    assert unknown == []


def test_translate_unknown_tool_surfaced() -> None:
    toolsets, unknown = translate_tools("Read, Frobnicate")
    assert toolsets == ["file"]
    assert unknown == ["Frobnicate"]


def test_translate_none_returns_default() -> None:
    toolsets, unknown = translate_tools(None)
    assert toolsets == ["file", "web"]
    assert unknown == []


def test_translate_empty_string_returns_default() -> None:
    toolsets, unknown = translate_tools("")
    assert toolsets == ["file", "web"]
    assert unknown == []


def test_translate_empty_list_returns_default() -> None:
    # Gap coverage: an explicit empty list is "no tools requested" - treat
    # like None and serve the default.
    toolsets, unknown = translate_tools([])
    assert toolsets == ["file", "web"]
    assert unknown == []


def test_translate_dropped_tool_silent() -> None:
    toolsets, unknown = translate_tools("Task, Read")
    assert toolsets == ["file"]
    assert unknown == []


def test_translate_only_dropped_falls_back_to_default() -> None:
    # All inputs dropped → default toolset, not an empty list.
    toolsets, unknown = translate_tools("Task")
    assert toolsets == ["file", "web"]
    assert unknown == []


def test_translate_only_unknown_falls_back_to_default() -> None:
    toolsets, unknown = translate_tools("Frobnicate, Mystery")
    assert toolsets == ["file", "web"]
    assert unknown == ["Frobnicate", "Mystery"]


def test_translate_mixed_known_and_unknown() -> None:
    toolsets, unknown = translate_tools(["Read", "WebFetch", "Frobnicate"])
    assert toolsets == ["file", "web"]
    assert unknown == ["Frobnicate"]


def test_translate_invalid_type_returns_default() -> None:
    # Gap coverage: non-string, non-list input (e.g. dict from a malformed
    # plugin) should fall through to the default rather than crash.
    toolsets, unknown = translate_tools({"a": "b"})
    assert toolsets == ["file", "web"]
    assert unknown == []


def test_translate_dedupes_repeated_mappings() -> None:
    # Read and Grep both map to "file" - dedup, preserve first-seen order.
    toolsets, _ = translate_tools("Read, Grep, Bash, Edit")
    assert toolsets == ["file", "terminal"]
