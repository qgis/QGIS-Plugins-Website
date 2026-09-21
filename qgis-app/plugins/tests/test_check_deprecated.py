"""
Unit tests for deprecated API check functionality
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from plugins.models import Plugin, PluginVersion
from plugins.tasks.save_deprecated_result import save_deprecated_result


class DeprecatedStatusModelTest(TestCase):
    """Test DeprecatedStatus choices and default value on PluginVersion"""

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

    def test_default_deprecated_status_is_not_run(self):
        """A newly created PluginVersion should have deprecated_status set to NOT_RUN"""
        version = PluginVersion(
            plugin=self.plugin,
            version="1.0.0",
            min_qg_version="3.0.0",
        )
        self.assertEqual(
            version.deprecated_status, PluginVersion.DeprecatedStatus.NOT_RUN
        )

    def test_deprecated_status_choices(self):
        """DeprecatedStatus should have the expected choices"""
        choices = [c[0] for c in PluginVersion.DeprecatedStatus.choices]
        self.assertIn("not_run", choices)
        self.assertIn("pending", choices)
        self.assertIn("no_deprecated", choices)
        self.assertIn("has_deprecated", choices)

    def test_deprecated_status_can_be_updated(self):
        """deprecated_status should be updatable on a PluginVersion"""
        version = PluginVersion(
            plugin=self.plugin,
            version="1.0.0",
            min_qg_version="3.0.0",
        )
        version.deprecated_status = PluginVersion.DeprecatedStatus.NO_DEPRECATED
        self.assertEqual(
            version.deprecated_status, PluginVersion.DeprecatedStatus.NO_DEPRECATED
        )

        version.deprecated_status = PluginVersion.DeprecatedStatus.HAS_DEPRECATED
        self.assertEqual(
            version.deprecated_status, PluginVersion.DeprecatedStatus.HAS_DEPRECATED
        )


class SaveDeprecatedResultTaskTest(TestCase):
    """Test the save_deprecated_result Celery task"""

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

    def test_save_deprecated_result_no_deprecated(self):
        """save_deprecated_result should set status to NO_DEPRECATED when no issues found"""
        save_deprecated_result(self.plugin_version.pk, True, "")

        self.plugin_version.refresh_from_db()
        self.assertEqual(
            self.plugin_version.deprecated_status,
            PluginVersion.DeprecatedStatus.NO_DEPRECATED,
        )
        self.assertIsNotNone(self.plugin_version.deprecated_checked_on)

    def test_save_deprecated_result_has_deprecated(self):
        """save_deprecated_result should set status to HAS_DEPRECATED when issues found"""
        logs = '  /tmp/tmpXXX/myplugin/core/file.py:325:29 - error: The method "setMinimal" in class "QgsRectangle" is deprecated'
        save_deprecated_result(self.plugin_version.pk, True, logs)

        self.plugin_version.refresh_from_db()
        self.assertEqual(
            self.plugin_version.deprecated_status,
            PluginVersion.DeprecatedStatus.HAS_DEPRECATED,
        )

    def test_save_deprecated_result_failed_script(self):
        """save_deprecated_result should set status to NOT_RUN when script failed"""
        save_deprecated_result(self.plugin_version.pk, False, "Script execution failed")

        self.plugin_version.refresh_from_db()
        self.assertEqual(
            self.plugin_version.deprecated_status,
            PluginVersion.DeprecatedStatus.NOT_RUN,
        )

    def test_save_deprecated_result_nonexistent_plugin_version(self):
        """save_deprecated_result should handle gracefully a non-existent PluginVersion pk"""
        # Should not raise an exception
        save_deprecated_result(99999, True, "some logs")


class TriggerDeprecatedCheckSignalTest(TestCase):
    """Test the post_save signal that triggers the deprecated check"""

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

    def test_signal_sets_pending_status(self):
        """Signal should set deprecated_status to PENDING before sending the task"""
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
                    version.deprecated_status,
                    PluginVersion.DeprecatedStatus.PENDING,
                )
