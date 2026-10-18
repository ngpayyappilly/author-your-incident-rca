"""Helpers for deriving bad RCA documents from the good example.

Every mutation asserts its target text exists exactly once, so a fixture can
never silently stop testing what it claims to test when the example changes.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "sre-rca-author" / "scripts"
VALIDATOR = SCRIPT_DIR / "validate_rca.py"
EXAMPLE = ROOT / "sre-rca-author" / "assets" / "example-rca.md"

sys.path.insert(0, str(SCRIPT_DIR))
import validate_rca  # noqa: E402


def load_example():
    return EXAMPLE.read_text(encoding="utf-8")


def mutate(text, old, new):
    """Replace `old` with `new`, requiring exactly one occurrence of `old`."""
    count = text.count(old)
    assert count == 1, f"mutation target must occur exactly once, found {count}: {old[:70]!r}"
    return text.replace(old, new)


def remove_all(text, old):
    """Remove every occurrence of `old`, requiring at least one."""
    assert old in text, f"nothing to remove: {old[:70]!r}"
    return text.replace(old, "")


def regex_sub(text, pattern, repl, min_count=1):
    new, n = re.subn(pattern, repl, text)
    assert n >= min_count, f"pattern matched {n} time(s), expected >= {min_count}: {pattern!r}"
    return new


def drop_lines(text, prefix=None, contains=None, min_count=1):
    """Drop lines starting with `prefix` or containing `contains`."""
    out, dropped = [], 0
    for ln in text.split("\n"):
        if (prefix is not None and ln.startswith(prefix)) or (contains is not None and contains in ln):
            dropped += 1
        else:
            out.append(ln)
    assert dropped >= min_count, f"dropped {dropped} line(s), expected >= {min_count}"
    return "\n".join(out)


def _section_span(text, num):
    m = re.search(rf"^## {num}\. .*$", text, re.M)
    assert m, f"section {num} not found"
    nxt = re.search(r"^## \d+\. ", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    return m.start(), m.end(), end


def cut_section(text, num):
    """Remove a whole numbered section, heading included."""
    start, _, end = _section_span(text, num)
    return text[:start] + text[end:]


def edit_section_body(text, num, fn):
    """Apply fn(body) -> body to the text below a section heading."""
    _, body_start, end = _section_span(text, num)
    return text[:body_start] + fn(text[body_start:end]) + text[end:]


def codes(report):
    return {
        "errors": {e["code"] for e in report.errors},
        "warnings": {w["code"] for w in report.warnings},
    }
