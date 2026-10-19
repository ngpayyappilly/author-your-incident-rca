#!/usr/bin/env python3
"""Deterministic quality gate for RCA documents produced by the sre-rca-author skill.

Usage:
    python validate_rca.py rca.md [--json report.json] [--tier full|lite] [--strict]

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

LEDGER_ID_RE = re.compile(r"E-\d{3,}")
DERIVED_RE = re.compile(r"\[derived:\s*([^\]]*)\]", re.I)
# Text that looks numeric but is not a measured quantity; blanked out before numbers are extracted.
NON_QUANTITY_RES = [
    re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.]+Z?"),         # ISO timestamps
    re.compile(r"\d{4}-\d{2}-\d{2}"),                    # dates
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?Z?"),         # clock times
    re.compile(r"\b[A-Z]{1,5}-\d+\b"),                    # E-001, CF-1, A-1, ADO-4412, H-2
    re.compile(r"\bINC\d+\b"),                            # incident numbers
    re.compile(r"\bP[0-4]\b"),                             # severities and priorities
    re.compile(r"\b[1-5]xx\b", re.I),                      # HTTP status classes
]
NUMBER_RE = re.compile(r"(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?)(?![\w]*\d)")
SCALE_WORDS = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "billion": 1e9, "b": 1e9}
LEDGER_RANGE_RE = re.compile(
    rf"^\s*({ISO})\s*(?:-|\u2013|to)\s*({ISO}|\d{{2}}:\d{{2}}(?::\d{{2}})?Z)\s*$"
)

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


def number_values(text):
    """Numeric values in text, including scaled readings ('1.41 million' -> 1.41 and 1410000)."""
    values = []
    for m in NUMBER_RE.finditer(text):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        values.append(v)
        word = re.match(r"\s*([A-Za-z]+)", text[m.end():])
        if word and word.group(1).lower() in SCALE_WORDS:
            values.append(v * SCALE_WORDS[word.group(1).lower()])
    return values


def quantities(sentence):
    """(token text, [candidate values]) for each measured quantity in a sentence."""
    blanked = sentence
    for rx in NON_QUANTITY_RES:
        blanked = rx.sub(lambda m: " " * len(m.group(0)), blanked)
    blanked = re.sub(r"^\s*(?:\d+\.|[-*])\s+", " ", blanked)  # list markers
    out = []
    for m in NUMBER_RE.finditer(blanked):
        vals = number_values(blanked[m.start():m.end() + 12])[:2] or []
        first = vals[0] if vals else None
        if first is None:
            continue
        # keep the scaled reading as a second candidate when followed by a scale word
        cands = [first] + ([vals[1]] if len(vals) > 1 and vals[1] != first else [])
        out.append((m.group(1), cands))
    return out


def split_sentences(line):
    """Split a prose line into sentences, and a table row into its cells."""
    stripped = line.strip()
    if stripped.startswith("|"):
        return [c.strip() for c in stripped.strip("|").split("|")]
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\[`*])", stripped)
    return [p for p in parts if p]


def parse_ledger(lines):
    """Ledger rows from the table whose header starts with ID and has Source. Returns list of dicts."""
    records = []
    for header, rows, _ in table_rows(lines):
        if not (header and header[0] == "ID" and "Source" in header):
            continue
        for cells, off in rows:
            if cells and LEDGER_ID_RE.fullmatch(cells[0]):
                rec = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header)}
                rec["_offset"] = off
                records.append(rec)
    return records


def parse_ledger_range(text):
    """(start, end) datetimes for a ledger Time Range such as '2026-09-22T13:00Z-16:00Z', else None."""
    m = LEDGER_RANGE_RE.match(text)
    if not m:
        return None
    start = parse_ts(m.group(1))
    end_text = m.group(2)
    if ISO_RE.fullmatch(end_text):
        end = parse_ts(end_text)
    else:
        hh, mm = int(end_text[0:2]), int(end_text[3:5])
        ss = int(end_text[6:8]) if end_text.count(":") == 2 else 0
        try:
            end = start.replace(hour=hh, minute=mm, second=ss)
        except ValueError:
            return None
    return start, end


def check_numeric_traceability(r, secs, ledger_by_id, strict):
    """Numbers in cited sentences must appear in the Key Finding of a cited ledger row."""
    traced = total = 0
    emit = r.err if strict else r.warn
    findings = {i: number_values(rec.get("Key Finding", "")) for i, rec in ledger_by_id.items()}
    for sec_no in ("3", "5", "6"):
        if sec_no not in secs:
            continue
        for i, line in enumerate(secs[sec_no]["lines"]):
            if line.lstrip().startswith("#") or re.match(r"^\s*\|[\s:\-|]+\|\s*$", line):
                continue
            for sentence in split_sentences(line):
                ids = {m for m in LEDGER_ID_RE.findall(sentence) if m in ledger_by_id}
                if not ids or TAG_RE.search(sentence):
                    continue
                derived = set()
                for dm in DERIVED_RE.finditer(sentence):
                    derived.update(number_values(dm.group(1)))
                body = DERIVED_RE.sub(" ", sentence)
                known = [v for e in ids for v in findings[e]]
                untraced = []
                for token, cands in quantities(body):
                    total += 1
                    if any(abs(c - k) < 1e-9 for c in cands for k in known) or any(
                            abs(c - d) < 1e-9 for c in cands for d in derived):
                        traced += 1
                    else:
                        untraced.append(token)
                if untraced:
                    emit("CITATION_NUMBER_UNTRACED",
                         f"{', '.join(untraced)} not found in the Key Finding of {', '.join(sorted(ids))}; "
                         f"add it to the ledger row, cite the row that holds it, or mark it [derived: ...]: "
                         f"'{sentence.strip()[:80]}'",
                         secs[sec_no]["start"] + 2 + i)
    r.info["numeric_traceability"] = {"traced": traced, "total": total}


def check_ledger_fields(r, records, impact_start):
    """Field-level checks on ledger rows; returns the set of valid IDs."""
    seen = set()
    for rec in records:
        eid = rec["ID"]
        if eid in seen:
            r.err("LEDGER_DUPLICATE_ID", f"{eid} appears more than once in the Evidence Ledger")
        seen.add(eid)
        if not rec.get("Query / Link", "").strip():
            r.err("LEDGER_QUERY_MISSING", f"{eid} has no Query / Link; a reviewer must be able to re-run it")
        collected = rec.get("Collected (UTC)", "").strip()
        if not ISO_RE.fullmatch(collected):
            r.err("LEDGER_COLLECTED_INVALID", f"{eid}: 'Collected (UTC)' must be ISO-8601 UTC (got '{collected}')")
        elif impact_start and parse_ts(collected) < impact_start:
            r.err("LEDGER_COLLECTED_BEFORE_INCIDENT",
                  f"{eid}: collected {collected} is before the impact start; check the timestamp")
        rng = rec.get("Time Range", "").strip()
        is_gap = "collection gap" in rec.get("Key Finding", "").lower()
        parsed = parse_ledger_range(rng) if rng else None
        if not is_gap and (parsed is None or parsed[0] > parsed[1]):
            r.warn("LEDGER_RANGE_INVALID",
                   f"{eid}: Time Range '{rng}' should be 'start-end', e.g. 2026-09-22T13:00Z-16:00Z")
    ids = sorted(seen, key=lambda x: int(x[2:]))
    if ids:
        nums = [int(x[2:]) for x in ids]
        gaps = [n for n in range(nums[0], nums[-1] + 1) if n not in set(nums)]
        if gaps:
            r.info["ledger_id_gaps"] = [f"E-{n:03d}" for n in gaps]
    return seen


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


def check(text, tier, strict=False):
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
    ts_map = {}
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
        ts_map = ts
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
    ledger_by_id = {}
    if "10" in secs:
        records = parse_ledger(secs["10"]["lines"])
        ledger_by_id = {rec["ID"]: rec for rec in records}
        ledger = check_ledger_fields(r, records, ts_map.get("Impact Start (UTC)"))
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
    check_numeric_traceability(r, secs, ledger_by_id, strict)
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
    ap.add_argument("--strict", action="store_true",
                    help="treat untraced numbers in cited sentences as errors instead of warnings")
    args = ap.parse_args()
    try:
        text = open(args.path, encoding="utf-8").read()
    except OSError as e:
        print(f"cannot read {args.path}: {e}", file=sys.stderr)
        return 2

    rep = check(text, args.tier, strict=args.strict)
    result = {
        "file": args.path,
        "tier": args.tier,
        "strict": args.strict,
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
