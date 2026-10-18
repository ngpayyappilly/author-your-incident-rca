"""Tests for sre-rca-author/scripts/validate_rca.py.

Run:  python -m unittest discover -s tests -v

Table-driven: every error/warning code the validator can emit has a mutation of
the good example that must trigger it. A meta-test fails if the validator gains
a code that this file does not cover.
"""
import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import helpers as h
from helpers import (
    cut_section, drop_lines, edit_section_body, load_example, mutate,
    regex_sub, remove_all, validate_rca,
)

EXAMPLE = load_example()
EXEC_SENTENCE = "This incident consumed about 29% of the 30-day error budget."

# code -> (bucket, mutation(text) -> text)
CASES = {
    # --- structure ---
    "PLACEHOLDER": ("errors", lambda t: mutate(t, "No security impact identified:", "TBD No security impact identified:")),
    "TITLE": ("errors", lambda t: drop_lines(t, prefix="# RCA:")),
    "SECTION_MISSING": ("errors", lambda t: cut_section(t, "8")),
    "SECTION_EMPTY": ("errors", lambda t: edit_section_body(t, "8", lambda b: "\nx\n\n")),
    "SECTION_TITLE": ("warnings", lambda t: mutate(t, "## 8. Security Review", "## 8. Security")),
    # --- metadata ---
    "META_MISSING": ("errors", lambda t: mutate(t, "| Severity | P2 |", "| Severity | |")),
    "META_SEVERITY": ("warnings", lambda t: mutate(t, "| Severity | P2 |", "| Severity | P9 |")),
    "META_CONFIDENCE": ("errors", lambda t: mutate(t, "| Draft Confidence | High |", "| Draft Confidence | Very high |")),
    "META_TIMESTAMP": ("errors", lambda t: mutate(t, "| Detected (UTC) | 2026-09-22T14:19:00Z |", "| Detected (UTC) | yesterday |")),
    "META_ORDER": ("errors", lambda t: mutate(t, "| Detected (UTC) | 2026-09-22T14:19:00Z |", "| Detected (UTC) | 2026-09-22T14:30:00Z |")),
    # --- summary and impact ---
    "EXEC_LONG": ("warnings", lambda t: mutate(t, EXEC_SENTENCE, EXEC_SENTENCE + " word" * 120)),
    "IMPACT_UNQUANTIFIED": ("errors", lambda t: edit_section_body(t, "3", lambda b: "\nMembers were affected for a while.\n\n")),
    "IMPACT_NO_BUDGET": ("warnings", lambda t: edit_section_body(t, "3", lambda b: "\nAbout 5 users were affected.\n\n")),
    # --- timeline ---
    "TIMELINE_TS": ("errors", lambda t: mutate(t, "| 2026-09-22T14:02:10Z | Argo CD syncs", "| around 2pm | Argo CD syncs")),
    "TIMELINE_SHORT": ("errors", lambda t: _drop_timeline_rows(t, 5)),
    "TIMELINE_ORDER": ("errors", lambda t: mutate(t, "| 2026-09-22T14:02:10Z | Argo CD syncs", "| 2026-09-22T15:30:00Z | Argo CD syncs")),
    "TIMELINE_NO_EVIDENCE": ("warnings", lambda t: mutate(t, "| Argo CD | [E-002] |", "| Argo CD | |")),
    # --- technical analysis ---
    "ROOT_CAUSE_MISSING": ("errors", lambda t: mutate(t, "**Root cause:**", "Root cause:")),
    "TRIGGER_MISSING": ("errors", lambda t: mutate(t, "**Trigger:**", "Trigger:")),
    "ROOT_CAUSE_UNCITED": ("errors", lambda t: mutate(t, "could reach every pod at once [E-008].", "could reach every pod at once.")),
    "TRIGGER_UNCITED": ("errors", lambda t: mutate(t, "Argo CD synced it to all pods [E-002].", "Argo CD synced it to all pods.")),
    "CF_MISSING": ("errors", lambda t: regex_sub(t, r"\*\*(CF-\d+)", r"\1", min_count=4)),
    "EVIDENCE_COVERAGE": ("errors", lambda t: edit_section_body(t, "5", lambda b: _strip_citations(b))),
    "UNCITED_CLAIM": ("warnings", lambda t: edit_section_body(t, "5", lambda b: _strip_citations(b))),
    "FIVE_WHYS": ("warnings", lambda t: mutate(t, "### 5.4 Five Whys", "### Five Whys")),
    "HYPOTHESES": ("warnings", lambda t: mutate(t, "### 5.5 Hypotheses Considered", "### Hypotheses Considered")),
    # --- detection and response ---
    "DETECTION_METRIC": ("warnings", lambda t: mutate(
        t, "**TTD / TTA / TTM / TTR:** 12 min / 4 min / 32 min / 63 min, computed from the metadata timestamps.", "**Timings:** see metadata.")),
    "NO_LUCK": ("warnings", lambda t: mutate(t, "Where we got lucky", "Other notes")),
    # --- action items ---
    "ACTIONS_TABLE": ("errors", lambda t: mutate(t, "| ID | Action | Type |", "| Num | Action | Type |")),
    "ACTIONS_COLUMNS": ("errors", lambda t: mutate(t, "| Addresses |", "| Fixes |")),
    "ACTIONS_EMPTY": ("errors", lambda t: drop_lines(t, prefix="| A-", min_count=5)),
    "ACTION_ROW": ("errors", lambda t: _truncate_row(t, "A-5")),
    "ACTION_ID": ("errors", lambda t: mutate(t, "| A-1 |", "| X-1 |")),
    "ACTION_TYPE": ("errors", lambda t: mutate(t, "| Prevent | CF-1 |", "| Fixit | CF-1 |")),
    "ACTION_UNMAPPED": ("errors", lambda t: mutate(t, "| Prevent | CF-1 |", "| Prevent | none |")),
    "ACTION_OWNER": ("errors", lambda t: mutate(t, "| Platform Engineering | P0 | 2026-10-30 |", "| TBD | P0 | 2026-10-30 |")),
    "ACTION_PRIORITY": ("errors", lambda t: mutate(t, "| P0 | 2026-10-30 |", "| P9 | 2026-10-30 |")),
    "ACTION_DUE": ("errors", lambda t: mutate(t, "2026-10-30", "30/10/2026")),
    "ACTION_TRACKING": ("errors", lambda t: mutate(t, "| ADO-4412 |", "| - |")),
    "ACTION_VAGUE": ("warnings", lambda t: mutate(
        t, "Add a runbook step that checks Argo CD sync events in the prior 24 hours and automate rollback on canary failure",
        "Improve how the team handles it")),
    "ACTION_TYPE_MIX": ("warnings", lambda t: _all_prevent(t)),
    "CF_UNADDRESSED": ("errors", lambda t: mutate(t, "| Mitigate | CF-4 |", "| Mitigate | CF-1 |")),
    "ACTION_DANGLING_CF": ("errors", lambda t: mutate(t, "| Mitigate | CF-4 |", "| Mitigate | CF-9 |")),
    # --- evidence ---
    "LEDGER_MISSING": ("errors", lambda t: drop_lines(t, prefix="| E-0", min_count=10)),
    "CITATION_DANGLING": ("errors", lambda t: mutate(t, "were exposed [E-009].", "were exposed [E-099].")),
    "LEDGER_UNUSED": ("warnings", lambda t: remove_all(t, " [E-010]")),
    # --- language and sign-off ---
    "BLAMELESS": ("warnings", lambda t: mutate(t, "No security impact identified:", "Human error caused it. No security impact identified:")),
    "SIGNOFF_PREFILLED": ("errors", lambda t: mutate(t, "| RCA Owner | | Pending | |", "| RCA Owner | | Approved | |")),
}


def _strip_citations(body):
    return regex_sub(body, r" ?\[E-\d{3,}\]", "", min_count=5)


def _drop_timeline_rows(text, n):
    rows = [
        "Gateway retries raise request volume", "On-call engineer acknowledges", "Responders decide to revert",
        "Argo CD syncs the previous revision", "Incident resolved after",
    ]
    for r in rows[:n]:
        text = drop_lines(text, contains=r)
    return text


def _truncate_row(text, action_id):
    return regex_sub(text, rf"(?m)^\| {action_id} \|.*$", f"| {action_id} | short row |")


def _all_prevent(text):
    text = regex_sub(text, r"\| Detect \|", "| Prevent |")
    return regex_sub(text, r"\| Mitigate \|", "| Prevent |", min_count=2)


# ALL_CAPS string literals in the validator that are not diagnostic codes.
NOT_CODES = {"PASS", "FAIL", "ID", "P0", "P1", "P2", "P3", "P4", "TTD", "TTA", "TTM", "TTR"}


def _emitted_codes():
    """Diagnostic codes in validate_rca.py: ALL_CAPS string literals minus NOT_CODES.

    If the validator adds a new ALL_CAPS literal that is not a code, add it to
    NOT_CODES; if it adds a code, add a CASES entry.
    """
    tree = ast.parse(h.VALIDATOR.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if v.isupper() and v.replace("_", "").isalnum() and v not in NOT_CODES:
                found.add(v)
    return found


class GoodExample(unittest.TestCase):
    def test_example_passes_clean(self):
        rep = validate_rca.check(EXAMPLE, "full")
        self.assertEqual(rep.errors, [])
        self.assertEqual(rep.warnings, [])

    def test_computed_metrics(self):
        rep = validate_rca.check(EXAMPLE, "full")
        self.assertEqual(rep.info["computed_metrics_minutes"], {"TTD": 12.0, "TTA": 4.0, "TTM": 32.0, "TTR": 63.0})

    def test_ledger_and_citations_counted(self):
        rep = validate_rca.check(EXAMPLE, "full")
        self.assertEqual(rep.info["evidence_ledger_rows"], 10)
        self.assertEqual(rep.info["evidence_cited"], 10)


class CodeCoverage(unittest.TestCase):
    def test_every_code_triggers_in_its_bucket(self):
        for code, (bucket, mutation) in CASES.items():
            with self.subTest(code=code):
                rep = validate_rca.check(mutation(EXAMPLE), "full")
                got = h.codes(rep)[bucket]
                self.assertIn(code, got, f"{code} not in {bucket}: {sorted(got)}")

    def test_every_validator_code_has_a_case(self):
        missing = sorted(_emitted_codes() - set(CASES))
        self.assertEqual(missing, [], f"validator codes without a test case: {missing}")

    def test_cases_do_not_reference_removed_codes(self):
        stale = sorted(set(CASES) - _emitted_codes())
        self.assertEqual(stale, [], f"test cases for codes the validator no longer emits: {stale}")


class SemanticBehaviour(unittest.TestCase):
    def test_accepted_risk_clears_unaddressed_factor(self):
        text = mutate(EXAMPLE, "| Mitigate | CF-4 |", "| Mitigate | CF-1 |")
        text = mutate(text, "**Accepted risks:** None", "**Accepted risks:** CF-4: rationale, Service Owner")
        self.assertNotIn("CF_UNADDRESSED", h.codes(validate_rca.check(text, "full"))["errors"])

    def test_tag_satisfies_citation_requirement(self):
        text = mutate(EXAMPLE, "could reach every pod at once [E-008].", "could reach every pod at once [ASSUMPTION].")
        self.assertNotIn("ROOT_CAUSE_UNCITED", h.codes(validate_rca.check(text, "full"))["errors"])

    def test_blameless_scan_skips_evidence_ledger(self):
        text = mutate(EXAMPLE, "Pool wait p99 3 ms to 1.9 s;", "Log said human error; pool wait p99 3 ms to 1.9 s;")
        self.assertNotIn("BLAMELESS", h.codes(validate_rca.check(text, "full"))["warnings"])


class Tiers(unittest.TestCase):
    def test_lite_allows_missing_sections_8_and_9(self):
        text = cut_section(cut_section(EXAMPLE, "8"), "9")
        self.assertEqual(validate_rca.check(text, "lite").errors, [])
        self.assertIn("SECTION_MISSING", h.codes(validate_rca.check(text, "full"))["errors"])

    def test_lite_still_requires_core_sections(self):
        text = cut_section(EXAMPLE, "7")
        self.assertIn("SECTION_MISSING", h.codes(validate_rca.check(text, "lite"))["errors"])


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(h.VALIDATOR), *args], capture_output=True, text=True)

    def test_exit_0_on_pass(self):
        res = self.run_cli(str(h.EXAMPLE))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("PASS", res.stdout)

    def test_exit_1_on_errors(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.md"
            bad.write_text(mutate(EXAMPLE, "| Severity | P2 |", "| Severity | |"), encoding="utf-8")
            res = self.run_cli(str(bad))
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("FAIL", res.stdout)

    def test_exit_2_on_missing_file(self):
        res = self.run_cli("does-not-exist.md")
        self.assertEqual(res.returncode, 2)

    def test_json_report_schema(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "report.json"
            res = self.run_cli(str(h.EXAMPLE), "--json", str(out))
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"file", "tier", "passed", "errors", "warnings", "info"})
        self.assertTrue(data["passed"])
        self.assertEqual(data["tier"], "full")

    def test_tier_flag_is_applied(self):
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "lite.md"
            doc.write_text(cut_section(EXAMPLE, "8"), encoding="utf-8")
            self.assertEqual(self.run_cli(str(doc), "--tier", "lite").returncode, 0)
            self.assertEqual(self.run_cli(str(doc)).returncode, 1)


if __name__ == "__main__":
    unittest.main()
