"""Command-line entry point for the QGIS plugin security checker.

Usage:
    qgis-plugin-security [--path DIR_OR_ZIP] [--api-url URL]
                         [--skip CODE,CODE] [--strict] [--json]

Exit codes:
    0  scan ran, no critical issues (safe to upload)
    1  scan ran, at least one critical issue (blocked, as the platform would)
    2  transport/usage error (network, bad path, invalid response)
"""
import argparse
import json
import os
import sys
import tempfile
import zipfile
from importlib.metadata import PackageNotFoundError, version
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import Request, urlopen

from .security_scanner import PluginSecurityScanner

DEFAULT_API_URL = "https://plugins.qgis.org"
RULES_PATH = "/plugins/api/security-rules/"

# Map the platform's tool distribution names to the local distributions we check.
LOCAL_TOOL_DISTRIBUTIONS = ["bandit", "detect-secrets", "flake8"]

EXIT_OK = 0
EXIT_CRITICAL = 1
EXIT_ERROR = 2


class ScanError(Exception):
    """Raised for transport/usage problems that map to exit code 2."""


def _fetch_rules(api_url: str) -> dict:
    """GET the enabled rules + tool versions from the platform."""
    url = api_url.rstrip("/") + RULES_PATH
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8")
    except (URLError, OSError) as exc:
        raise ScanError(f"Could not reach {url}: {exc}") from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ScanError(f"Invalid JSON from {url}: {exc}") from exc
    if "rules" not in data:
        raise ScanError(f"Unexpected response from {url}: missing 'rules'")
    return data


def _build_enabled_rules(rules: list, skip_codes: set) -> list:
    """Turn API rule dicts into lightweight objects the scanner understands.

    Only rules flagged ``can_be_skipped`` may be removed via ``skip_codes`` —
    this mirrors the platform's skip policy so a developer cannot silence a
    mandatory (critical) rule locally.
    """
    enabled = []
    for rule in rules:
        code = rule.get("check_code")
        if code in skip_codes and rule.get("can_be_skipped"):
            continue
        enabled.append(
            SimpleNamespace(
                check_code=code,
                check_category=rule.get("check_category"),
            )
        )
    return enabled


def _zip_directory(path: str) -> str:
    """Zip a plugin source directory into a temporary .zip; return its path."""
    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    base = os.path.basename(os.path.abspath(path.rstrip(os.sep))) or "plugin"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(path):
            # Skip VCS and cache noise that would never ship in a plugin zip.
            dirs[:] = [
                d for d in dirs if d not in (".git", "__pycache__", ".mypy_cache")
            ]
            for name in files:
                abs_path = os.path.join(root, name)
                rel = os.path.relpath(abs_path, path)
                zf.write(abs_path, os.path.join(base, rel))
    return zip_path


def _resolve_zip(path: str):
    """Return (zip_path, cleanup) for a directory or an existing .zip."""
    if os.path.isdir(path):
        zip_path = _zip_directory(path)
        return zip_path, lambda: os.path.exists(zip_path) and os.remove(zip_path)
    if os.path.isfile(path) and path.lower().endswith(".zip"):
        return path, lambda: None
    raise ScanError(f"--path must be a directory or a .zip file: {path!r}")


def _local_tool_versions() -> dict:
    versions = {}
    for dist in LOCAL_TOOL_DISTRIBUTIONS:
        try:
            versions[dist] = version(dist)
        except PackageNotFoundError:
            versions[dist] = None
    return versions


def _warn_version_mismatch(platform_versions: dict) -> None:
    """Print a warning if local analysis tools differ from the platform's."""
    if not platform_versions:
        return
    local = _local_tool_versions()
    for dist, platform_ver in platform_versions.items():
        local_ver = local.get(dist)
        if local_ver is None:
            print(
                f"WARNING: '{dist}' is not installed locally; its checks will be "
                f"skipped. The platform runs {dist} {platform_ver}.",
                file=sys.stderr,
            )
        elif platform_ver and local_ver != platform_ver:
            print(
                f"WARNING: local {dist} {local_ver} differs from the platform's "
                f"{dist} {platform_ver}; results may differ slightly.",
                file=sys.stderr,
            )


def _print_report(report: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, indent=2))
        return
    summary = report.get("summary", {})
    print("QGIS plugin security check")
    print("=" * 40)
    print(f"Files scanned : {summary.get('files_scanned', 0)}")
    print(f"Checks passed : {summary.get('passed', 0)}/{summary.get('total_checks', 0)}")
    print(f"Critical      : {summary.get('critical', 0)}")
    print(f"Warnings      : {summary.get('warnings', 0)}")
    print(f"Info          : {summary.get('info', 0)}")
    config_files = report.get("config_files") or []
    if config_files:
        print(f"Config files  : {', '.join(config_files)}")
    print("-" * 40)
    for check in report.get("checks", []):
        if check.get("passed"):
            continue
        status = check.get("severity", "info").upper()
        print(f"[{status}] {check.get('name')}: {check.get('issues_found', 0)} issue(s)")
        for detail in check.get("details", []):
            loc = detail.get("file", "")
            line = detail.get("line")
            where = f"{loc}:{line}" if line else loc
            print(f"    - {where} {detail.get('message', '')}".rstrip())
    print("-" * 40)


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="qgis-plugin-security",
        description="Run the QGIS plugins platform security checks locally.",
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Plugin source directory or .zip to scan (default: current directory).",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("QGIS_PLUGINS_URL", DEFAULT_API_URL),
        help="Base URL of the QGIS plugins platform (default: %(default)s).",
    )
    parser.add_argument(
        "--skip",
        default="",
        help="Comma-separated skippable rule codes to ignore (e.g. B101,E501).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also fail (exit 1) when warnings are found, not just criticals.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print the full JSON report instead of a summary.",
    )
    args = parser.parse_args(argv)

    skip_codes = {c.strip() for c in args.skip.split(",") if c.strip()}

    try:
        data = _fetch_rules(args.api_url)
        enabled_rules = _build_enabled_rules(data.get("rules", []), skip_codes)
        _warn_version_mismatch(data.get("tool_versions", {}))

        zip_path, cleanup = _resolve_zip(args.path)
        try:
            scanner = PluginSecurityScanner(
                zip_path,
                enabled_rules=enabled_rules,
                all_secrets_plugins=data.get("secrets_plugins", []),
            )
            report = scanner.scan()
        finally:
            cleanup()
    except ScanError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    _print_report(report, args.as_json)

    summary = report.get("summary", {})
    critical = summary.get("critical", 0)
    warnings = summary.get("warnings", 0)
    if critical > 0:
        print("RESULT: BLOCKED - critical issues found.", file=sys.stderr)
        return EXIT_CRITICAL
    if args.strict and warnings > 0:
        print("RESULT: FAILED (strict) - warnings found.", file=sys.stderr)
        return EXIT_CRITICAL
    print("RESULT: PASSED - no critical issues.", file=sys.stderr)
    return EXIT_OK


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
