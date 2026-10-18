#!/usr/bin/env python3
"""Build sre-rca-author.skill from the sre-rca-author/ folder, deterministically.

Usage:
    python scripts/build_skill.py            # lint SKILL.md, then (re)write sre-rca-author.skill
    python scripts/build_skill.py --check    # lint, then fail (exit 1) if the committed bundle is stale
    python scripts/build_skill.py --lint     # lint SKILL.md front matter only

Output is byte-reproducible: sorted entries, fixed timestamps and permissions.
Exit codes: 0 ok, 1 lint failure or stale bundle, 2 usage/IO error. Standard library only.
"""
import argparse
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_NAME = "sre-rca-author"
SOURCE_DIR = REPO / SKILL_NAME
BUNDLE = REPO / f"{SKILL_NAME}.skill"

FIXED_DATE_TIME = (2020, 1, 1, 0, 0, 0)
EXCLUDE_DIRS = {"__pycache__", "evidence", "service-profiles", ".git", ".pytest_cache"}
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
DESCRIPTION_MAX = 1024


def lint_front_matter(source_dir):
    """Return a list of problems with <source_dir>/SKILL.md front matter (empty = ok)."""
    skill_md = source_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"{skill_md} not found"]
    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not m:
        return ["SKILL.md must start with a '---' delimited front matter block"]
    fields = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if kv:
            fields[kv.group(1)] = kv.group(2).strip()
    problems = []
    name = fields.get("name", "")
    if not name:
        problems.append("front matter is missing 'name'")
    elif name != source_dir.name:
        problems.append(f"front matter name '{name}' must match the folder name '{source_dir.name}'")
    elif not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        problems.append(f"name '{name}' must be lowercase letters, digits and hyphens")
    desc = fields.get("description", "")
    if not desc:
        problems.append("front matter is missing 'description'")
    elif len(desc) > DESCRIPTION_MAX:
        problems.append(f"description is {len(desc)} characters; the limit is {DESCRIPTION_MAX}")
    return problems


def collect_files(source_dir):
    """Sorted list of (archive_name, path) for every bundled file."""
    files = []
    for path in source_dir.rglob("*"):
        rel = path.relative_to(source_dir)
        if not path.is_file() or path.is_symlink():
            continue
        if set(rel.parts[:-1]) & EXCLUDE_DIRS:
            continue
        if path.name in EXCLUDE_NAMES or path.suffix in EXCLUDE_SUFFIXES:
            continue
        files.append((f"{source_dir.name}/{rel.as_posix()}", path))
    return sorted(files)


def build_bytes(source_dir):
    """Return the bundle as bytes (reproducible)."""
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for arcname, path in collect_files(source_dir):
            info = zipfile.ZipInfo(arcname, FIXED_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3  # unix, so external_attr is honoured everywhere
            zf.writestr(info, path.read_bytes())
    return buf.getvalue()


def describe_drift(bundle_path, source_dir):
    """Human-readable differences between a committed bundle and the folder."""
    if not bundle_path.is_file():
        return [f"{bundle_path.name} does not exist"]
    expected = {name: path.read_bytes() for name, path in collect_files(source_dir)}
    with zipfile.ZipFile(bundle_path) as zf:
        actual = {n: zf.read(n) for n in zf.namelist() if not n.endswith("/")}
    lines = []
    for n in sorted(expected.keys() - actual.keys()):
        lines.append(f"missing from bundle: {n}")
    for n in sorted(actual.keys() - expected.keys()):
        lines.append(f"stale entry in bundle: {n}")
    for n in sorted(expected.keys() & actual.keys()):
        if expected[n] != actual[n]:
            lines.append(f"content differs: {n}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="fail if the committed bundle differs from a fresh build")
    group.add_argument("--lint", action="store_true", help="only lint SKILL.md front matter")
    args = ap.parse_args(argv)

    problems = lint_front_matter(SOURCE_DIR)
    for p in problems:
        print(f"LINT  {p}", file=sys.stderr)
    if problems:
        return 1
    if args.lint:
        print("lint ok")
        return 0

    try:
        fresh = build_bytes(SOURCE_DIR)
    except OSError as e:
        print(f"cannot read sources: {e}", file=sys.stderr)
        return 2

    if args.check:
        current = BUNDLE.read_bytes() if BUNDLE.is_file() else None
        if current == fresh:
            print(f"{BUNDLE.name} is up to date ({len(collect_files(SOURCE_DIR))} files)")
            return 0
        print(f"{BUNDLE.name} is out of date. Run: python scripts/build_skill.py", file=sys.stderr)
        try:
            for line in describe_drift(BUNDLE, SOURCE_DIR):
                print(f"  {line}", file=sys.stderr)
        except zipfile.BadZipFile:
            print("  committed bundle is not a valid zip", file=sys.stderr)
        return 1

    BUNDLE.write_bytes(fresh)
    print(f"wrote {BUNDLE.name}: {len(collect_files(SOURCE_DIR))} files, {len(fresh)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
