"""Standalone security-check CLI for QGIS plugin authors.

Runs the exact same checks as the QGIS plugins web platform, locally, before
uploading a plugin version. Rules are fetched read-only from the platform so
they never drift from what the platform enforces.
"""

__version__ = "0.1.0"
