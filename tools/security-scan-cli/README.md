# QGIS Plugin Security Check (CLI)

Run the **same** security checks as the QGIS plugins web platform, locally, on your
machine — before you upload a plugin version. Catch issues while you develop instead of
at publish time.

The rules are fetched read-only from the platform
(`GET /plugins/api/security-rules/`), so they always reflect what the platform enforces:
there is no separate rule list to keep in sync. The analysis tools (bandit,
detect-secrets, flake8) are pinned to the same versions the platform runs, and the CLI
warns you if your locally-installed versions differ.

Nothing is uploaded. Your plugin source never leaves your machine.

## Install

The tool lives in the QGIS Plugins Website repository (this directory) and installs directly
from GitHub — no PyPI account needed:

```bash
pipx install "git+https://github.com/qgis/QGIS-Plugins-Website.git#subdirectory=tools/security-scan-cli"
# or with pip
pip install "git+https://github.com/qgis/QGIS-Plugins-Website.git#subdirectory=tools/security-scan-cli"
```

Append `@<tag-or-sha>` to the repository URL to pin a specific release. This installs the
`qgis-plugin-security` command plus the pinned analysis tools.

## Usage

```bash
# Scan the current directory
qgis-plugin-security

# Scan a specific plugin source directory or an existing .zip
qgis-plugin-security --path path/to/plugin
qgis-plugin-security --path path/to/plugin.zip

# Ignore skippable rules you have reviewed (mandatory/critical rules cannot be skipped)
qgis-plugin-security --skip B101,E501

# Fail on warnings too, not just critical issues
qgis-plugin-security --strict

# Machine-readable output
qgis-plugin-security --json
```

Point at a different platform host with `--api-url` or the `QGIS_PLUGINS_URL` env var
(default: `https://plugins.qgis.org`).

## Exit codes

| Code | Meaning                                                    |
|------|------------------------------------------------------------|
| `0`  | Scan ran, no critical issues — safe to upload.             |
| `1`  | Scan ran, at least one critical issue — blocked (as the platform would block it). Also returned with `--strict` when warnings are present. |
| `2`  | Transport/usage error (network, bad `--path`, invalid response). |

## Use in CI (GitHub Actions)

```yaml
- name: QGIS plugin security check
  run: |
    pipx install "git+https://github.com/qgis/QGIS-Plugins-Website.git#subdirectory=tools/security-scan-cli"
    qgis-plugin-security --path .
```

The job fails automatically when critical issues are found (exit code 1).

## Use as a pre-commit hook

If you installed the CLI, add a local hook to your plugin repo's
`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: qgis-plugin-security
        name: QGIS plugin security check
        entry: qgis-plugin-security
        language: system
        pass_filenames: false
        always_run: true
```

## Config files are respected

Because the CLI runs the same scanner as the platform, tool config files bundled in your
plugin are honoured locally, exactly as they are on upload:

- `.bandit` — skip specific Bandit test IDs or exclude paths.
- `.secrets.baseline` — acknowledge known/reviewed secrets so they are not re-reported.
- `.flake8` — ignore specific Flake8 codes or set per-file ignores.

Keep them at the top level of your plugin (next to `metadata.txt`). When the CLI scans a
directory it includes dotfiles automatically (only `.git`, `__pycache__` and `.mypy_cache`
are excluded), so your config files are picked up with no extra flags.

## How rule parity works

- **Rules**: fetched live from `/plugins/api/security-rules/`. No local copy to drift.
- **Scanner code**: this package ships the *same* `security_scanner.py` used by the
  platform (a single source file, guarded by a test that fails CI if the two ever
  diverge).
- **Tool versions**: pinned here to match the platform; the endpoint also reports the
  platform's actual versions so the CLI can warn you on any mismatch.

---

Made with 💗 by [Kartoza](https://kartoza.com) |
[Donate!](https://github.com/sponsors/qgis) |
[GitHub](https://github.com/qgis/QGIS-Plugins-Website)
