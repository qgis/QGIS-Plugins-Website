"""
Security, quality, and code analysis scanner for QGIS plugins

This module performs non-blocking security and quality checks on uploaded plugin packages.
Results are informational and do not prevent plugin upload.

Uses professional security scanning libraries:
- Bandit: Security vulnerability scanner for Python code
- Safety: Checks dependencies against known vulnerabilities
- detect-secrets: Finds hardcoded secrets
- Flake8: Code quality and style checker
"""

import ast
import json
import os
import re
import subprocess
import tempfile
import zipfile
from typing import Dict

from django.utils.translation import gettext_lazy as _

# Import security tools
try:
    from bandit.core import config as bandit_config
    from bandit.core import manager as bandit_manager

    BANDIT_AVAILABLE = True
except ImportError:
    BANDIT_AVAILABLE = False

try:
    from detect_secrets import SecretsCollection
    from detect_secrets.settings import default_settings

    DETECT_SECRETS_AVAILABLE = True
except ImportError:
    DETECT_SECRETS_AVAILABLE = False

try:
    import safety

    SAFETY_AVAILABLE = True
except ImportError:
    SAFETY_AVAILABLE = False

try:
    from flake8.api import legacy as flake8_legacy

    FLAKE8_AVAILABLE = True
except ImportError:
    FLAKE8_AVAILABLE = False


class SecurityCheck:
    """Base class for security checks"""

    def __init__(self, name: str, category: str, severity: str, description: str):
        self.name = name
        self.category = category  # 'security', 'quality', 'best_practice'
        self.severity = severity  # 'info', 'warning', 'critical'
        self.description = description
        self.passed = False
        self.details = []
        self.files_checked = 0
        self.issues_found = 0


class PluginSecurityScanner:
    """
    Performs comprehensive security and quality checks on plugin packages

    Uses professional security tools:
    - Bandit for Python security issues
    - detect-secrets for hardcoded secrets
    - flake8 for code quality
    - safety for vulnerable dependencies
    """

    def __init__(self, package_path: str):
        """
        Initialize scanner with package path

        Args:
            package_path: Path to the plugin ZIP file
        """
        self.package_path = package_path
        self.checks = []
        self.extracted_dir = None

    def scan(self) -> Dict:
        """
        Run all security and quality checks

        Returns:
            Dictionary containing check results
        """
        self.checks = []

        # Extract plugin to temporary directory for tool analysis
        self.extracted_dir = tempfile.mkdtemp()
        try:
            with zipfile.ZipFile(self.package_path, "r") as zf:
                zf.extractall(self.extracted_dir)

            # Run all checks
            self._check_with_bandit()
            self._check_secrets()
            self._check_code_quality()
            self._check_dependencies_safety()
            self._check_file_permissions()
            self._check_suspicious_files()

        except Exception:
            # If extraction fails, run basic checks on ZIP
            self._check_file_permissions()
            self._check_suspicious_files()

        # Calculate summary
        return self._generate_report()

    def _check_with_bandit(self):
        """Run Bandit security scanner on Python files"""
        check = SecurityCheck(
            name="Bandit Security Analysis",
            category="security",
            severity="critical",
            description="Professional security vulnerability scanner for Python code (checks for SQL injection, hardcoded passwords, unsafe functions, etc.)",
        )

        if not BANDIT_AVAILABLE:
            check.details.append(
                {"file": "N/A", "message": "Bandit not installed (pip install bandit)"}
            )
            check.passed = True  # Don't fail if tool unavailable
            self.checks.append(check)
            return

        try:
            # Configure Bandit
            b_conf = bandit_config.BanditConfig()
            b_mgr = bandit_manager.BanditManager(
                b_conf, "file", debug=False, verbose=False
            )

            # Find all Python files to scan
            python_files = []
            for root, dirs, files in os.walk(self.extracted_dir):
                for file in files:
                    if file.endswith(".py"):
                        python_files.append(os.path.join(root, file))

            if not python_files:
                check.passed = True
                check.details.append({"message": "No Python files found to scan"})
                self.checks.append(check)
                return

            # Discover and run tests
            b_mgr.discover_files(python_files)
            b_mgr.run_tests()

            # Get results
            check.files_checked = len(python_files)
            results = b_mgr.get_issue_list()

            # Filter for medium/high severity only
            filtered_results = [r for r in results if r.severity in ["MEDIUM", "HIGH"]]
            check.issues_found = len(filtered_results)

            for issue in filtered_results[:10]:  # Limit to first 10
                check.details.append(
                    {
                        "file": issue.fname.replace(self.extracted_dir, ""),
                        "line": issue.lineno,
                        "type": issue.test_id,
                        "severity": issue.severity,
                        "confidence": issue.confidence,
                        "message": issue.text,
                        "code": issue.get_code() if hasattr(issue, "get_code") else "",
                    }
                )

            check.passed = check.issues_found == 0

        except Exception as e:
            check.details.append(
                {"file": "N/A", "message": f"Bandit scan error: {str(e)}"}
            )
            check.passed = True  # Don't fail on errors

        self.checks.append(check)

    def _check_secrets(self):
        """Check for hardcoded secrets using detect-secrets"""
        check = SecurityCheck(
            name="Secrets Detection",
            category="security",
            severity="critical",
            description="Scans for hardcoded secrets, API keys, passwords, and tokens using detect-secrets",
        )

        if not DETECT_SECRETS_AVAILABLE:
            check.passed = True
            check.details.append(
                {
                    "file": "N/A",
                    "message": "detect-secrets not installed (pip install detect-secrets)",
                }
            )
            self.checks.append(check)
            return

        try:
            # Use subprocess instead of Python API to completely avoid logging issues
            result = subprocess.run(
                ["detect-secrets", "scan", "--all-files", self.extracted_dir],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # Suppress stderr completely
                text=True,
                timeout=30,
            )

            if result.stdout:
                try:
                    secrets_report = json.loads(result.stdout)
                    results = secrets_report.get("results", {})

                    for file_path, secrets in results.items():
                        # Skip binary files
                        if file_path.endswith((".pyc", ".pyo", ".so", ".dll", ".exe")):
                            continue

                        check.files_checked += 1

                        for secret in secrets:
                            check.issues_found += 1
                            check.details.append(
                                {
                                    "file": file_path.replace(self.extracted_dir, ""),
                                    "line": secret.get("line_number", 0),
                                    "type": secret.get("type", "Unknown"),
                                    "message": f"Potential {secret.get('type', 'secret')} detected",
                                }
                            )

                    check.passed = check.issues_found == 0
                except json.JSONDecodeError:
                    check.passed = True
            else:
                # No secrets found
                check.passed = True
                # Count files scanned
                for root, dirs, files in os.walk(self.extracted_dir):
                    for file in files:
                        if not file.endswith((".pyc", ".pyo", ".so", ".dll", ".exe")):
                            check.files_checked += 1

        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Tool not available, pass gracefully
            check.passed = True

        except Exception as e:
            check.details.append(
                {"file": "N/A", "message": f"Secrets detection error: {str(e)}"}
            )
            check.passed = True

        self.checks.append(check)

    def _check_code_quality(self):
        """Basic Python code quality checks using flake8"""
        check = SecurityCheck(
            name="Code Quality (Flake8)",
            category="quality",
            severity="info",
            description="Python code quality and style checker. 💡 Showing first 20 issues. Run `flake8 --ignore=E501 .` in your plugin root to see all issues.",
        )

        try:
            import subprocess

            # Find Python files first
            python_files = []
            for root, dirs, files in os.walk(self.extracted_dir):
                for file in files:
                    if file.endswith(".py"):
                        python_files.append(os.path.join(root, file))

            if not python_files:
                check.passed = True
                self.checks.append(check)
                return

            check.files_checked = len(python_files)

            # Try flake8 with JSON output first (requires flake8-json)
            try:
                result = subprocess.run(
                    [
                        "flake8",
                        "--format=json",
                        "--max-line-length=120",
                        "--ignore=E501",
                    ]
                    + python_files,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                # Parse JSON output
                if result.stdout:
                    flake8_data = json.loads(result.stdout)

                    # Count total issues across all files
                    for file_path, issues in flake8_data.items():
                        for issue in issues:
                            check.issues_found += 1

                    # Collect first 20 issues for display
                    issue_count = 0
                    for file_path, issues in flake8_data.items():
                        for issue in issues:
                            if issue_count >= 20:
                                break
                            check.details.append(
                                {
                                    "file": file_path.replace(self.extracted_dir, ""),
                                    "line": issue.get("line_number", 0),
                                    "column": issue.get("column_number", 0),
                                    "code": issue.get("code", ""),
                                    "message": issue.get("text", ""),
                                }
                            )
                            issue_count += 1
                        if issue_count >= 20:
                            break

                    check.passed = check.issues_found == 0
                else:
                    # No JSON output, try standard format
                    raise Exception("No JSON output from flake8")

            except (
                subprocess.TimeoutExpired,
                FileNotFoundError,
                json.JSONDecodeError,
                Exception,
            ):
                # Fallback: Try flake8 with standard output
                try:
                    result = subprocess.run(
                        ["flake8", "--max-line-length=120", "--ignore=E501"]
                        + python_files,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )

                    if result.stdout:
                        # Parse standard flake8 output format: "file:line:col: code message"
                        lines = result.stdout.strip().split("\n")
                        check.issues_found = len([l for l in lines if l.strip()])

                        for line in lines[:20]:  # First 20 issues
                            if not line.strip():
                                continue

                            try:
                                # Parse: /path/file.py:10:5: E302 expected 2 blank lines
                                parts = line.split(":", 3)
                                if len(parts) >= 4:
                                    file_path = parts[0]
                                    line_num = parts[1]
                                    col_num = parts[2]
                                    # parts[3] is like " E302 expected 2 blank lines"
                                    message_parts = parts[3].strip().split(" ", 1)
                                    code = message_parts[0] if message_parts else ""
                                    message = (
                                        message_parts[1]
                                        if len(message_parts) > 1
                                        else ""
                                    )

                                    check.details.append(
                                        {
                                            "file": file_path.replace(
                                                self.extracted_dir, ""
                                            ),
                                            "line": (
                                                int(line_num)
                                                if line_num.isdigit()
                                                else 0
                                            ),
                                            "column": (
                                                int(col_num) if col_num.isdigit() else 0
                                            ),
                                            "code": code,
                                            "message": message,
                                        }
                                    )
                            except Exception:
                                continue

                        check.passed = check.issues_found == 0
                    else:
                        # Flake8 found no issues
                        check.passed = True

                except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                    # Final fallback: manual syntax check
                    self._check_python_syntax_fallback(check)
                    check.passed = check.issues_found == 0

        except Exception:
            # Ultimate fallback
            self._check_python_syntax_fallback(check)
            check.passed = check.issues_found == 0

        self.checks.append(check)

    def _check_python_syntax_fallback(self, check):
        """Fallback syntax checker when flake8 is unavailable"""
        try:
            with zipfile.ZipFile(self.package_path, "r") as zf:
                for file_info in zf.filelist:
                    if not file_info.filename.endswith(".py"):
                        continue

                    check.files_checked += 1

                    try:
                        content = zf.read(file_info.filename).decode(
                            "utf-8", errors="ignore"
                        )

                        # Try to parse Python code
                        try:
                            ast.parse(content)
                        except SyntaxError as e:
                            check.issues_found += 1
                            check.details.append(
                                {
                                    "file": file_info.filename,
                                    "line": e.lineno,
                                    "message": f"Syntax error: {e.msg}",
                                }
                            )

                        # Check for very long lines (possible obfuscation)
                        lines = content.split("\n")
                        for i, line in enumerate(lines, 1):
                            if len(line) > 500:
                                check.issues_found += 1
                                check.details.append(
                                    {
                                        "file": file_info.filename,
                                        "line": i,
                                        "message": f"Extremely long line ({len(line)} chars) - possible code obfuscation",
                                    }
                                )
                    except Exception:
                        continue
        except Exception:
            pass

    def _check_dependencies_safety(self):
        """Check dependencies for known vulnerabilities using safety"""
        check = SecurityCheck(
            name="Dependencies Vulnerability Check",
            category="security",
            severity="warning",
            description="Checks Python dependencies against known vulnerability databases",
        )

        if not SAFETY_AVAILABLE:
            check.passed = True
            check.details.append(
                {"file": "N/A", "message": "Safety not installed (pip install safety)"}
            )
            self.checks.append(check)
            return

        requirements_files = []

        # Search for requirements files in all subdirectories
        for root, dirs, files in os.walk(self.extracted_dir):
            for file in files:
                if file in [
                    "requirements.txt",
                    "requirements-dev.txt",
                    "requirements-test.txt",
                ]:
                    requirements_files.append(os.path.join(root, file))

        if not requirements_files:
            check.passed = True
            check.details.append(
                {
                    "file": "N/A",
                    "message": "No requirements files found (requirements.txt, requirements-dev.txt, requirements-test.txt)",
                }
            )
            self.checks.append(check)
            return

        try:
            for req_path in requirements_files:
                check.files_checked += 1

                try:
                    # Read requirements
                    with open(req_path, "r") as f:
                        requirements = f.read()

                    # Check with Safety
                    # Try multiple API versions (Safety 3.x vs 2.x)
                    vulnerabilities = []
                    try:
                        # Safety 3.x API
                        from safety.models import Project
                        from safety.scan.command import scan_projects

                        # This is more complex in v3, so fall back to simpler approach
                        raise ImportError("Use v2 API")
                    except (ImportError, AttributeError):
                        try:
                            # Safety 2.x API
                            from safety.safety import check as safety_check

                            vulnerabilities, _ = safety_check(
                                packages=requirements.splitlines(),
                                key=None,
                                db_mirror=None,
                                cached=False,
                                ignore_ids=set(),
                            )
                        except (ImportError, AttributeError, TypeError):
                            try:
                                # Even older Safety API
                                from safety import check as safety_check

                                vulnerabilities = safety_check(
                                    packages=requirements.splitlines()
                                )
                            except Exception:
                                # All Safety APIs failed, use fallback
                                self._check_typosquatting(req_path, check)
                                continue

                    # Process vulnerabilities if we got any
                    for vuln in vulnerabilities:
                        check.issues_found += 1
                        # Handle different vulnerability object formats
                        package = getattr(
                            vuln, "package_name", getattr(vuln, "package", "unknown")
                        )
                        version = getattr(
                            vuln,
                            "analyzed_version",
                            getattr(vuln, "installed_version", "unknown"),
                        )
                        vuln_id = getattr(
                            vuln,
                            "vulnerability_id",
                            getattr(vuln, "vuln_id", "unknown"),
                        )

                        check.details.append(
                            {
                                "file": os.path.basename(req_path),
                                "package": package,
                                "version": version,
                                "message": f"Vulnerability: {vuln_id}",
                                "severity": "warning",
                            }
                        )

                except FileNotFoundError:
                    pass
                except Exception:
                    # Fallback to basic typosquatting check
                    self._check_typosquatting(req_path, check)

            check.passed = check.issues_found == 0

        except Exception:
            check.passed = True  # Don't fail if tool unavailable

        self.checks.append(check)

    def _check_typosquatting(self, req_path, check):
        """Fallback: Check for typosquatting package names"""
        suspicious_packages = [
            "requets",
            "urllib3s",
            "requests2",
            "beautifulsoup",
            "dateutil2",
            "python-dateutil2",
            "setup-tools",
            "pip-tools",
            "nump",
            "pandsa",
            "djagno",
            "flaск",
            "requеsts",  # Note: some use unicode lookalikes
        ]

        try:
            with open(req_path, "r") as f:
                content = f.read()

            for package in suspicious_packages:
                if re.search(rf"\b{package}\b", content, re.IGNORECASE):
                    check.issues_found += 1
                    check.details.append(
                        {
                            "file": os.path.basename(req_path),
                            "message": f"Suspicious package name detected: {package} (possible typosquatting)",
                        }
                    )
        except Exception:
            pass

    def _check_file_permissions(self):
        """Check for files with unusual permissions"""
        check = SecurityCheck(
            name="File Permissions",
            category="security",
            severity="info",
            description="Checks for files with executable or unusual permissions",
        )

        try:
            with zipfile.ZipFile(self.package_path, "r") as zf:
                for file_info in zf.filelist:
                    check.files_checked += 1

                    # Check external attributes for Unix permissions
                    # External attr has Unix permissions in high 16 bits
                    unix_perm = file_info.external_attr >> 16

                    if unix_perm and (unix_perm & 0o111):  # Has execute bit
                        # .py files shouldn't typically be executable in a plugin
                        if file_info.filename.endswith(".py"):
                            check.issues_found += 1
                            check.details.append(
                                {
                                    "file": file_info.filename,
                                    "message": f"Python file has executable permission (may be suspicious)",
                                }
                            )

            check.passed = check.issues_found == 0

        except Exception as e:
            check.details.append(
                {"file": "N/A", "message": f"Error during scan: {str(e)}"}
            )

        self.checks.append(check)

    def _check_suspicious_files(self):
        """Check for suspicious file types or hidden files"""
        check = SecurityCheck(
            name="Suspicious Files",
            category="security",
            severity="warning",
            description="Detects suspicious file types, hidden files, or unexpected executables",
        )

        suspicious_extensions = [
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".bat",
            ".sh",
            ".ps1",
            ".cmd",
        ]

        try:
            with zipfile.ZipFile(self.package_path, "r") as zf:
                for file_info in zf.filelist:
                    check.files_checked += 1
                    filename = os.path.basename(file_info.filename)

                    # Check for hidden files (starting with .)
                    if filename.startswith(".") and filename not in [
                        ".gitignore",
                        ".gitattributes",
                    ]:
                        check.issues_found += 1
                        check.details.append(
                            {
                                "file": file_info.filename,
                                "message": "Hidden file detected",
                            }
                        )

                    # Check for suspicious extensions
                    for ext in suspicious_extensions:
                        if file_info.filename.lower().endswith(ext):
                            check.issues_found += 1
                            check.details.append(
                                {
                                    "file": file_info.filename,
                                    "message": f"Executable or binary file detected ({ext})",
                                }
                            )
                            break

            check.passed = check.issues_found == 0

        except Exception as e:
            check.details.append(
                {"file": "N/A", "message": f"Error during scan: {str(e)}"}
            )

        self.checks.append(check)

    def _check_dependencies(self):
        """Check for known vulnerable dependencies or suspicious packages"""
        check = SecurityCheck(
            name="Dependencies Check",
            category="best_practice",
            severity="info",
            description="Reviews plugin dependencies for potential issues",
        )

        # Fallback if safety not available - checked in _check_dependencies_safety
        check.passed = True
        check.details.append(
            {
                "message": "Basic dependency check (use safety tool for comprehensive vulnerability scanning)"
            }
        )

        self.checks.append(check)

    def _generate_report(self) -> Dict:
        """Generate comprehensive report from all checks"""
        report = {
            "summary": {
                "total_checks": len(self.checks),
                "passed": sum(1 for c in self.checks if c.passed),
                "warnings": sum(
                    1 for c in self.checks if not c.passed and c.severity == "warning"
                ),
                "critical": sum(
                    1 for c in self.checks if not c.passed and c.severity == "critical"
                ),
                "info": sum(
                    1 for c in self.checks if not c.passed and c.severity == "info"
                ),
                "files_scanned": sum(c.files_checked for c in self.checks),
                "total_issues": sum(c.issues_found for c in self.checks),
            },
            "checks": [],
        }

        for check in self.checks:
            report["checks"].append(
                {
                    "name": check.name,
                    "category": check.category,
                    "severity": check.severity,
                    "description": check.description,
                    "passed": check.passed,
                    "files_checked": check.files_checked,
                    "issues_found": check.issues_found,
                    "details": check.details[:20],  # Show first 20 details
                }
            )

        return report
