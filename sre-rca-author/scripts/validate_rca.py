#!/usr/bin/env python3
"""Deterministic quality gate for RCA documents produced by the sre-rca-author skill.

Usage:
    python validate_rca.py rca.md [--json report.json] [--tier full|lite]

Exit code 0 = no errors (warnings allowed), 1 = errors found, 2 = usage/file error.
Standard library only.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone

ISO = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z"
ISO_RE = re.compile(ISO)
EVID_RE = re.compile(r"\[E-(\d{3,})\]")
TAG_RE = re.compile(r"\[(ASSUMPTION|UNVERIFIED)\]")
CF_RE = re.compile(r"\bCF-\d+\b")

SECTIONS = [
    ("1", "Incident Metadata"),
    ("2", "Executive Summary"),
    ("3", "Impact Analysis"),
    ("4", "Incident Timeline"),
    ("5", "Technical Analysis"),
    ("6", "Detection and Response Analysis"),
    ("7", "Action Items"),
    ("8", "Security Review"),
    ("9", "SRE Reliability Principles Review"),
    ("10", "Appendix and Sign-Off"),
]
LITE_REQUIRED = {"1", "2", "3", "4", "5", "6", "7"}

ANCHORS = [
    "Impact Start (UTC)",
    "Detected (UTC)",
    "Acknowledged (UTC)",
    "Mitigated (UTC)",
    "Resolved (UTC)",
]

BLAME_PATTERNS = [
    (r"\bhuman error\b", "'human error' is not a cause; describe the missing safeguard"),
    (r"\b(careless|carelessly|negligen\w*|sloppy|incompeten\w*|lazy)\b", "judgmental adjective"),
    (r"\bshould have (known|caught|noticed|checked|realized|seen)\b", "hindsight blame; state what the system did not surface"),
    (r"\b(fault of|to blame)\b", "blame language"),
    (r"\bblam(e|ed|ing)\b(?!less)", "blame language"),
    (r"\b(forgot|forgotten|neglected|ignored)\b", "attributes omission to a person; describe the process gap"),
    (r"\bfailed to (notice|follow|check|update|test|read)\b", "attributes failure to a person; describe the system gap"),
    (r"\broot cause (was|is) (a |an |the )?(person|engineer|developer|operator|admin|employee|team member)\b", "root cause names a person"),
]

VAGUE_ACTION_START = re.compile(
    r"^(be more|improve|ensure|review|monitor|investigate|consider|look into|pay attention|communicate better|"
    r"be careful|train)\b",
    re.I,
)
MEASURABLE_HINT = re.compile(
    r"(\d|alert|test|gate|canary|slo|dashboard|runbook|validation|automat|limit|timeout|circuit|rollback|game ?day|pipeline|schema)",
    re.I,
)
PLACEHOLDER_RE = re.compile(r"(\{\{.*?\}\}|\bTODO\b|\bTBD\b|\bFIXME\b|<insert|lorem ipsum)", re.I)


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = {}

    def err(self, code, msg, line=None):
        self.errors.append({"code": code, "message": msg, "line": line})

    def warn(self, code, msg, line=None):
        self.warnings.append({"code": code, "message": msg, "line": line})


def parse_ts(s):
    s = s.strip()
    fmt = "%Y-%m-%dT%H:%M:%SZ" if s.count(":") == 2 else "%Y-%m-%dT%H:%MZ"
    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)


def split_sections(lines):
    """Return {section_number: (start_line_idx, [lines])} keyed by '## N. Title' headings."""
    heads = []
    for i, ln in enumerate(lines):
        m = re.match(r"^##\s+(\d+)\.\s+(.+?)\s*$", ln)
        if m:
            heads.append((i, m.group(1), m.group(2)))
    out = {}
    for idx, (i, num, title) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        out[num] = {"title": title, "start": i, "lines": lines[i + 1:end]}
    return out


def table_rows(sec_lines):
    """Parse markdown tables in a block into list of (header_list, [row_lists], first_line_offset)."""
    tables = []
    i = 0
    while i < len(sec_lines):
        if sec_lines[i].lstrip().startswith("|") and i + 1 < len(sec_lines) and re.match(r"^\s*\|[\s:\-|]+\|\s*$", sec_lines[i + 1]):
            header = [c.strip() for c in sec_lines[i].strip().strip("|").split("|")]
            rows = []
            j = i + 2
            while j < len(sec_lines) and sec_lines[j].lstrip().startswith("|"):
                rows.append(([c.strip() for c in sec_lines[j].strip().strip("|").split("|")], j))
                j += 1
            tables.append((header, rows, i))
            i = j
        else:
            i += 1
    return tables


def check(text, tier):
    r = Report()
    lines = text.splitlines()

    # Placeholders
    for n, ln in enumerate(lines, 1):
        if PLACEHOLDER_RE.search(ln):
            r.err("PLACEHOLDER", f"Unresolved placeholder: {ln.strip()[:80]}", n)

    secs = split_sections(lines)

    # Title
    if not any(re.match(r"^#\s+RCA:\s+\S", ln) for ln in lines):
        r.err("TITLE", "Missing '# RCA: <title>' heading")

    # Required sections
    for num, title in SECTIONS:
        required = tier == "full" or num in LITE_REQUIRED
        if num not in secs:
            if required:
                r.err("SECTION_MISSING", f"Missing section '## {num}. {title}'")
            continue
        if secs[num]["title"].lower() != title.lower():
            r.warn("SECTION_TITLE", f"Section {num} titled '{secs[num]['title']}', expected '{title}'", secs[num]["start"] + 1)
        body = "\n".join(secs[num]["lines"]).strip()
        if len(body) < 20:
            r.err("SECTION_EMPTY", f"Section {num} ({title}) is empty")

    # Metadata
    meta = {}
    if "1" in secs:
        for header, rows, _ in table_rows(secs["1"]["lines"]):
            for cells, _ in rows:
                if len(cells) >= 2:
                    meta[cells[0]] = cells[1]
        for key in ["Incident ID", "Service(s)", "Severity", "RCA Owner", "Status", "Draft Confidence"]:
            if not meta.get(key):
                r.err("META_MISSING", f"Metadata field '{key}' missing or empty")
        if meta.get("Severity") and meta["Severity"] not in {"P1", "P2", "P3", "P4"}:
            r.warn("META_SEVERITY", f"Unexpected severity value '{meta['Severity']}'")
        if meta.get("Draft Confidence") and meta["Draft Confidence"] not in {"High", "Medium", "Low"}:
            r.err("META_CONFIDENCE", "Draft Confidence must be High, Medium, or Low")

        ts = {}
        for a in ANCHORS:
            v = meta.get(a, "")
            if not ISO_RE.fullmatch(v):
                r.err("META_TIMESTAMP", f"'{a}' must be ISO-8601 UTC like 2026-10-01T14:03:00Z (got '{v}')")
            else:
                ts[a] = parse_ts(v)
        if len(ts) == len(ANCHORS):
            ordered = [ts[a] for a in ANCHORS]
            if ordered != sorted(ordered):
                r.err("META_ORDER", "Anchor timestamps are not in order: start <= detected <= acknowledged <= mitigated <= resolved")
            mins = lambda a, b: round((ts[b] - ts[a]).total_seconds() / 60, 1)
            r.info["computed_metrics_minutes"] = {
                "TTD": mins("Impact Start (UTC)", "Detected (UTC)"),
                "TTA": mins("Detected (UTC)", "Acknowledged (UTC)"),
                "TTM": mins("Detected (UTC)", "Mitigated (UTC)"),
                "TTR": mins("Impact Start (UTC)", "Resolved (UTC)"),
            }

    # Executive summary length
    if "2" in secs:
        words = len(re.findall(r"\w+", " ".join(secs["2"]["lines"])))
        r.info["exec_summary_words"] = words
        if words > 230:
            r.warn("EXEC_LONG", f"Executive summary is {words} words; target under 200")

    # Impact quantified
    if "3" in secs:
        body = "\n".join(secs["3"]["lines"])
        if not re.search(r"\d", body):
            r.err("IMPACT_UNQUANTIFIED", "Impact Analysis contains no numbers")
        if not re.search(r"(error budget|budget)", body, re.I):
            r.warn("IMPACT_NO_BUDGET", "Impact Analysis does not mention error budget burn")

    # Timeline
    if "4" in secs:
        tables = table_rows(secs["4"]["lines"])
        rows = tables[0][1] if tables else []
        stamps = []
        for cells, off in rows:
            if cells and ISO_RE.fullmatch(cells[0]):
                stamps.append(parse_ts(cells[0]))
            else:
                r.err("TIMELINE_TS", f"Timeline row has non-ISO-UTC time: '{cells[0] if cells else ''}'", secs["4"]["start"] + 2 + off)
        if len(rows) < 5:
            r.err("TIMELINE_SHORT", f"Timeline has {len(rows)} rows; need at least 5")
        if stamps and stamps != sorted(stamps):
            r.err("TIMELINE_ORDER", "Timeline rows are not in chronological order")
        for cells, off in rows:
            if len(cells) >= 4 and not EVID_RE.search(cells[3]) and not TAG_RE.search(" ".join(cells)):
                r.warn("TIMELINE_NO_EVIDENCE", "Timeline row without evidence reference", secs["4"]["start"] + 2 + off)

    # Technical analysis
    cf_ids = set()
    if "5" in secs:
        body_lines = secs["5"]["lines"]
        body = "\n".join(body_lines)
        if not re.search(r"\*\*Root cause:?\*\*", body):
            r.err("ROOT_CAUSE_MISSING", "Section 5 needs a '**Root cause:**' statement")
        if not re.search(r"\*\*Trigger:?\*\*", body):
            r.err("TRIGGER_MISSING", "Section 5 needs a '**Trigger:**' statement separating trigger from root cause")
        for label, code in (("Root cause", "ROOT_CAUSE_UNCITED"), ("Trigger", "TRIGGER_UNCITED")):
            for ln in body_lines:
                if re.search(rf"\*\*{label}:?\*\*", ln):
                    if not (EVID_RE.search(ln) or TAG_RE.search(ln)):
                        r.err(code, f"The {label.lower()} statement must cite [E-nnn] or carry [ASSUMPTION]/[UNVERIFIED]")
                    break
        cf_ids = set(re.findall(r"\*\*(CF-\d+)\b", body))
        if not cf_ids:
            r.err("CF_MISSING", "No contributing factors (**CF-n ...**) found in Section 5")
        if tier == "full":
            if not re.search(r"###\s+5\.4", body):
                r.warn("FIVE_WHYS", "No '5.4 Five Whys' subsection found")
            if not re.search(r"###\s+5\.5", body):
                r.warn("HYPOTHESES", "No '5.5 Hypotheses Considered' subsection found")

        claims = [
            (i, ln) for i, ln in enumerate(body_lines)
            if ln.strip() and not ln.lstrip().startswith("#") and not re.match(r"^\s*\|[\s:\-|]+\|\s*$", ln)
            and not re.match(r"^\s*\|\s*ID\s*\|", ln) and len(ln.strip()) > 40
        ]
        covered = [c for c in claims if EVID_RE.search(c[1]) or TAG_RE.search(c[1])]
        cov = (len(covered) / len(claims)) if claims else 0.0
        r.info["technical_analysis_evidence_coverage"] = round(cov, 2)
        if claims and cov < 0.8:
            r.err("EVIDENCE_COVERAGE", f"Only {cov:.0%} of Section 5 claims carry [E-nnn] or [ASSUMPTION]/[UNVERIFIED] (need >= 80%)")
            for i, ln in claims:
                if not (EVID_RE.search(ln) or TAG_RE.search(ln)):
                    r.warn("UNCITED_CLAIM", f"Uncited: {ln.strip()[:90]}", secs["5"]["start"] + 2 + i)
                    break

    # Detection and response
    if "6" in secs:
        body = "\n".join(secs["6"]["lines"])
        for key in ["TTD", "TTA", "TTM", "TTR"]:
            if key not in body:
                r.warn("DETECTION_METRIC", f"Section 6 does not mention {key}")
        if not re.search(r"lucky", body, re.I):
            r.warn("NO_LUCK", "Section 6 has no 'Where we got lucky' entry (write 'None identified' if true)")

    # Action items
    action_cf = set()
    if "7" in secs:
        tables = [t for t in table_rows(secs["7"]["lines"]) if t[0] and t[0][0] == "ID"]
        if not tables:
            r.err("ACTIONS_TABLE", "Action items table (columns: ID | Action | Type | Addresses | Owner | Priority | Due | Tracking) not found")
        else:
            header, rows, _ = tables[0]
            expected = ["ID", "Action", "Type", "Addresses", "Owner", "Priority", "Due", "Tracking"]
            if header[:8] != expected:
                r.err("ACTIONS_COLUMNS", f"Action table columns must be {expected}")
            else:
                types = set()
                if not rows:
                    r.err("ACTIONS_EMPTY", "Action table has no rows")
                for cells, off in rows:
                    ln = secs["7"]["start"] + 2 + off
                    if len(cells) < 8:
                        r.err("ACTION_ROW", "Action row has fewer than 8 columns", ln)
                        continue
                    aid, act, typ, addr, owner, pri, due, trk = cells[:8]
                    if not re.fullmatch(r"A-\d+", aid):
                        r.err("ACTION_ID", f"Bad action ID '{aid}' (expected A-n)", ln)
                    if typ not in {"Prevent", "Detect", "Mitigate"}:
                        r.err("ACTION_TYPE", f"{aid}: Type must be Prevent, Detect, or Mitigate (got '{typ}')", ln)
                    types.add(typ)
                    found = set(CF_RE.findall(addr))
                    if not found:
                        r.err("ACTION_UNMAPPED", f"{aid}: 'Addresses' must reference at least one CF-n", ln)
                    action_cf |= found
                    if not owner or owner.lower() in {"tbd", "everyone", "team", "n/a", "-"}:
                        r.err("ACTION_OWNER", f"{aid}: needs a specific owner team or role", ln)
                    if pri not in {"P0", "P1", "P2"}:
                        r.err("ACTION_PRIORITY", f"{aid}: Priority must be P0, P1, or P2", ln)
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                        r.err("ACTION_DUE", f"{aid}: Due must be YYYY-MM-DD", ln)
                    if not trk or trk.lower() in {"tbd", "-", "n/a"}:
                        r.err("ACTION_TRACKING", f"{aid}: needs a tracking ID or TO-CREATE", ln)
                    if VAGUE_ACTION_START.match(act) and not MEASURABLE_HINT.search(act):
                        r.warn("ACTION_VAGUE", f"{aid}: action reads as vague/untestable: '{act[:70]}'", ln)
                if rows and tier == "full":
                    missing = {"Prevent", "Detect", "Mitigate"} - types
                    if missing:
                        r.warn("ACTION_TYPE_MIX", f"No action of type: {', '.join(sorted(missing))}")
        body7 = "\n".join(secs["7"]["lines"])
        accepted = set()
        m = re.search(r"\*\*Accepted risks:?\*\*(.*)", body7)
        if m:
            accepted = set(CF_RE.findall(m.group(1)))
        for cf in sorted(cf_ids - action_cf - accepted):
            r.err("CF_UNADDRESSED", f"{cf} has no action item and is not listed under Accepted risks")
        for cf in sorted(action_cf - cf_ids):
            r.err("ACTION_DANGLING_CF", f"Action references {cf}, which is not defined in Section 5.2")

    # Evidence ledger and citations
    ledger = set()
    if "10" in secs:
        for header, rows, _ in table_rows(secs["10"]["lines"]):
            if header and header[0] == "ID" and "Source" in header:
                for cells, _ in rows:
                    if cells and re.fullmatch(r"E-\d{3,}", cells[0]):
                        ledger.add(cells[0])
        if not ledger:
            r.err("LEDGER_MISSING", "Evidence Ledger (10.1) has no E-nnn rows")
    cited = set()
    for sec_no in ["1", "2", "3", "4", "5", "6", "7", "8", "9"]:
        if sec_no in secs:
            for m in EVID_RE.finditer("\n".join(secs[sec_no]["lines"])):
                cited.add(f"E-{m.group(1)}")
    for e in sorted(cited - ledger):
        r.err("CITATION_DANGLING", f"{e} is cited but not defined in the Evidence Ledger")
    for e in sorted(ledger - cited):
        r.warn("LEDGER_UNUSED", f"{e} is in the ledger but never cited")
    r.info["evidence_cited"] = len(cited)
    r.info["evidence_ledger_rows"] = len(ledger)

    # Blameless language (skip the evidence ledger, which may quote logs)
    scan_until = secs["10"]["start"] if "10" in secs else len(lines)
    for n, ln in enumerate(lines[:scan_until], 1):
        for pat, why in BLAME_PATTERNS:
            if re.search(pat, ln, re.I):
                r.warn("BLAMELESS", f"{why}: '{ln.strip()[:90]}'", n)
                break

    # Sign-off must not be pre-approved
    if "10" in secs:
        body = "\n".join(secs["10"]["lines"])
        if re.search(r"\|\s*(Approved|Signed)\s*\|", body, re.I):
            r.err("SIGNOFF_PREFILLED", "Sign-off block is pre-approved; the agent must leave decisions as Pending")

    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--tier", choices=["full", "lite"], default="full")
    args = ap.parse_args()
    try:
        text = open(args.path, encoding="utf-8").read()
    except OSError as e:
        print(f"cannot read {args.path}: {e}", file=sys.stderr)
        return 2

    rep = check(text, args.tier)
    result = {
        "file": args.path,
        "tier": args.tier,
        "passed": not rep.errors,
        "errors": rep.errors,
        "warnings": rep.warnings,
        "info": rep.info,
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

    print(f"{'PASS' if result['passed'] else 'FAIL'}: {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    for e in rep.errors:
        loc = f" (line {e['line']})" if e["line"] else ""
        print(f"  ERROR   [{e['code']}]{loc} {e['message']}")
    for w in rep.warnings:
        loc = f" (line {w['line']})" if w["line"] else ""
        print(f"  WARN    [{w['code']}]{loc} {w['message']}")
    if rep.info:
        print("  INFO   ", json.dumps(rep.info))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
