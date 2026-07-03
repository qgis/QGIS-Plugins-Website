"""
Tests for the standalone QGIS plugin security-check CLI.

Run from tools/security-scan-cli/ with:  python -m pytest
Network is never hit: _fetch_rules is monkeypatched.
"""
import hashlib
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from qgis_plugin_security import cli

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_SCANNER = REPO_ROOT / "qgis-app" / "plugins" / "security_scanner.py"
CLI_SCANNER = (
    REPO_ROOT
    / "tools"
    / "security-scan-cli"
    / "qgis_plugin_security"
    / "security_scanner.py"
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_cli_scanner_in_sync():
    """The CLI's scanner must be identical to the platform's (no drift)."""
    assert APP_SCANNER.exists(), APP_SCANNER
    assert CLI_SCANNER.exists(), CLI_SCANNER
    assert _sha(APP_SCANNER) == _sha(CLI_SCANNER), (
        "tools/security-scan-cli scanner has drifted from qgis-app/plugins "
        "scanner; keep it a symlink / single source."
    )


def test_build_enabled_rules_skips_only_skippable():
    rules = [
        {"check_code": "B602", "check_category": "bandit", "can_be_skipped": False},
        {"check_code": "E501", "check_category": "flake8", "can_be_skipped": True},
    ]
    # Try to skip both; only the skippable E501 may actually be removed.
    enabled = cli._build_enabled_rules(rules, {"B602", "E501"})
    codes = {r.check_code for r in enabled}
    assert "B602" in codes  # mandatory rule cannot be skipped
    assert "E501" not in codes


def test_resolve_zip_rejects_bad_path():
    with pytest.raises(cli.ScanError):
        cli._resolve_zip("/definitely/not/here.txt")


def test_zip_directory_roundtrip(tmp_path):
    (tmp_path / "plugin").mkdir()
    (tmp_path / "plugin" / "__init__.py").write_text("# clean\n")
    (tmp_path / "plugin" / ".git").mkdir()
    (tmp_path / "plugin" / ".git" / "config").write_text("noise\n")

    zip_path = cli._zip_directory(str(tmp_path / "plugin"))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert any(n.endswith("__init__.py") for n in names)
        assert not any(".git" in n for n in names)  # VCS noise excluded
    finally:
        os.remove(zip_path)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_zip_directory_respects_gitignore(tmp_path):
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "__init__.py").write_text("# clean\n")
    (plugin / ".gitignore").write_text("venv/\nsecret.txt\n")
    # Ignored virtualenv-like content that must NOT be scanned.
    (plugin / "venv").mkdir()
    (plugin / "venv" / "evil.py").write_text("import os\nos.system('rm -rf /')\n")
    (plugin / "secret.txt").write_text("token = 'abc'\n")

    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    subprocess.run(["git", "-C", str(plugin), "init", "-q"], check=True, env=env)

    zip_path = cli._zip_directory(str(plugin))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
    finally:
        os.remove(zip_path)

    assert any(n.endswith("__init__.py") for n in names)
    assert not any("venv" in n for n in names)  # gitignored dir excluded
    assert not any(n.endswith("secret.txt") for n in names)  # gitignored file


def test_run_transport_error(monkeypatch):
    def boom(_url):
        raise cli.ScanError("network down")

    monkeypatch.setattr(cli, "_fetch_rules", boom)
    assert cli.run(["--path", "."]) == cli.EXIT_ERROR


def test_run_clean_plugin_exits_ok(monkeypatch, tmp_path):
    (tmp_path / "__init__.py").write_text("def f():\n    return 1\n")

    monkeypatch.setattr(
        cli,
        "_fetch_rules",
        lambda _url: {"rules": [], "secrets_plugins": [], "tool_versions": {}},
    )
    assert cli.run(["--path", str(tmp_path)]) == cli.EXIT_OK


@pytest.mark.skipif(
    shutil.which("bandit") is None, reason="bandit not installed locally"
)
def test_run_critical_plugin_exits_one(monkeypatch, tmp_path):
    # subprocess with shell=True is a Bandit high-severity (B602) finding.
    (tmp_path / "bad.py").write_text(
        "import subprocess\nsubprocess.call('ls', shell=True)\n"
    )

    monkeypatch.setattr(
        cli,
        "_fetch_rules",
        lambda _url: {
            "rules": [
                {
                    "check_code": "B602",
                    "check_category": "bandit",
                    "can_be_skipped": False,
                }
            ],
            "secrets_plugins": [],
            "tool_versions": {},
        },
    )
    assert cli.run(["--path", str(tmp_path)]) == cli.EXIT_CRITICAL
