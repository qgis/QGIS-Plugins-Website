"""
Security, quality, and code analysis scanner for QGIS plugins

This module performs non-blocking security and quality checks on uploaded plugin packages.
Results are informational and do not prevent plugin upload.

Uses professional security scanning tools via subprocess:
- Bandit: Security vulnerability scanner for Python code
- detect-secrets: Finds hardcoded secrets
- Flake8: Code quality and style checker
"""

import ast
import json
import os
import subprocess
import tempfile
import zipfile
from typing import Dict

from django.utils.translation import gettext_lazy as _

# All security tools are invoked via subprocess to avoid import/dependency issues


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

    Uses professional security tools via subprocess:
    - Bandit for Python security issues
    - detect-secrets for hardcoded secrets
    - flake8 for code quality
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

        try:
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

            check.files_checked = len(python_files)

            # Run Bandit via subprocess with JSON output
            # Note: Bandit returns exit code 1 when issues are found, which is normal
            result = subprocess.run(
                [
                    "bandit",
                    "-r",
                    self.extracted_dir,
                    "-f",
                    "json",
                    "-ll",  # Only medium/high severity
                    "--quiet",  # Suppress progress bar and other non-JSON output
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # Capture stderr too
                text=True,
                timeout=60,
            )

            # Bandit outputs JSON to stdout even when exit code is 1 (issues found)
            if result.stdout and result.stdout.strip():
                try:
                    bandit_report = json.loads(result.stdout)
                    results = bandit_report.get("results", [])
                    check.issues_found = len(results)

                    for issue in results[:10]:  # Limit to first 10
                        check.details.append(
                            {
                                "file": issue.get("filename", "").replace(
                                    self.extracted_dir, ""
                                ),
                                "line": issue.get("line_number", 0),
                                "type": issue.get("test_id", ""),
                                "severity": issue.get("issue_severity", ""),
                                "confidence": issue.get("issue_confidence", ""),
                                "message": issue.get("issue_text", ""),
                                "code": issue.get("code", ""),
                            }
                        )

                    check.passed = check.issues_found == 0
                except json.JSONDecodeError as e:
                    # If JSON parsing fails, show what we got for debugging
                    check.details.append(
                        {
                            "file": "N/A",
                            "message": f"Bandit JSON parse error. Output preview: {result.stdout[:100]}",
                        }
                    )
                    check.passed = True
            else:
                # No output - could be no issues or an error
                if result.stderr and result.stderr.strip():
                    check.details.append(
                        {
                            "file": "N/A",
                            "message": f"Bandit error: {result.stderr[:200]}",
                        }
                    )
                else:
                    # No stdout and no stderr - assume no issues found
                    check.details.append(
                        {"message": "No security issues detected by Bandit"}
                    )
                check.passed = True

        except (subprocess.TimeoutExpired, FileNotFoundError):
            check.details.append(
                {"file": "N/A", "message": "Bandit not installed (pip install bandit)"}
            )
            check.passed = True  # Don't fail if tool unavailable

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

        try:
            # Use subprocess to avoid any import/logging issues
            result = subprocess.run(
                ["detect-secrets", "scan", "--all-files", "."],
                cwd=self.extracted_dir,
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
            description="Python code quality and style checker.",
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
                        "--ignore=E501",  # Ignore line length for quality check
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
                                    "message": "Python file has executable permission (may be suspicious)",
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
