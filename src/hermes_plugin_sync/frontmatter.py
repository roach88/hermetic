"""Frontmatter parsing/rendering and content hashing helpers.

These helpers are shared between skill and agent migration. The hashing
helpers live here too because frontmatter and content hashing are coupled in
practice: the manifest stores SHA-256 of the SKILL.md (which includes its
frontmatter) as the unit of comparison.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

# Matches a YAML frontmatter block at the start of a string. The pattern uses
# ``re.DOTALL`` so ``.`` spans newlines inside the YAML body.
_FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown string into ``(frontmatter_dict, body)``.

    Returns ``({}, text)`` if no frontmatter fences are present or if the YAML
    inside the fences fails to parse. The latter is intentionally non-fatal:
    a malformed frontmatter should not crash the whole sync.
    """
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm_raw, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError:
        fm = {}
    if not isinstance(fm, dict):
        # Something like ``---\n[1,2,3]\n---`` parses but isn't a dict.
        return {}, text
    return fm, body


def render_frontmatter(fm: dict[str, Any], body: str) -> str:
    """Re-emit a markdown string with ``fm`` serialized as YAML frontmatter."""
    fm_yaml = yaml.safe_dump(fm, sort_keys=False).strip()
    return f"---\n{fm_yaml}\n---\n\n{body.lstrip()}"


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at ``path``."""
    return sha256_bytes(path.read_bytes())
