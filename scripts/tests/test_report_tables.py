#!/usr/bin/env python3
"""Tests for the SBOM and CVE markdown table generators.

These scripts only ever run inside .github/workflows/docker.yml, where a bad
output is not a crash but a silently malformed release body -- which is exactly
how three releases shipped with no CVE section at all. They are covered here
rather than in the Django suite because they are standalone stdlib scripts with
no relationship to the app; see the "report-tables" step in
.github/workflows/test.yaml.

Run with:  python -m unittest discover -s scripts/tests
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cve_table  # noqa: E402
import sbom_table  # noqa: E402
from report_common import (  # noqa: E402
    COMMENT_BODY_LIMIT,
    CVE_TABLE_BUDGET,
    RELEASE_BODY_LIMIT,
    REPORT_BUDGET,
    SBOM_TABLE_BUDGET,
    github_length,
    render_budgeted,
)

# Rough size of the rest of build-report.md: the image metadata table, the
# quick-start block and the trailing commit line. Measured from a real PR
# report and rounded up, so the combined-size test reflects what is actually
# posted rather than just the two tables.
REPORT_PREAMBLE_ALLOWANCE = 2_000


def make_match(cve_id, severity, fix_state, pkg="somepkg", versions=None):
    return {
        "vulnerability": {
            "id": cve_id,
            "severity": severity,
            "description": "A representative description of moderate length. " * 3,
            "cvss": [{"metrics": {"baseScore": 7.5}}],
            "fix": {"state": fix_state, "versions": versions or []},
        },
        "artifact": {"name": pkg, "version": "1.2.3-4+deb13u1"},
    }


def run_script(module, payload):
    """Run a table generator over ``payload`` and return its stdout."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(payload, handle)
        path = handle.name
    argv = sys.argv
    sys.argv = [module.__name__, path]
    try:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            module.main()
        return buffer.getvalue()
    finally:
        sys.argv = argv
        Path(path).unlink()


class GithubLengthTests(unittest.TestCase):
    def test_counts_utf16_code_units(self):
        # The severity emoji are astral, so they cost two units each on
        # GitHub while Python's len() sees one. Budgeting on len() is what
        # first pushed the real table over its cap.
        self.assertEqual(len("\U0001f534"), 1)
        self.assertEqual(github_length("\U0001f534"), 2)

    def test_matches_len_for_ascii(self):
        self.assertEqual(github_length("plain ascii"), len("plain ascii"))


class RenderBudgetedTests(unittest.TestCase):
    def test_keeps_everything_when_it_fits(self):
        out = render_budgeted("HEAD\n", ["a", "b"], "TAIL\n", 1000, "x.json")
        self.assertIn("a", out)
        self.assertIn("b", out)
        self.assertNotIn("omitted to stay within", out)

    def test_head_and_tail_always_survive_truncation(self):
        rows = [f"row-{i:04d}" for i in range(5000)]
        out = render_budgeted("HEAD\n", rows, "TAIL\n", 500, "x.json")
        self.assertTrue(out.startswith("HEAD\n"))
        self.assertTrue(out.endswith("TAIL\n"))

    def test_reports_how_many_were_dropped(self):
        rows = [f"row-{i:04d}" for i in range(5000)]
        out = render_budgeted("HEAD\n", rows, "TAIL\n", 500, "cve-scan.json")
        self.assertIn("of 5000 rows", out)
        self.assertIn("cve-scan.json", out)
        self.assertIn(f"{RELEASE_BODY_LIMIT:,}", out)

    def test_never_exceeds_budget(self):
        rows = [f"row-{i:04d}" for i in range(5000)]
        for budget in (200, 500, 5_000, 50_000):
            out = render_budgeted("HEAD\n", rows, "TAIL\n", budget, "x.json")
            self.assertLessEqual(github_length(out), budget, f"budget={budget}")


class CveTableTests(unittest.TestCase):
    def test_no_matches(self):
        out = run_script(cve_table, {"matches": []})
        self.assertIn("No known CVEs detected", out)

    def test_stays_within_budget_and_flags_truncation(self):
        # Mixed fix states, as a real scan has: a minority are fixable.
        matches = [
            make_match(
                f"CVE-2026-{i:05d}",
                "High",
                "fixed" if i % 10 == 0 else "not-fixed",
                versions=["9.9.9"] if i % 10 == 0 else None,
            )
            for i in range(5000)
        ]
        out = run_script(cve_table, {"matches": matches})
        self.assertLessEqual(github_length(out), CVE_TABLE_BUDGET)
        self.assertIn("omitted to stay within", out)
        self.assertIn("cve-scan.json", out)
        # The summary and the closing tag must survive so the section is
        # still well-formed markdown after truncation.
        self.assertIn("of 5000 total", out)
        self.assertIn("</details>", out)

    def test_headline_counts_only_fixable(self):
        matches = [
            make_match("CVE-1", "Critical", "fixed", versions=["2.0"]),
            make_match("CVE-2", "High", "wont-fix"),
            make_match("CVE-3", "High", "not-fixed"),
            make_match("CVE-4", "Low", "fixed", versions=["3.0"]),
        ]
        out = run_script(cve_table, {"matches": matches})
        self.assertIn("**2 actionable CVEs** (of 4 total):", out)

    def test_unfixable_findings_are_excluded_from_the_table(self):
        matches = [
            make_match("CVE-CRIT", "Critical", "wont-fix", pkg="unfixable-pkg"),
            make_match("CVE-NP", "High", "not-fixed", pkg="unpatched-pkg"),
            make_match("CVE-LOW", "Low", "fixed", pkg="fixable-pkg", versions=["9.9"]),
        ]
        out = run_script(cve_table, {"matches": matches})
        self.assertIn("fixable-pkg", out)
        # A Critical nobody can act on must not crowd out the row that matters.
        self.assertNotIn("unfixable-pkg", out)
        self.assertNotIn("unpatched-pkg", out)

    def test_excluded_findings_are_still_counted_and_explained(self):
        matches = [
            make_match("CVE-1", "Low", "fixed", versions=["9.9"]),
            make_match("CVE-2", "Critical", "wont-fix"),
            make_match("CVE-3", "Critical", "wont-fix"),
            make_match("CVE-4", "High", "not-fixed"),
        ]
        out = run_script(cve_table, {"matches": matches})
        self.assertIn("3 further findings", out)
        self.assertIn("2 upstream will not fix", out)
        self.assertIn("1 no patch published yet", out)
        self.assertIn("cve-scan.json", out)

    def test_headline_when_nothing_is_fixable(self):
        matches = [make_match("CVE-1", "High", "wont-fix")]
        out = run_script(cve_table, {"matches": matches})
        self.assertIn("**No actionable CVEs.**", out)
        self.assertIn("1 further finding", out)

    def test_unknown_severity_appears_in_breakdown(self):
        # Regression: the breakdown was built from a hardcoded severity list
        # that omitted "Unknown", so the parts did not sum to the total.
        matches = [
            make_match("CVE-1", "Critical", "fixed", versions=["1.0"]),
            make_match("CVE-2", "Unknown", "fixed", versions=["1.0"]),
            make_match("CVE-3", "Unknown", "fixed", versions=["1.0"]),
        ]
        out = run_script(cve_table, {"matches": matches})
        summary = [ln for ln in out.splitlines() if ln.startswith("**3 actionable")][0]
        self.assertIn("1 Critical", summary)
        self.assertIn("2 Unknown", summary)

    def test_missing_fix_block_is_treated_as_unfixable(self):
        match = make_match("CVE-1", "High", "fixed")
        del match["vulnerability"]["fix"]
        out = run_script(cve_table, {"matches": [match]})
        self.assertIn("**No actionable CVEs.**", out)


class SbomTableTests(unittest.TestCase):
    def _artifacts(self, count):
        return [
            {
                "name": f"libpackage-{i}",
                "version": f"1.{i}.0-2+deb13u1",
                "type": "deb",
                "licenses": [{"value": "GPL-2.0-only"}],
                "locations": [{"path": f"/usr/lib/pkg-{i}/METADATA"}],
            }
            for i in range(count)
        ]

    def test_stays_within_budget_and_flags_truncation(self):
        out = run_script(sbom_table, {"artifacts": self._artifacts(5000)})
        self.assertLessEqual(github_length(out), SBOM_TABLE_BUDGET)
        self.assertIn("omitted to stay within", out)
        self.assertIn("sbom.spdx.json", out)
        self.assertIn("</details>", out)

    def test_small_sbom_is_not_truncated(self):
        out = run_script(sbom_table, {"artifacts": self._artifacts(3)})
        self.assertNotIn("omitted to stay within", out)
        self.assertIn("libpackage-2", out)

    def test_deduplicates_by_name_and_version(self):
        artifacts = self._artifacts(2) + self._artifacts(2)
        out = run_script(sbom_table, {"artifacts": artifacts})
        self.assertIn("**2 packages detected**", out)


class CombinedBudgetTests(unittest.TestCase):
    def test_both_tables_together_fit_the_release_body(self):
        cve = run_script(
            cve_table,
            {
                "matches": [
                    make_match(f"CVE-2026-{i:05d}", "High", "not-fixed")
                    for i in range(5000)
                ]
            },
        )
        sbom = run_script(
            sbom_table,
            {
                "artifacts": [
                    {
                        "name": f"libpackage-{i}",
                        "version": f"1.{i}.0",
                        "type": "deb",
                        "licenses": [],
                        "locations": [],
                    }
                    for i in range(5000)
                ]
            },
        )
        combined = github_length(cve) + github_length(sbom)
        self.assertLessEqual(combined, REPORT_BUDGET)

        # build-report.md is posted as a PR comment as well as appended to the
        # release body, and the comment limit is the smaller of the two. Unlike
        # the release body it is enforced by rejection, not truncation, so
        # exceeding it loses the comment entirely.
        whole_report = combined + REPORT_PREAMBLE_ALLOWANCE
        self.assertLess(whole_report, COMMENT_BODY_LIMIT)
        self.assertLess(whole_report, RELEASE_BODY_LIMIT)

    def test_budget_split_fits_the_smaller_github_limit(self):
        self.assertEqual(CVE_TABLE_BUDGET + SBOM_TABLE_BUDGET, REPORT_BUDGET)
        self.assertLess(REPORT_BUDGET + REPORT_PREAMBLE_ALLOWANCE, COMMENT_BODY_LIMIT)


if __name__ == "__main__":
    unittest.main()
