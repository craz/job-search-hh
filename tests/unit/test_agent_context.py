"""Regression tests for bounded Cursor context and protected HH runtime state."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_only_minimal_global_cursor_rule_is_always_applied() -> None:
    """Browser-specific instructions must not enter every unrelated request."""
    always = []
    for rule in (ROOT / ".cursor" / "rules").glob("*.mdc"):
        if re.search(r"(?m)^alwaysApply:\s*true\s*$", rule.read_text(encoding="utf-8")):
            always.append(rule.name)

    assert sorted(always) == ["00-global.mdc"]


def test_profile_tokens_and_local_state_are_excluded_from_cursor_context() -> None:
    """Sensitive browser state must remain outside automatic indexing and requests."""
    private_patterns = (ROOT / ".cursorignore").read_text(encoding="utf-8")
    index_patterns = (ROOT / ".cursorindexingignore").read_text(encoding="utf-8")

    for required in (".local/", "browser-profile/", "tokens/", "data/", "logs/"):
        assert required in private_patterns
    for required in (".local/", "browser-profile/", "data/", "logs/"):
        assert required in index_patterns
