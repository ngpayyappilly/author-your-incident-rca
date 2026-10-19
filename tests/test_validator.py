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
    "CITATION_NUMBER_UNTRACED": ("warnings", lambda t: mutate(
        t, "**Member impact:** 29% of profile lookup", "**Member impact:** 41% of profile lookup")),
    "LEDGER_DUPLICATE_ID": ("errors", lambda t: mutate(
        t, "| E-002 | Argo CD | Application sync history", "| E-001 | Argo CD | Application sync history")),
    "LEDGER_QUERY_MISSING": ("errors", lambda t: mutate(
        t, "| member-profile-api success ratio, 1m, vs prior week |", "| |")),
    "LEDGER_COLLECTED_INVALID": ("errors", lambda t: mutate(t, "| 2026-09-23T09:10:00Z |", "| yesterday |")),
    "LEDGER_COLLECTED_BEFORE_INCIDENT": ("errors", lambda t: mutate(
        t, "| 2026-09-23T09:10:00Z |", "| 2026-09-22T09:10:00Z |")),
    "LEDGER_RANGE_INVALID": ("warnings", lambda t: mutate(
        t, "| 2026-09-22T13:00Z-16:00Z | Success rate 71%", "| around 1pm | Success rate 71%")),
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
    def test_example_numbers_all_trace(self):
        rep = validate_rca.check(EXAMPLE, "full")
        tr = rep.info["numeric_traceability"]
        self.assertGreater(tr["total"], 20)
        self.assertEqual(tr["traced"], tr["total"])

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


def untraced(text, **kw):
    rep = validate_rca.check(text, "full", **kw)
    return [w["message"] for w in rep.warnings if w["code"] == "CITATION_NUMBER_UNTRACED"], rep


class NumericTraceability(unittest.TestCase):
    CLAIM = "**Member impact:** 29% of profile lookup"

    def test_changed_number_is_flagged_and_named(self):
        msgs, rep = untraced(mutate(EXAMPLE, self.CLAIM, "**Member impact:** 41% of profile lookup"))
        self.assertEqual(len(msgs), 1)
        self.assertIn("41", msgs[0])
        self.assertIn("E-001", msgs[0])
        self.assertEqual(rep.info["numeric_traceability"]["total"] - rep.info["numeric_traceability"]["traced"], 1)

    def test_strict_promotes_warning_to_error(self):
        text = mutate(EXAMPLE, self.CLAIM, "**Member impact:** 41% of profile lookup")
        rep = validate_rca.check(text, "full", strict=True)
        self.assertIn("CITATION_NUMBER_UNTRACED", h.codes(rep)["errors"])
        self.assertNotIn("CITATION_NUMBER_UNTRACED", h.codes(rep)["warnings"])

    def test_number_may_come_from_any_cited_row(self):
        # 41 is only in E-099's finding; cite both rows and it traces.
        text = mutate(EXAMPLE, self.CLAIM, "**Member impact:** 41% of profile lookup")
        text = mutate(text, "about 410,000 failed requests out of 1.41 million [E-001].",
                      "about 410,000 failed requests out of 1.41 million [E-001] [E-010].")
        text = mutate(text, "Connections 22% of max; query latency flat", "Connections 22% of max; 41% of lookups sampled")
        self.assertEqual(untraced(text)[0], [])

    def test_formatting_variants_trace(self):
        for old, new in [("1.9 s", "1.9s"), ("29%", "29 %"), ("410,000", "410000"), ("1.41 million", "1.41M")]:
            with self.subTest(old=old):
                text = mutate(EXAMPLE, "(29% failed: about 410,000 of 1.41 million requests)",
                              "(29% failed: about 410,000 of 1.41 million requests)".replace(old, new))
                self.assertEqual(untraced(text)[0], [])

    def test_scaled_reading_traces(self):
        # Claim says 1.41 million; the ledger row spells it out.
        text = mutate(EXAMPLE, "of 1.41 million requests", "of 1,410,000 requests")
        self.assertEqual(untraced(text)[0], [])

    def test_derived_marker_exempts_listed_numbers(self):
        text = mutate(EXAMPLE, "[derived: 44 min = 14:07Z to 14:51Z; 12.8 = 0.29 x 44; 43.2 = 30 days x 1440 x 0.001; 29.5% = 12.8 / 43.2] ", "")
        msgs, _ = untraced(text)
        self.assertEqual(len(msgs), 1)
        for token in ("44", "12.8", "29.5", "43.2"):
            self.assertIn(token, msgs[0])

    def test_tags_exempt_the_sentence(self):
        text = mutate(EXAMPLE, self.CLAIM, "**Member impact:** 41% of profile lookup")
        text = mutate(text, "about 410,000 failed requests out of 1.41 million [E-001].",
                      "about 410,000 failed requests out of 1.41 million [E-001] [ASSUMPTION].")
        self.assertEqual(untraced(text)[0], [])

    def test_timestamps_ids_and_status_classes_are_not_quantities(self):
        qs = validate_rca.quantities("At 14:07Z (2026-09-22T14:07:00Z) CF-3 and A-5 on INC0098765 saw 5xx for P2 [E-001].")
        self.assertEqual(qs, [])

    def test_list_markers_and_headings_are_ignored(self):
        self.assertEqual(validate_rca.quantities("1. Why did it fail?"), [])
        self.assertEqual([t for t, _ in validate_rca.quantities("- 8 pods restarted")], ["8"])

    def test_only_cited_sentences_are_checked(self):
        # The cited sentence is checked ...
        text = mutate(EXAMPLE, "showed an error state for affected members;", "showed an error state for 9999 members;")
        self.assertEqual(len(untraced(text)[0]), 1)
        # ... an earlier sentence on the same line, with no citation of its own, is not.
        text2 = mutate(EXAMPLE, "- **Blast radius:**", "- **Blast radius:** 9999 hosts. Unrelated:")
        self.assertEqual(untraced(text2)[0], [])

    def test_table_cells_are_checked_separately(self):
        text = mutate(EXAMPLE, "DB connections at 22% of max and latency flat [E-010]",
                      "DB connections at 87% of max and latency flat [E-010]")
        msgs, _ = untraced(text)
        self.assertEqual(len(msgs), 1)
        self.assertIn("87", msgs[0])

    def test_scale_words(self):
        self.assertEqual(sorted(validate_rca.number_values("1.41 million and 3k")), [1.41, 3.0, 3000.0, 1410000.0])


class LedgerFields(unittest.TestCase):
    def test_range_formats(self):
        ok = ["2026-09-22T13:00Z-16:00Z", "2026-09-22T13:00:00Z-2026-09-22T16:00:00Z",
              "2026-09-21T00:00Z-2026-09-22T14:00Z", "2026-09-22T13:00Z to 16:00Z"]
        for text in ok:
            with self.subTest(text=text):
                self.assertIsNotNone(validate_rca.parse_ledger_range(text))
        for text in ["", "around 1pm", "13:00-16:00", "2026-09-22T13:00Z", "2026-09-22T13:00Z-99:99Z"]:
            with self.subTest(text=text):
                self.assertIsNone(validate_rca.parse_ledger_range(text))

    def test_range_start_after_end_is_flagged(self):
        text = mutate(EXAMPLE, "| 2026-09-22T13:00Z-16:00Z | Success rate 71%", "| 2026-09-22T16:00Z-13:00Z | Success rate 71%")
        self.assertIn("LEDGER_RANGE_INVALID", h.codes(validate_rca.check(text, "full"))["warnings"])

    def test_collection_gap_row_may_lack_a_range(self):
        text = mutate(EXAMPLE, "| 2026-09-22T13:00Z-16:00Z | Success rate 71%", "| n/a | collection gap: query returned no data. Success rate 71%")
        self.assertNotIn("LEDGER_RANGE_INVALID", h.codes(validate_rca.check(text, "full"))["warnings"])

    def test_collected_equal_to_impact_start_is_allowed(self):
        text = mutate(EXAMPLE, "| 2026-09-23T09:10:00Z |", "| 2026-09-22T14:07:00Z |")
        self.assertNotIn("LEDGER_COLLECTED_BEFORE_INCIDENT", h.codes(validate_rca.check(text, "full"))["errors"])

    def test_id_gaps_are_informational(self):
        text = drop_lines(EXAMPLE, prefix="| E-005 |")
        rep = validate_rca.check(text, "full")
        self.assertEqual(rep.info["ledger_id_gaps"], ["E-005"])
        self.assertNotIn("ledger_id_gaps", validate_rca.check(EXAMPLE, "full").info)


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
        self.assertEqual(set(data), {"file", "tier", "strict", "passed", "errors", "warnings", "info"})
        self.assertTrue(data["passed"])
        self.assertEqual(data["tier"], "full")

    def test_strict_flag(self):
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "untraced.md"
            doc.write_text(mutate(EXAMPLE, "**Member impact:** 29% of profile lookup", "**Member impact:** 41% of profile lookup"),
                           encoding="utf-8")
            self.assertEqual(self.run_cli(str(doc)).returncode, 0)
            res = self.run_cli(str(doc), "--strict")
            self.assertEqual(res.returncode, 1, res.stdout)
            self.assertIn("CITATION_NUMBER_UNTRACED", res.stdout)

    def test_tier_flag_is_applied(self):
        with tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "lite.md"
            doc.write_text(cut_section(EXAMPLE, "8"), encoding="utf-8")
            self.assertEqual(self.run_cli(str(doc), "--tier", "lite").returncode, 0)
            self.assertEqual(self.run_cli(str(doc)).returncode, 1)


if __name__ == "__main__":
    unittest.main()
