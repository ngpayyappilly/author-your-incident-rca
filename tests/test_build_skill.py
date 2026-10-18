"""Tests for scripts/build_skill.py (deterministic .skill bundle + front matter lint).

Run:  python -m unittest discover -s tests -v
"""
import hashlib
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_skill as b  # noqa: E402

GOOD_SKILL_MD = "---\nname: demo-skill\ndescription: Does a demo thing.\n---\n\n# Demo\n"


def make_skill(root, skill_md=GOOD_SKILL_MD, name="demo-skill"):
    src = Path(root) / name
    (src / "references").mkdir(parents=True)
    (src / "SKILL.md").write_text(skill_md, encoding="utf-8")
    (src / "references" / "a.md").write_text("alpha\n", encoding="utf-8")
    (src / "z.txt").write_text("zulu\n", encoding="utf-8")
    return src


class Lint(unittest.TestCase):
    def lint(self, skill_md, name="demo-skill"):
        with tempfile.TemporaryDirectory() as d:
            return b.lint_front_matter(make_skill(d, skill_md, name))

    def test_good_front_matter_passes(self):
        self.assertEqual(self.lint(GOOD_SKILL_MD), [])

    def test_missing_front_matter(self):
        self.assertTrue(any("front matter" in p for p in self.lint("# no front matter\n")))

    def test_name_must_match_folder(self):
        probs = self.lint("---\nname: other\ndescription: x\n---\n")
        self.assertTrue(any("must match the folder" in p for p in probs), probs)

    def test_name_required(self):
        self.assertTrue(any("missing 'name'" in p for p in self.lint("---\ndescription: x\n---\n")))

    def test_description_required(self):
        self.assertTrue(any("missing 'description'" in p for p in self.lint("---\nname: demo-skill\n---\n")))

    def test_description_length_limit(self):
        long_desc = "x" * (b.DESCRIPTION_MAX + 1)
        probs = self.lint(f"---\nname: demo-skill\ndescription: {long_desc}\n---\n")
        self.assertTrue(any("limit is" in p for p in probs), probs)

    def test_description_at_limit_passes(self):
        desc = "x" * b.DESCRIPTION_MAX
        self.assertEqual(self.lint(f"---\nname: demo-skill\ndescription: {desc}\n---\n"), [])

    def test_missing_skill_md(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "demo-skill").mkdir()
            self.assertTrue(any("not found" in p for p in b.lint_front_matter(Path(d) / "demo-skill")))

    def test_real_skill_front_matter_is_valid(self):
        self.assertEqual(b.lint_front_matter(b.SOURCE_DIR), [])


class Build(unittest.TestCase):
    def test_deterministic_across_runs_and_mtimes(self):
        with tempfile.TemporaryDirectory() as d:
            src = make_skill(d)
            first = b.build_bytes(src)
            time.sleep(1.1)
            (src / "z.txt").touch()  # changes mtime only
            self.assertEqual(first, b.build_bytes(src))

    def test_entries_sorted_rooted_and_timestamps_fixed(self):
        with tempfile.TemporaryDirectory() as d:
            src = make_skill(d)
            out = Path(d) / "out.skill"
            out.write_bytes(b.build_bytes(src))
            with zipfile.ZipFile(out) as zf:
                names = zf.namelist()
                self.assertEqual(names, sorted(names))
                self.assertTrue(all(n.startswith("demo-skill/") for n in names))
                self.assertTrue(all(i.date_time == b.FIXED_DATE_TIME for i in zf.infolist()))
                self.assertIsNone(zf.testzip())

    def test_content_change_changes_output(self):
        with tempfile.TemporaryDirectory() as d:
            src = make_skill(d)
            before = b.build_bytes(src)
            (src / "z.txt").write_text("changed\n", encoding="utf-8")
            self.assertNotEqual(before, b.build_bytes(src))

    def test_excludes_junk_and_generated_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            src = make_skill(d)
            for rel in ["scripts/__pycache__/x.pyc", "evidence/E-001.json", "service-profiles/svc.md",
                        "assets/.DS_Store", "scripts/mod.pyc"]:
                p = src / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("junk", encoding="utf-8")
            names = [n for n, _ in b.collect_files(src)]
            self.assertEqual(names, ["demo-skill/SKILL.md", "demo-skill/references/a.md", "demo-skill/z.txt"])

    def test_symlinks_are_not_bundled(self):
        with tempfile.TemporaryDirectory() as d:
            src = make_skill(d)
            target = Path(d) / "secret.txt"
            target.write_text("outside the skill", encoding="utf-8")
            try:
                (src / "link.txt").symlink_to(target)
            except OSError:
                self.skipTest("symlinks unsupported here")
            names = [n for n, _ in b.collect_files(src)]
            self.assertNotIn("demo-skill/link.txt", names)


class Drift(unittest.TestCase):
    def test_no_drift_when_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            src = make_skill(d)
            bundle = Path(d) / "demo-skill.skill"
            bundle.write_bytes(b.build_bytes(src))
            self.assertEqual(b.describe_drift(bundle, src), [])

    def test_reports_missing_changed_and_stale_entries(self):
        with tempfile.TemporaryDirectory() as d:
            src = make_skill(d)
            bundle = Path(d) / "demo-skill.skill"
            bundle.write_bytes(b.build_bytes(src))
            (src / "z.txt").write_text("changed\n", encoding="utf-8")        # content differs
            (src / "new.md").write_text("new\n", encoding="utf-8")           # missing from bundle
            (src / "references" / "a.md").unlink()                          # stale entry in bundle
            drift = "\n".join(b.describe_drift(bundle, src))
            self.assertIn("content differs: demo-skill/z.txt", drift)
            self.assertIn("missing from bundle: demo-skill/new.md", drift)
            self.assertIn("stale entry in bundle: demo-skill/references/a.md", drift)

    def test_missing_bundle_reported(self):
        with tempfile.TemporaryDirectory() as d:
            src = make_skill(d)
            self.assertTrue(b.describe_drift(Path(d) / "nope.skill", src))


class CommittedBundle(unittest.TestCase):
    """The repository's own bundle must match the folder (this is what CI enforces)."""

    def test_committed_bundle_is_up_to_date(self):
        drift = b.describe_drift(b.BUNDLE, b.SOURCE_DIR)
        self.assertEqual(drift, [], "run `python scripts/build_skill.py` and commit the bundle")
        self.assertEqual(b.BUNDLE.read_bytes(), b.build_bytes(b.SOURCE_DIR))

    def test_cli_check_passes(self):
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_skill.py"), "--check"],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_cli_lint_passes(self):
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_skill.py"), "--lint"],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_build_twice_is_byte_identical(self):
        h1 = hashlib.sha256(b.build_bytes(b.SOURCE_DIR)).hexdigest()
        h2 = hashlib.sha256(b.build_bytes(b.SOURCE_DIR)).hexdigest()
        self.assertEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
