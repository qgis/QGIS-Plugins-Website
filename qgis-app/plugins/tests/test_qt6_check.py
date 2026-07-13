"""
Unit tests for Qt6 check functionality
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from plugins.models import Plugin, PluginVersion
from plugins.tasks.save_qt6_result import save_qt6_result


class Qt6StatusModelTest(TestCase):
    """Test Qt6Status choices and default value on PluginVersion"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="testpass", email="test@test.com"
        )
        self.plugin = Plugin.objects.create(
            name="Test Plugin",
            package_name="TestPlugin",
            description="A test plugin",
            author="Test Author",
            email="test@test.com",
            created_by=self.user,
            repository="https://github.com/test/test",
            tracker="https://github.com/test/test/issues",
        )

    def test_default_qt6_status_is_not_run(self):
        """A newly created PluginVersion should have qt6_status set to NOT_RUN"""
        version = PluginVersion(
            plugin=self.plugin,
            version="1.0.0",
            min_qg_version="3.0.0",
        )
        self.assertEqual(version.qt6_status, PluginVersion.Qt6Status.NOT_RUN)

    def test_qt6_status_choices(self):
        """Qt6Status should have the expected choices"""
        choices = [c[0] for c in PluginVersion.Qt6Status.choices]
        self.assertIn("not_run", choices)
        self.assertIn("pending", choices)
        self.assertIn("compatible", choices)
        self.assertIn("not_compatible", choices)

    def test_qt6_status_can_be_updated(self):
        """Qt6 status should be updatable on a PluginVersion"""
        version = PluginVersion(
            plugin=self.plugin,
            version="1.0.0",
            min_qg_version="3.0.0",
        )
        version.qt6_status = PluginVersion.Qt6Status.COMPATIBLE
        self.assertEqual(version.qt6_status, PluginVersion.Qt6Status.COMPATIBLE)

        version.qt6_status = PluginVersion.Qt6Status.NOT_COMPATIBLE
        self.assertEqual(version.qt6_status, PluginVersion.Qt6Status.NOT_COMPATIBLE)


class SaveQt6ResultTaskTest(TestCase):
    """Test the save_qt6_result Celery task"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="testpass", email="test@test.com"
        )
        self.plugin = Plugin.objects.create(
            name="Test Plugin",
            package_name="TestPlugin",
            description="A test plugin",
            author="Test Author",
            email="test@test.com",
            created_by=self.user,
            repository="https://github.com/test/test",
            tracker="https://github.com/test/test/issues",
        )
        self.plugin_version = PluginVersion.objects.create(
            plugin=self.plugin,
            version="1.0.0",
            min_qg_version="3.0.0",
            package="packages/test.zip",
        )

    def test_save_qt6_result_compatible(self):
        """save_qt6_result should set status to COMPATIBLE when no issues found"""

        logs = "=== dry_run mode | Start Logs ===\n"
        save_qt6_result(self.plugin_version.pk, True, logs)

        self.plugin_version.refresh_from_db()
        self.assertEqual(
            self.plugin_version.qt6_status, PluginVersion.Qt6Status.COMPATIBLE
        )
        self.assertIsNotNone(self.plugin_version.qt6_checked_on)

    def test_save_qt6_result_not_compatible_with_issues(self):
        """save_qt6_result should set status to NOT_COMPATIBLE when issues found"""

        logs = (
            "=== dry_run mode | Start Logs ===\n"
            "/tmp/tmpXXX/myplugin/core/file.py:10:5 - Enum error, add 'LayerType' before 'VectorLayer'\n"
        )
        save_qt6_result(self.plugin_version.pk, True, logs)

        self.plugin_version.refresh_from_db()
        self.assertEqual(
            self.plugin_version.qt6_status, PluginVersion.Qt6Status.NOT_COMPATIBLE
        )

    def test_save_qt6_result_not_compatible_when_script_failed(self):
        """save_qt6_result should set status to NOT_COMPATIBLE when script failed"""

        save_qt6_result(self.plugin_version.pk, False, "Script execution failed")

        self.plugin_version.refresh_from_db()
        self.assertEqual(
            self.plugin_version.qt6_status, PluginVersion.Qt6Status.NOT_COMPATIBLE
        )

    def test_save_qt6_result_nonexistent_plugin_version(self):
        """save_qt6_result should handle gracefully a non-existent PluginVersion pk"""

        # Should not raise an exception
        save_qt6_result(99999, True, "some logs")


class TriggerQt6CheckSignalTest(TestCase):
    """Test the post_save signal that triggers the Qt6 check"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="testpass", email="test@test.com"
        )
        self.plugin = Plugin.objects.create(
            name="Test Plugin",
            package_name="TestPlugin",
            description="A test plugin",
            author="Test Author",
            email="test@test.com",
            created_by=self.user,
            repository="https://github.com/test/test",
            tracker="https://github.com/test/test/issues",
        )

    def test_signal_not_triggered_without_package(self):
        """Signal should be skipped when PluginVersion has no package file"""
        with patch("plugins.signals.app.send_task") as mock_send_task:
            PluginVersion.objects.create(
                plugin=self.plugin,
                version="1.0.0",
                min_qg_version="3.0.0",
                package="",
            )
            mock_send_task.assert_not_called()

    def test_signal_sends_task_with_correct_args(self):
        """Signal should send the qt6 task with pk and package path"""
        with patch("plugins.signals.app.send_task") as mock_send_task:
            with patch(
                "django.db.models.fields.files.FieldFile.path",
                new_callable=lambda: property(
                    lambda self: "/home/web/media/packages/test.zip"
                ),
            ):
                version = PluginVersion.objects.create(
                    plugin=self.plugin,
                    version="1.0.0",
                    min_qg_version="3.0.0",
                    package="packages/test.zip",
                )
                mock_send_task.assert_called_once_with(
                    "plugins.tasks.run_check_qt6.run_qgis_script",
                    args=[version.pk, "/home/web/media/packages/test.zip"],
                    queue="qt6",
                )

    def test_signal_sets_pending_status(self):
        """Signal should set qt6_status to PENDING before sending the task"""
        with patch("plugins.signals.app.send_task"):
            with patch(
                "django.db.models.fields.files.FieldFile.path",
                new_callable=lambda: property(
                    lambda self: "/home/web/media/packages/test.zip"
                ),
            ):
                version = PluginVersion.objects.create(
                    plugin=self.plugin,
                    version="1.0.0",
                    min_qg_version="3.0.0",
                    package="packages/test.zip",
                )
                version.refresh_from_db()
                self.assertEqual(
                    version.qt6_status, PluginVersion.Qt6Status.PENDING
                )