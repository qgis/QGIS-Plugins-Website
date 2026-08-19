#!/usr/bin/env python3
"""Parse Grype CVE scan JSON output into a markdown table.

The table is size-capped: see scripts/report_common.py for why, and for what
happens to the rows that do not fit.
"""

import json
import sys

from report_common import CVE_TABLE_BUDGET, render_budgeted

SEVERITY_EMOJI = {
    "Critical": "🔴",
    "High": "🟠",
    "Medium": "🟡",
    "Low": "🔵",
    "Negligible": "⚪",
    "Unknown": "⚪",
}

SEVERITY_ORDER = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
    "Negligible": 4,
    "Unknown": 5,
}

IMPACT_ASSESSMENT = """
> **Impact Assessment:** This image runs the QGIS Plugins Website — a public,
> internet-facing Django application served by uWSGI behind an nginx reverse
> proxy. It **accepts untrusted input** (plugin package uploads, search queries,
> authenticated user content) and talks to a PostgreSQL database, RabbitMQ, and
> Celery workers running as separate services. The threat surface is therefore
> wider than a local desktop container: CVEs in the web/runtime stack (Python,
> Django and its dependencies, libxml/libxslt, Pillow/JPEG, OpenSSL, libpq) are
> potentially reachable from the network and should be triaged promptly. In
> production the app runs behind nginx with TLS and is not exposed directly.
> This scan is **report-only** today (it never blocks a deploy); once the
> baseline is clean it will be switched to fail releases above a severity cutoff.
> Prioritise Critical/High fixes that touch request-handling or parsing code.
"""


def main():
    if len(sys.argv) < 2:
        print("Usage: cve_table.py <grype-json-file>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    matches = data.get("matches", [])

    if not matches:
        print("**No known CVEs detected in this image.**\n")
        print(IMPACT_ASSESSMENT)
        return

    rows = []
    for match in matches:
        vuln = match.get("vulnerability", {})
        cve_id = vuln.get("id", "unknown")
        severity = vuln.get("severity", "Unknown")
        description = vuln.get("description", "")[:120]
        if len(vuln.get("description", "")) > 120:
            description += "..."

        cvss_scores = vuln.get("cvss", [])
        cvss = "-"
        for score in cvss_scores:
            if "metrics" in score and "baseScore" in score["metrics"]:
                cvss = str(score["metrics"]["baseScore"])
                break

        artifact = match.get("artifact", {})
        pkg_name = artifact.get("name", "unknown")
        pkg_version = artifact.get("version", "unknown")

        fix = vuln.get("fix", {}) or {}
        # Grype reports "fixed", "not-fixed", "wont-fix" or "unknown". Only
        # "fixed" means an upgrade exists that we could actually take today.
        fixable = fix.get("state") == "fixed"
        fixed_in = ", ".join(fix.get("versions") or []) or "-"

        nvd_link = f"[{cve_id}](https://nvd.nist.gov/vuln/detail/{cve_id})"

        rows.append(
            (
                0 if fixable else 1,
                SEVERITY_ORDER.get(severity, 5),
                cve_id,
                severity,
                cvss,
                nvd_link,
                pkg_name,
                pkg_version,
                fixed_in,
                description,
                fix.get("state") or "unknown",
            )
        )

    rows.sort(key=lambda r: (r[0], r[1], r[2]))

    def breakdown(by_severity):
        # Driven by SEVERITY_ORDER rather than a hardcoded list, so "Unknown"
        # is included. It previously was not, which meant the severities in the
        # summary line did not add up to the total beside them.
        return ", ".join(
            f"{SEVERITY_EMOJI.get(sev, '')} {by_severity[sev]} {sev}"
            for sev in sorted(by_severity, key=lambda s: SEVERITY_ORDER.get(s, 5))
        )

    # The table lists only findings we can act on. On a Debian-based image the
    # great majority of matches are advisories the distribution has explicitly
    # declined to fix or has no patch for, and listing them buries the handful
    # that matter: the v4.3.0 report was 1346 rows of which 1201 could not be
    # acted on at all. Those are still counted below, and the attached
    # cve-scan.json remains the complete record.
    actionable = [row for row in rows if row[0] == 0]

    fixable_counts = {}
    unfixable_states = {}
    for row in rows:
        if row[0] == 0:
            fixable_counts[row[3]] = fixable_counts.get(row[3], 0) + 1
        else:
            unfixable_states[row[10]] = unfixable_states.get(row[10], 0) + 1

    STATE_LABELS = {
        "wont-fix": "upstream will not fix",
        "not-fixed": "no patch published yet",
        "unknown": "fix status unknown",
    }
    omitted = sum(unfixable_states.values())
    if omitted:
        detail = ", ".join(
            f"{count} {STATE_LABELS.get(state, state)}"
            for state, count in sorted(unfixable_states.items(), key=lambda kv: -kv[1])
        )
        context = (
            f"\n{omitted} further finding{'s' if omitted != 1 else ''} "
            f"({detail}) {'are' if omitted != 1 else 'is'} not listed: there is "
            "nothing to upgrade to. Complete data in the attached "
            "`cve-scan.json`.\n"
        )
    else:
        context = ""

    if not actionable:
        print(
            f"**No actionable CVEs.** {len(rows)} finding"
            f"{'s' if len(rows) != 1 else ''} detected, none with a fix "
            "available.\n"
            f"{context}"
        )
        print(IMPACT_ASSESSMENT)
        return

    head = (
        f"**{len(actionable)} actionable CVEs** (of {len(rows)} total): "
        f"{breakdown(fixable_counts)}\n"
        f"{context}\n"
        "<details>\n"
        f"<summary>Actionable CVEs ({len(actionable)} with a fix available)"
        "</summary>\n\n"
        "| Severity | CVSS | CVE | Package | Version | Fixed In | Description |\n"
        "|----------|------|-----|---------|---------|----------|-------------|\n"
    )
    tail = "\n</details>\n\n" + IMPACT_ASSESSMENT

    table_rows = []
    for (
        _,
        _,
        cve_id,
        severity,
        cvss,
        nvd_link,
        pkg_name,
        pkg_version,
        fixed_in,
        desc,
        _,
    ) in actionable:
        emoji = SEVERITY_EMOJI.get(severity, "")
        table_rows.append(
            f"| {emoji} {severity} | {cvss} | {nvd_link} | {pkg_name} | "
            f"{pkg_version} | {fixed_in} | {desc} |"
        )

    print(render_budgeted(head, table_rows, tail, CVE_TABLE_BUDGET, "cve-scan.json"))


if __name__ == "__main__":
    main()
