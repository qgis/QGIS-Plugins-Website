"""
Unit tests for the plugin security scanner

Tests cover all security check types and edge cases
"""

import os
import tempfile
import zipfile

from django.contrib.auth.models import User
from django.test import TestCase
from plugins.models import Plugin, PluginVersion, PluginVersionSecurityScan
from plugins.security_scanner import PluginSecurityScanner, SecurityCheck
from plugins.security_utils import get_scan_badge_info


class SecurityScannerTestCase(TestCase):
    """Test cases for the PluginSecurityScanner"""

    def setUp(self):
        """Set up test user and plugin"""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

        self.plugin = Plugin.objects.create(
            name="Test Plugin",
            package_name="test_plugin",
            description="A test plugin",
            created_by=self.user,
            author="Test Author",
            email="author@example.com",
        )

    def _create_test_zip(self, files_content):
        """
        Helper to create a test ZIP file

        Args:
            files_content: dict of {filename: content}

        Returns:
            path to temporary ZIP file
        """
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, "test_plugin.zip")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, content in files_content.items():
                zf.writestr(filename, content)

        return zip_path

    def test_clean_plugin_passes_all_checks(self):
        """Test that a clean plugin passes all security checks"""
        clean_code = """
# Clean Python plugin
def process_data(data):
    return data.upper()

def main():
    print("Hello QGIS!")
"""

        zip_path = self._create_test_zip(
            {
                "test_plugin/__init__.py": clean_code,
                "test_plugin/plugin.py": clean_code,
                "test_plugin/metadata.txt": "[general]\nname=Test",
            }
        )

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        self.assertEqual(report["summary"]["total_checks"], 5)
        self.assertGreater(report["summary"]["passed"], 0)
        self.assertEqual(report["summary"]["critical"], 0)

        # Clean up
        os.remove(zip_path)

    def test_detect_hardcoded_password(self):
        """Test detection of hardcoded passwords"""
        vulnerable_code = """
# Bad practice - hardcoded password
password = "supersecret123"
db_password = 'mydbpass'
"""

        zip_path = self._create_test_zip({"test_plugin/__init__.py": vulnerable_code})

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        # Find the secrets detection check
        sensitive_check = next(
            (c for c in report["checks"] if c["name"] == "Secrets Detection"),
            None,
        )

        self.assertIsNotNone(sensitive_check)
        self.assertFalse(sensitive_check["passed"])
        self.assertGreater(sensitive_check["issues_found"], 0)

        # Clean up
        os.remove(zip_path)

    def test_detect_api_keys(self):
        """Test detection of API keys"""
        vulnerable_code = """
# Bad practice - API key exposed
api_key = "AKIAIOSFODNN7EXAMPLE"
secret_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
"""

        zip_path = self._create_test_zip({"test_plugin/config.py": vulnerable_code})

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        sensitive_check = next(
            (c for c in report["checks"] if c["name"] == "Secrets Detection"),
            None,
        )

        self.assertIsNotNone(sensitive_check)
        self.assertFalse(sensitive_check["passed"])
        self.assertGreater(sensitive_check["issues_found"], 0)

        # Clean up
        os.remove(zip_path)

    def test_detect_dangerous_eval(self):
        """Test detection of dangerous eval() usage"""
        dangerous_code = """
# Dangerous code
def execute_user_input(code):
    result = eval(code)
    return result

def run_command(cmd):
    exec(cmd)
"""

        zip_path = self._create_test_zip({"test_plugin/__init__.py": dangerous_code})

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        dangerous_check = next(
            (c for c in report["checks"] if c["name"] == "Bandit Security Analysis"),
            None,
        )

        self.assertIsNotNone(dangerous_check)
        self.assertFalse(dangerous_check["passed"])
        self.assertGreaterEqual(
            dangerous_check["issues_found"], 1
        )  # Bandit detects eval/exec

        # Clean up
        os.remove(zip_path)

    def test_detect_os_system_calls(self):
        """Test detection of os.system() calls"""
        dangerous_code = """
import os
import subprocess

def run_shell_command(cmd):
    os.system(cmd)

def run_subprocess(cmd):
    subprocess.call(cmd, shell=True)
"""

        zip_path = self._create_test_zip({"test_plugin/utils.py": dangerous_code})

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        dangerous_check = next(
            (c for c in report["checks"] if c["name"] == "Bandit Security Analysis"),
            None,
        )

        self.assertIsNotNone(dangerous_check)
        self.assertFalse(dangerous_check["passed"])
        self.assertGreater(dangerous_check["issues_found"], 0)

        # Clean up
        os.remove(zip_path)

    def test_xml_stdlib_parsing_not_flagged_by_bandit(self):
        """
        Regression test for https://github.com/qgis/QGIS-Plugins-Website/issues/302

        Bandit recommends defusedxml for XML parsing, but defusedxml is a
        third-party package that is not bundled with QGIS's Python environment.
        Plugins that parse XML with the standard library (xml.etree.ElementTree,
        xml.dom.minidom, etc.) must not be flagged as critical security issues.
        Bandit tests B313-B320 and B405-B411 are skipped for this reason.
        """
        xml_parsing_code = """
import xml.etree.ElementTree as ET
import xml.dom.minidom

def parse_layer_config(xml_string):
    root = ET.fromstring(xml_string)
    return root

def parse_project_file(path):
    tree = ET.parse(path)
    return tree.getroot()

def pretty_print_xml(xml_string):
    dom = xml.dom.minidom.parseString(xml_string)
    return dom.toprettyxml()
"""

        zip_path = self._create_test_zip(
            {"test_plugin/xml_utils.py": xml_parsing_code}
        )

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        bandit_check = next(
            (c for c in report["checks"] if c["name"] == "Bandit Security Analysis"),
            None,
        )

        self.assertIsNotNone(bandit_check)
        self.assertTrue(
            bandit_check["passed"],
            "stdlib XML parsing should not be flagged as a critical issue "
            "(defusedxml is not available in QGIS Python)",
        )

        # Clean up
        os.remove(zip_path)

    def test_hashlib_md5_not_flagged_by_bandit(self):
        """
        Regression test for https://github.com/qgis/QGIS-Plugins-Website/issues/302

        Bandit flags hashlib.md5 and hashlib.sha1 as insecure even when they
        are used for non-security purposes (e.g. file checksums, cache keys).
        Bandit tests B303 and B324 are skipped to avoid these false positives.
        """
        hashlib_code = """
import hashlib

def compute_file_checksum(path):
    \"\"\"Compute MD5 checksum for file integrity verification, not cryptography.\"\"\"
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()

def cache_key(value):
    return hashlib.sha1(value.encode()).hexdigest()
"""

        zip_path = self._create_test_zip(
            {"test_plugin/utils.py": hashlib_code}
        )

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        bandit_check = next(
            (c for c in report["checks"] if c["name"] == "Bandit Security Analysis"),
            None,
        )

        self.assertIsNotNone(bandit_check)
        self.assertTrue(
            bandit_check["passed"],
            "hashlib.md5/sha1 used for non-cryptographic purposes "
            "should not be flagged as a critical security issue",
        )

        # Clean up
        os.remove(zip_path)

    def test_w503_line_break_not_flagged_by_flake8(self):
        """
        Regression test for https://github.com/qgis/QGIS-Plugins-Website/issues/302

        W503 (line break before binary operator) is a deprecated Flake8 rule.
        PEP 8 was revised to prefer W504 (break after operator). Plugins using
        the modern style must not be penalised by an outdated rule.
        """
        modern_style_code = """
def compute(a, b, c, d):
    result = (
        a
        + b
        + c
        + d
    )
    return result
"""

        zip_path = self._create_test_zip(
            {"test_plugin/compute.py": modern_style_code}
        )

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        quality_check = next(
            (c for c in report["checks"] if c["name"] == "Code Quality (Flake8)"),
            None,
        )

        self.assertIsNotNone(quality_check)
        # W503 violations must not contribute issues
        w503_issues = [
            d for d in quality_check.get("details", [])
            if d.get("code") == "W503"
        ]
        self.assertEqual(
            len(w503_issues),
            0,
            "W503 (deprecated line-break rule) should not be reported",
        )

        # Clean up
        os.remove(zip_path)

    def test_direct_pyqt5_import_flagged_by_flake8_qgis(self):
        """
        Regression test for https://github.com/qgis/QGIS-Plugins-Website/issues/240

        flake8-qgis rule QGS401 flags direct PyQt5/PyQt4 imports. Plugins should
        use the qgis.PyQt compatibility shim so they work with both Qt5 and Qt6
        (QGIS 4). This test ensures flake8-qgis is installed and active.
        """
        code = (
            "from PyQt5.QtWidgets import QDialog, QPushButton\n"
            "from PyQt5.QtCore import Qt, QThread\n"
            "\n"
            "\n"
            "class MyDialog(QDialog):\n"
            "    pass\n"
        )

        zip_path = self._create_test_zip({"test_plugin/dialog.py": code})

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        quality_check = next(
            (c for c in report["checks"] if c["name"] == "Code Quality (Flake8)"),
            None,
        )

        self.assertIsNotNone(quality_check)
        qgs_issues = [
            d for d in quality_check.get("details", [])
            if d.get("code", "").startswith("QGS")
        ]
        self.assertGreater(
            len(qgs_issues),
            0,
            "flake8-qgis should flag direct PyQt5 imports with a QGS rule "
            "(e.g. QGS401). Is flake8-qgis installed in the Docker image?",
        )

        # Clean up
        os.remove(zip_path)

    def test_qgs201_qgs202_suppressed_by_flake8_qgis(self):
        """
        Regression test for https://github.com/qgis/QGIS-Plugins-Website/issues/240

        QGS201 and QGS202 are experimental return-value checks explicitly marked
        as having a high false-positive rate on PyPI. They must be suppressed so
        that normal PyQGIS code (where discarding a return value is intentional)
        is not incorrectly flagged.
        """
        code = (
            "class QgsVectorLayer:\n"
            "    def setCrs(self, crs):\n"
            "        return True\n"
            "\n"
            "\n"
            "layer = QgsVectorLayer()\n"
            "layer.setCrs(None)  # return value intentionally discarded\n"
        )

        zip_path = self._create_test_zip({"test_plugin/layer_ops.py": code})

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        quality_check = next(
            (c for c in report["checks"] if c["name"] == "Code Quality (Flake8)"),
            None,
        )

        self.assertIsNotNone(quality_check)
        suppressed_issues = [
            d for d in quality_check.get("details", [])
            if d.get("code") in ("QGS201", "QGS202")
        ]
        self.assertEqual(
            len(suppressed_issues),
            0,
            "QGS201/QGS202 (experimental return-value checks) must be suppressed "
            "via --extend-ignore to avoid high false-positive rate",
        )

        # Clean up
        os.remove(zip_path)

    def test_detect_syntax_errors(self):
        """Test detection of Python syntax errors"""
        invalid_code = """
# Syntax error
def broken_function(
    return "missing closing parenthesis"
"""

        zip_path = self._create_test_zip({"test_plugin/__init__.py": invalid_code})

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        quality_check = next(
            (c for c in report["checks"] if c["name"] == "Code Quality (Flake8)"), None
        )

        self.assertIsNotNone(quality_check)
        self.assertFalse(quality_check["passed"])
        self.assertGreater(quality_check["issues_found"], 0)

        # Clean up
        os.remove(zip_path)

    def test_detect_obfuscated_code(self):
        """Test detection of potentially obfuscated code (very long lines)"""
        obfuscated_code = "x = " + "a" * 600 + "\n"

        zip_path = self._create_test_zip({"test_plugin/__init__.py": obfuscated_code})

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        quality_check = next(
            (c for c in report["checks"] if c["name"] == "Code Quality (Flake8)"), None
        )

        self.assertIsNotNone(quality_check)
        self.assertGreater(quality_check["issues_found"], 0)

        # Clean up
        os.remove(zip_path)

    def test_detect_suspicious_executables(self):
        """Test detection of executable files"""
        zip_path = self._create_test_zip(
            {
                "test_plugin/__init__.py": "# Clean code",
                "test_plugin/malware.exe": b"\x4d\x5a\x90\x00",  # PE header
                "test_plugin/library.dll": b"DLL content",
                "test_plugin/script.sh": '#!/bin/bash\necho "test"',
            }
        )

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        suspicious_check = next(
            (c for c in report["checks"] if c["name"] == "Suspicious Files"), None
        )

        self.assertIsNotNone(suspicious_check)
        self.assertFalse(suspicious_check["passed"])
        self.assertGreaterEqual(suspicious_check["issues_found"], 3)  # .exe, .dll, .sh

        # Clean up
        os.remove(zip_path)

    def test_detect_hidden_files(self):
        """Test detection of hidden files"""
        zip_path = self._create_test_zip(
            {
                "test_plugin/__init__.py": "# Clean code",
                "test_plugin/.secret": "hidden content",
                "test_plugin/.env": "SECRET_KEY=abc123",
                "test_plugin/.gitignore": "*.pyc",  # This should be allowed
            }
        )

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        suspicious_check = next(
            (c for c in report["checks"] if c["name"] == "Suspicious Files"), None
        )

        # Should detect .secret and .env but not .gitignore
        self.assertGreaterEqual(suspicious_check["issues_found"], 2)

        # Clean up
        os.remove(zip_path)

    def test_multiple_file_types_scanned(self):
        """Test that scanner checks multiple file types"""
        zip_path = self._create_test_zip(
            {
                "test_plugin/__init__.py": "# Python file\ndef func1(): pass",
                "test_plugin/utils.py": "# Utils file\ndef func2(): pass",
                "test_plugin/helpers.py": "# Helpers file\ndef func3(): pass",
                "test_plugin/config.ini": "[section]\nkey=value",
                "test_plugin/README.txt": "Readme content",
            }
        )

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        # Bandit and Flake8 scan all Python files, so check those
        bandit_check = next(
            (c for c in report["checks"] if c["name"] == "Bandit Security Analysis"),
            None,
        )

        # Should have scanned multiple Python files
        self.assertIsNotNone(bandit_check)
        self.assertGreaterEqual(bandit_check["files_checked"], 3)

        # Clean up
        os.remove(zip_path)

    def test_hex_values_not_flagged_as_secrets(self):
        """
        Regression test for https://github.com/qgis/QGIS-Plugins-Website/issues/300

        Hex values are common in legitimate plugin code and must not be flagged
        as secrets by the HexHighEntropyString detector:
        - qgis-plugin-ci injects a commitSha1 field (full 40-char git SHA) into
          metadata.txt.
        - Alembic database migrations use short hex revision identifiers in SQL
          statements such as UPDATE alembic_version SET version_num='315e0f69004f'.
        The HexHighEntropyString detector is disabled to prevent these false
        positives.
        """
        metadata_with_sha = (
            "[general]\n"
            "name=Test Plugin\n"
            "version=1.0.0\n"
            "commitSha1=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2\n"
        )
        alembic_migration = (
            "# Alembic migration\n"
            "revision = '315e0f69004f'\n"
            "down_revision = '98624e3008ab'\n"
            "def upgrade():\n"
            "    op.execute(\n"
            "        \"UPDATE alembic_version SET version_num='315e0f69004f'\"\n"
            "        \" WHERE alembic_version.version_num = '98624e3008ab'\"\n"
            "    )\n"
        )

        zip_path = self._create_test_zip(
            {
                "test_plugin/__init__.py": "# Clean code",
                "test_plugin/metadata.txt": metadata_with_sha,
                "test_plugin/migrations/001_initial.py": alembic_migration,
            }
        )

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        secrets_check = next(
            (c for c in report["checks"] if c["name"] == "Secrets Detection"),
            None,
        )

        self.assertIsNotNone(secrets_check)
        self.assertTrue(
            secrets_check["passed"],
            "Hex values (git SHAs, Alembic revision IDs) must not be flagged as secrets",
        )
        self.assertEqual(secrets_check["issues_found"], 0)

        # Clean up
        os.remove(zip_path)

    def test_report_structure(self):
        """Test that scan report has correct structure"""
        zip_path = self._create_test_zip({"test_plugin/__init__.py": "# Clean code"})

        scanner = PluginSecurityScanner(zip_path)
        report = scanner.scan()

        # Check summary structure
        self.assertIn("summary", report)
        self.assertIn("checks", report)

        summary = report["summary"]
        self.assertIn("total_checks", summary)
        self.assertIn("passed", summary)
        self.assertIn("warnings", summary)
        self.assertIn("critical", summary)
        self.assertIn("info", summary)
        self.assertIn("files_scanned", summary)
        self.assertIn("total_issues", summary)

        # Check checks structure
        for check in report["checks"]:
            self.assertIn("name", check)
            self.assertIn("category", check)
            self.assertIn("severity", check)
            self.assertIn("description", check)
            self.assertIn("passed", check)
            self.assertIn("files_checked", check)
            self.assertIn("issues_found", check)
            self.assertIn("details", check)

        # Clean up
        os.remove(zip_path)


class SecurityUtilsTestCase(TestCase):
    """Test cases for security_utils functions"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

        self.plugin = Plugin.objects.create(
            name="Test Plugin",
            package_name="test_plugin",
            description="A test plugin",
            created_by=self.user,
            author="Test Author",
            email="author@example.com",
        )

    def test_get_scan_badge_info_no_scan(self):
        """Test badge info when no scan exists"""
        badge_info = get_scan_badge_info(None)

        self.assertEqual(badge_info["color"], "secondary")
        self.assertEqual(badge_info["text"], "Not Scanned")
        self.assertIn("icon", badge_info)
        self.assertIn("class", badge_info)

    def test_get_scan_badge_info_passed(self):
        """Test badge info for passed scan"""
        scan = PluginVersionSecurityScan(
            total_checks=10,
            passed_checks=10,
            warning_count=0,
            critical_count=0,
            info_count=0,
        )

        badge_info = get_scan_badge_info(scan)

        self.assertEqual(badge_info["color"], "success")
        self.assertIn("Passed", badge_info["text"])
        self.assertEqual(badge_info["class"], "badge-success")

    def test_get_scan_badge_info_critical(self):
        """Test badge info for scan with critical issues"""
        scan = PluginVersionSecurityScan(
            total_checks=10,
            passed_checks=7,
            warning_count=0,
            critical_count=3,
            info_count=0,
        )

        badge_info = get_scan_badge_info(scan)

        self.assertEqual(badge_info["color"], "danger")
        self.assertIn("Critical", badge_info["text"])
        self.assertEqual(badge_info["class"], "badge-danger")

    def test_get_scan_badge_info_warning(self):
        """Test badge info for scan with warnings"""
        scan = PluginVersionSecurityScan(
            total_checks=10,
            passed_checks=8,
            warning_count=2,
            critical_count=0,
            info_count=0,
        )

        badge_info = get_scan_badge_info(scan)

        self.assertEqual(badge_info["color"], "warning")
        self.assertIn("Warnings", badge_info["text"])
        self.assertEqual(badge_info["class"], "badge-warning")

    def test_get_scan_badge_info_info(self):
        """Test badge info for scan with info items"""
        scan = PluginVersionSecurityScan(
            total_checks=10,
            passed_checks=9,
            warning_count=0,
            critical_count=0,
            info_count=1,
        )

        badge_info = get_scan_badge_info(scan)

        self.assertEqual(badge_info["color"], "info")
        self.assertIn("Info", badge_info["text"])
        self.assertEqual(badge_info["class"], "badge-info")


class SecurityScanModelTestCase(TestCase):
    """Test cases for PluginVersionSecurityScan model"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

        self.plugin = Plugin.objects.create(
            name="Test Plugin",
            package_name="test_plugin",
            description="A test plugin",
            created_by=self.user,
            author="Test Author",
            email="author@example.com",
        )

        # Create a dummy package file
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, "test.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("test_plugin/__init__.py", "# test")

        self.version = PluginVersion.objects.create(
            plugin=self.plugin,
            version="1.0.0",
            min_qg_version="3.0",
            package=zip_path,
            created_by=self.user,
        )

    def test_overall_status_passed(self):
        """Test overall_status property for passed scan"""
        scan = PluginVersionSecurityScan.objects.create(
            plugin_version=self.version,
            total_checks=10,
            passed_checks=10,
            warning_count=0,
            critical_count=0,
            info_count=0,
        )

        self.assertEqual(scan.overall_status, "passed")

    def test_overall_status_critical(self):
        """Test overall_status property for critical scan"""
        scan = PluginVersionSecurityScan.objects.create(
            plugin_version=self.version,
            total_checks=10,
            passed_checks=7,
            warning_count=0,
            critical_count=3,
            info_count=0,
        )

        self.assertEqual(scan.overall_status, "critical")

    def test_overall_status_warning(self):
        """Test overall_status property for warning scan"""
        scan = PluginVersionSecurityScan.objects.create(
            plugin_version=self.version,
            total_checks=10,
            passed_checks=8,
            warning_count=2,
            critical_count=0,
            info_count=0,
        )

        self.assertEqual(scan.overall_status, "warning")

    def test_overall_status_info(self):
        """Test overall_status property for info scan"""
        scan = PluginVersionSecurityScan.objects.create(
            plugin_version=self.version,
            total_checks=10,
            passed_checks=9,
            warning_count=0,
            critical_count=0,
            info_count=1,
        )

        self.assertEqual(scan.overall_status, "info")

    def test_pass_rate_calculation(self):
        """Test pass_rate property calculation"""
        scan = PluginVersionSecurityScan.objects.create(
            plugin_version=self.version,
            total_checks=10,
            passed_checks=8,
            warning_count=2,
            critical_count=0,
            info_count=0,
        )

        self.assertEqual(scan.pass_rate, 80.0)

    def test_pass_rate_zero_checks(self):
        """Test pass_rate property with zero checks"""
        scan = PluginVersionSecurityScan.objects.create(
            plugin_version=self.version, total_checks=0, passed_checks=0
        )

        self.assertEqual(scan.pass_rate, 0)

    def test_str_representation(self):
        """Test string representation of scan"""
        scan = PluginVersionSecurityScan.objects.create(
            plugin_version=self.version, total_checks=10, passed_checks=10
        )

        str_repr = str(scan)
        self.assertIn("Test Plugin", str_repr)
        self.assertIn("1.0.0", str_repr)
