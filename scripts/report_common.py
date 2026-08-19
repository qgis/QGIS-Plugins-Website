#!/usr/bin/env python3
"""Shared helpers for the SBOM and CVE markdown tables in the build report.

Both tables are concatenated into ``build-report.md`` by
``.github/workflows/docker.yml`` and then used in two places: as a pull request
comment, and appended to the GitHub release body.

The release body is the binding constraint. **GitHub truncates it at 125,000
characters**, silently -- the API accepts the request and returns 200. Before
this module existed neither script had any size limit, and the consequence was
visible in production: the v4.2.4, v4.2.5 and v4.2.6 release bodies all measured
exactly 124,999 characters, with the SBOM table alone consuming the entire
budget. The CVE Scan section came after it and was therefore cut off in full, so
three consecutive releases shipped with no vulnerability report at all while the
workflow reported success.

The fix is to give each table a fixed share of the budget and to make any
truncation explicit in the output, so a missing row is visible rather than
inferred. The complete, untruncated data is always attached to the release as
``cve-scan.json`` and ``sbom.spdx.json``.
"""

# GitHub's hard limit on the release body. Not documented in the REST API
# reference; established empirically from the truncated v4.2.x release bodies.
RELEASE_BODY_LIMIT = 125_000

# What the two tables may consume between them. The remainder is headroom for
# the image metadata table, the quick-start block, the impact assessment, and
# the release-drafter notes that `append_body: true` prepends ahead of our
# report.
REPORT_BUDGET = 100_000

# The CVE table lists only findings that have a fix available, so it is far
# smaller than the raw match count suggests -- 145 rows and ~32,000 units on the
# v4.3.0 scan, against 1346 matches. It keeps the headroom to absorb a bad month
# without truncating; the SBOM gets the rest, since it is a package inventory
# that will always exceed any budget and is attached in full regardless.
CVE_TABLE_BUDGET = 45_000
SBOM_TABLE_BUDGET = 55_000


def github_length(text):
    """Length of ``text`` as GitHub counts it: UTF-16 code units.

    Python's ``len()`` counts code points, which under-counts every astral
    character by one. The severity emoji in these tables (U+1F534 and friends)
    are all astral, so a table of a few hundred rows measured with ``len()``
    lands several hundred units over budget -- enough to matter when the whole
    point is to stay under a hard cap.
    """
    return len(text.encode("utf-16-le")) // 2


OMISSION_NOTE = (
    "\n_Showing {shown} of {total} rows. {omitted} omitted to stay within "
    "GitHub's {limit:,}-character release body limit -- the complete data is "
    "in the attached `{artifact}`._\n"
)


def render_budgeted(head, rows, tail, budget, artifact):
    """Join ``rows`` between ``head`` and ``tail``, dropping rows past ``budget``.

    ``head`` and ``tail`` are always emitted in full: the summary line and the
    table header are the parts that must survive, since they carry the counts.
    Only table rows are dropped, and never silently -- if any row is omitted an
    explicit note naming ``artifact`` is appended.

    Space for the note is reserved up front using its worst case (every row
    omitted), so adding the note can never push the result back over budget.
    """
    worst_case_note = OMISSION_NOTE.format(
        shown=0,
        total=len(rows),
        omitted=len(rows),
        limit=RELEASE_BODY_LIMIT,
        artifact=artifact,
    )
    available = (
        budget
        - github_length(head)
        - github_length(tail)
        - github_length(worst_case_note)
    )

    shown = []
    used = 0
    for row in rows:
        cost = github_length(row) + 1  # +1 for the newline
        if used + cost > available:
            break
        shown.append(row)
        used += cost

    out = head
    if shown:
        out += "\n".join(shown) + "\n"
    if len(shown) < len(rows):
        out += OMISSION_NOTE.format(
            shown=len(shown),
            total=len(rows),
            omitted=len(rows) - len(shown),
            limit=RELEASE_BODY_LIMIT,
            artifact=artifact,
        )
    out += tail
    return out
