# Security Scanning Feature Documentation

## Overview

The QGIS Plugins Website includes an automated security, quality, and code analysis system that scans all uploaded plugin packages using **industry-standard professional security tools**. This is a **non-blocking, informational feature** designed to help developers identify potential security issues, code quality problems, and best practice violations.

The scanner uses a **hybrid approach**: some tools are imported as Python libraries for better integration, while others use subprocess calls for more reliable output capture and to avoid logging/console spam issues.

## Security Tools Used

The scanner leverages professional open-source security tools:

1. **[Bandit](https://github.com/PyCQA/bandit)** - Industry-standard security linter for Python code
   - **Method**: Python API import via `bandit.core.manager` and `bandit.core.config`
   - Detects common security issues
   - Identifies SQL injection vulnerabilities
   - Finds hardcoded passwords and secrets
   - Checks for unsafe function usage

2. **[detect-secrets](https://github.com/Yelp/detect-secrets)** - Yelp's secrets detection tool
   - **Method**: Subprocess with JSON output (`detect-secrets scan --all-files`)
   - Finds API keys, tokens, passwords
   - Detects various secret patterns
   - Low false-positive rate
   - Uses subprocess to avoid console logging issues

3. **[Safety](https://github.com/pyupio/safety)** - Dependency vulnerability scanner
   - **Method**: Python API import via `safety.safety.check`
   - Checks against CVE database
   - Identifies known vulnerable packages
   - Provides security advisories
   - Recursively searches for requirements files in all subdirectories

4. **[Flake8](https://flake8.pycqa.org/)** - Python code quality checker
   - **Method**: Subprocess with JSON output (`flake8 --format=json`)
   - Requires `flake8-json` package for structured output
   - PEP 8 style guide enforcement
   - Syntax error detection
   - Code complexity analysis
   - Shows first 20 issues with helpful command hint for developers

5. **Fallback Checks** - When tools are unavailable:
   - Manual Python syntax validation using `ast.parse()`
   - Typosquatting package detection
   - File permission analysis
   - Suspicious file detection

## Key Features

### 🔍 What Gets Scanned

1. **Bandit Security Analysis (CRITICAL)**
   - Common security vulnerabilities in Python
   - SQL injection risks
   - Hardcoded passwords and keys
   - Use of unsafe functions (`eval`, `exec`, `pickle`)
   - Shell injection vulnerabilities
   - Weak cryptography usage
   - And 100+ other security checks

2. **Secrets Detection (CRITICAL)**
   - API keys and tokens
   - AWS credentials
   - Private SSH keys
   - Database connection strings
   - OAuth tokens
   - Generic high-entropy strings

3. **Dependencies Vulnerability Check (WARNING)**
   - Known CVEs in dependencies
   - Outdated vulnerable packages
   - Security advisories
   - Typosquatting detection

4. **Code Quality - Flake8 (INFO)**
   - Python syntax errors
   - PEP 8 style violations
   - Undefined names
   - Unused imports
   - Code complexity warnings
   - Displays first 20 issues with developer hint to run full flake8 locally

5. **File Analysis (INFO/WARNING)**
   - Executable files detection
   - Hidden files
   - Suspicious file types
   - Unusual file permissions

## How It Works

### Upload Flow

1. User uploads a plugin ZIP file
2. Plugin passes **blocking validation** (metadata, structure, size limits)
3. Plugin is saved to database
4. **Security scan runs automatically** in the background
5. Results are stored and displayed immediately
6. User sees scan summary in success messages
7. Full details available on version detail page

### Scan Process

```python
# Triggered after successful plugin version creation
security_scan = run_security_scan(plugin_version)

# Scanner analyzes:
# - All .py files for code patterns
# - Configuration files (.txt, .cfg, .ini, .json, .yaml)
# - File permissions and types
# - Package dependencies

# Results stored in PluginVersionSecurityScan model
```

## User Interface

### 1. Upload Success Messages

After successful upload, users see:
- ✓ Green success: "All security checks passed (95%)"
- ⚠ Orange warning: "Security scan found 3 warnings"
- 🔴 Red critical: "Security scan found 2 critical issues"

### 2. Version Detail Page - Security Tab

New dedicated tab showing:

**Summary Card:**
- Overall status (Passed/Critical/Warning/Info)
- Pass rate percentage
- Scan timestamp

**Quick Stats Grid:**
- Total Checks
- Passed Checks
- Warnings Count
- Critical Issues Count
- Files Scanned
- Total Issues
- Info Items

**Detailed Check Results:**
Each check displays as an expandable card:
- Check name and category badge
- Description of what was checked
- Files checked count
- Issues found count
- Expandable details section showing:
  - Affected file names
  - Line numbers
  - Issue descriptions
  - Code snippets (when applicable)

### Mobile Responsive Design

- Stacked columns for stats on mobile
- Compact tabs with badge indicators
- Scrollable detail sections
- Touch-friendly expand/collapse controls

## For Developers

### Adding New Security Checks

To add a new check to the scanner:

```python
# In plugins/security_scanner.py

def _check_your_new_feature(self):
    """Check description"""
    check = SecurityCheck(
        name="Your Check Name",
        category="security",  # or 'quality', 'best_practice'
        severity="warning",   # or 'critical', 'info'
        description="What this check does"
    )

    try:
        with zipfile.ZipFile(self.package_path, 'r') as zf:
            for file_info in zf.filelist:
                # Your analysis logic here
                check.files_checked += 1

                # If issue found:
                check.issues_found += 1
                check.details.append({
                    'file': file_info.filename,
                    'line': line_number,
                    'message': 'Issue description'
                })

        check.passed = check.issues_found == 0
    except Exception as e:
        check.details.append({
            'file': 'N/A',
            'message': f"Error: {str(e)}"
        })

    self.checks.append(check)

# Then call it in scan() method:
def scan(self):
    self._check_sensitive_data()
    self._check_dangerous_functions()
    self._check_your_new_feature()  # Add here
    # ...
```

### Running Manual Scans

```python
from plugins.models import PluginVersion
from plugins.security_utils import run_security_scan

version = PluginVersion.objects.get(pk=123)
scan_result = run_security_scan(version)
```

### Accessing Scan Results

```python
# In views
version = PluginVersion.objects.get(...)
if hasattr(version, 'security_scan'):
    scan = version.security_scan
    print(f"Pass rate: {scan.pass_rate}%")
    print(f"Status: {scan.overall_status}")
    print(f"Report: {scan.scan_report}")
```

## Database Schema

```python
class PluginVersionSecurityScan(models.Model):
    plugin_version = OneToOneField(PluginVersion, related_name='security_scan')
    scanned_on = DateTimeField(auto_now_add=True)

    # Summary statistics
    total_checks = IntegerField(default=0)
    passed_checks = IntegerField(default=0)
    warning_count = IntegerField(default=0)
    critical_count = IntegerField(default=0)
    info_count = IntegerField(default=0)
    files_scanned = IntegerField(default=0)
    total_issues = IntegerField(default=0)

    # Full report (JSON)
    scan_report = JSONField(default=dict)

    @property
    def overall_status(self):
        """Returns: 'passed', 'info', 'warning', or 'critical'"""

    @property
    def pass_rate(self):
        """Returns: percentage of passed checks"""
```

## Important Notes

### ✅ Non-Blocking
- Scans **never prevent plugin upload**
- Results are informational only
- Plugin approval process unchanged

### ⚠️ False Positives
- Some warnings may be false positives
- Review results in context of your plugin
- Legitimate use cases may trigger warnings
- Example: A password manager plugin may need to handle passwords

### 🔒 Security Considerations
- Scans run on server after upload
- Hybrid approach: some tools use Python API, others use subprocess for reliability
- Subprocess stderr suppressed to prevent console spam
- No external services used (except Safety database lookups)
- File analysis done locally
- Results stored in database
- Graceful degradation when tools unavailable

### 📊 Admin Features
- View all scans in Django admin
- Filter by status, date, plugin
- Detailed JSON reports available
- Color-coded status indicators

## Migration

To apply the database changes:

```bash
cd dockerize
make devweb-migrate  # Development
# or
make migrate         # Production
```

## Testing

```bash
# Run tests
make devweb-runtests

# Test specific functionality
python manage.py shell
>>> from plugins.security_scanner import PluginSecurityScanner
>>> scanner = PluginSecurityScanner('/path/to/plugin.zip')
>>> report = scanner.scan()
>>> print(report)
```

## Future Enhancements

Potential improvements:
- Integration with external security scanning APIs
- Machine learning-based malware detection
- Historical trend analysis
- Automated security advisories
- Comparison with previous versions
- Custom check configurations per plugin

## Support

For questions or issues:
- Check the Django admin for detailed scan reports
- Review the scan_report JSON field for complete details
- Check logs for scanner errors: `plugins.security_utils`
- File issues on the QGIS-Plugins-Website GitHub repository
