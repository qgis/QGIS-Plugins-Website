#!/usr/bin/env python3
"""Parse syft SBOM JSON output into a markdown table.

The table is size-capped: see scripts/report_common.py for why, and for what
happens to the rows that do not fit.
"""

import json
import sys

from report_common import SBOM_TABLE_BUDGET, render_budgeted


def main():
    if len(sys.argv) < 2:
        print("Usage: sbom_table.py <syft-json-file>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    artifacts = data.get("artifacts", [])
    seen = set()
    rows = []

    for art in artifacts:
        name = art.get("name", "unknown")
        version = art.get("version", "unknown")
        pkg_type = art.get("type", "unknown")
        key = f"{name}:{version}"
        if key in seen:
            continue
        seen.add(key)

        licenses_list = []
        for lic in art.get("licenses", []):
            if isinstance(lic, dict):
                licenses_list.append(lic.get("value", lic.get("expression", "")))
            else:
                licenses_list.append(str(lic))
        licenses = ", ".join(licenses_list) if licenses_list else "-"

        upstream = "-"
        for loc in art.get("locations", []):
            path = loc.get("path", "")
            if path:
                upstream = f"`{path}`"
                break

        rows.append((pkg_type, name, version, licenses, upstream))

    rows.sort(key=lambda r: (r[0], r[1]))

    head = (
        f"**{len(rows)} packages detected**\n\n"
        "<details>\n"
        f"<summary>SBOM ({len(rows)} packages)</summary>\n\n"
        "| Package | Version | Type | License | Location |\n"
        "|---------|---------|------|---------|----------|\n"
    )
    tail = "\n</details>\n"

    table_rows = [
        f"| {name} | {version} | {pkg_type} | {licenses} | {upstream} |"
        for pkg_type, name, version, licenses, upstream in rows
    ]

    # write(), not print(): print would append a newline that the budget did
    # not account for, so the rendered section could exceed its cap by one.
    sys.stdout.write(
        render_budgeted(head, table_rows, tail, SBOM_TABLE_BUDGET, "sbom.spdx.json")
    )


if __name__ == "__main__":
    main()
