"""Tests for ``hermetic.frontmatter``."""

from __future__ import annotations

from pathlib import Path

from hermetic.frontmatter import (
    parse_frontmatter,
    render_frontmatter,
    sha256_bytes,
    sha256_file,
)


def test_parse_valid_frontmatter() -> None:
    text = "---\nname: x\ndescription: y\n---\nbody text"
    fm, body = parse_frontmatter(text)
    assert fm == {"name": "x", "description": "y"}
    assert body == "body text"


def test_parse_no_frontmatter_returns_original() -> None:
    text = "# Heading\n\nNo fences here."
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_parse_malformed_yaml_returns_empty_fm() -> None:
    text = "---\nname: : : invalid\n---\nbody"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    # Body should still be the part after the closing fence.
    assert body == "body"


def test_parse_non_dict_yaml_returns_empty_fm() -> None:
    # Gap coverage: ``--- [1,2,3] ---`` parses to a list, not a dict; we
    # should refuse it rather than ship a list to callers expecting .get().
    text = "---\n[1, 2, 3]\n---\nbody"
    fm, body = parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_render_roundtrip() -> None:
    fm = {"name": "demo", "description": "test"}
    rendered = render_frontmatter(fm, "Hello world.\n")
    fm2, body2 = parse_frontmatter(rendered)
    assert fm2 == fm
    assert body2.strip() == "Hello world."


def test_render_strips_leading_body_whitespace() -> None:
    rendered = render_frontmatter({"a": 1}, "\n\n\nhello")
    assert rendered == "---\na: 1\n---\n\nhello"


def test_sha256_bytes_is_stable() -> None:
    assert sha256_bytes(b"hello") == sha256_bytes(b"hello")
    assert sha256_bytes(b"hello") != sha256_bytes(b"world")


def test_sha256_file_matches_bytes(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    assert sha256_file(p) == sha256_bytes(b"abc")
