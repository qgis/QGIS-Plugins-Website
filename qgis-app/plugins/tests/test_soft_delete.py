"""
Tests for the soft delete functionality of plugins and versions.
"""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from plugins.models import Plugin, PluginVersion
from plugins.tasks.delete_marked_plugins import delete_marked_plugins


class SetupMixin:
    """Mixin to set up common test data."""

    fixtures = ["fixtures/auth.json"]

    def setUp(self) -> None:
        self.creator = User.objects.get(id=2)
        self.staff = User.objects.get(id=3)
        self.plugin = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-soft-delete",
            name="test plugin soft delete",
            about="this is a test for plugin soft delete",
            author="author plugin",
        )
        self.version1 = PluginVersion.objects.create(
            plugin=self.plugin,
            created_by=self.creator,
            min_qg_version="0.0.0",
            max_qg_version="99.99.99",
            version="0.1",
            approved=True,
            external_deps="test",
        )
        self.version2 = PluginVersion.objects.create(
            plugin=self.plugin,
            created_by=self.creator,
            min_qg_version="0.0.0",
            max_qg_version="99.99.99",
            version="0.2",
            approved=False,
            external_deps="test",
        )


class TestPluginSoftDelete(SetupMixin, TestCase):
    """Test soft delete functionality for plugins."""

    def setUp(self):
        super().setUp()
        self.delete_url = reverse("plugin_delete", args=[self.plugin.package_name])
        self.restore_url = reverse("plugin_restore", args=[self.plugin.package_name])
        self.permanent_delete_url = reverse(
            "plugin_permanent_delete", args=[self.plugin.package_name]
        )

    def test_plugin_soft_delete_marks_as_deleted(self):
        """Test that deleting a plugin marks it as deleted instead of removing it."""
        self.client.force_login(self.creator)
        response = self.client.post(self.delete_url, {"delete_confirm": "1"})

        # Should redirect to my plugins
        self.assertRedirects(response, reverse("my_plugins"))

        # Plugin should still exist in database
        self.assertTrue(Plugin.objects.filter(pk=self.plugin.pk).exists())

        # Plugin should be marked as deleted
        plugin = Plugin.objects.get(pk=self.plugin.pk)
        self.assertTrue(plugin.is_deleted)
        self.assertIsNotNone(plugin.deleted_on)

    def test_soft_deleted_plugin_excluded_from_approved_objects(self):
        """Test that soft-deleted plugins don't appear in approved_objects."""
        # First, approve and verify plugin appears
        self.version1.approved = True
        self.version1.save()
        self.assertIn(self.plugin, Plugin.approved_objects.all())

        # Soft delete the plugin
        self.plugin.is_deleted = True
        self.plugin.deleted_on = timezone.now()
        self.plugin.save()

        # Plugin should not appear in approved_objects
        self.assertNotIn(self.plugin, Plugin.approved_objects.all())

    def test_soft_deleted_plugin_visible_in_my_plugins(self):
        """Test that soft-deleted plugins are visible to owners in My Plugins."""
        # Soft delete the plugin
        self.plugin.is_deleted = True
        self.plugin.deleted_on = timezone.now()
        self.plugin.save()

        # Login as creator
        self.client.force_login(self.creator)

        # Plugin should be visible in my plugins list
        response = self.client.get(reverse("my_plugins"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.plugin.name)

    def test_plugin_restore(self):
        """Test restoring a soft-deleted plugin."""
        # Soft delete first
        self.plugin.is_deleted = True
        self.plugin.deleted_on = timezone.now()
        self.plugin.save()

        # Restore the plugin
        self.client.force_login(self.creator)
        response = self.client.post(self.restore_url, {"restore_confirm": "1"})

        # Should redirect to plugin detail
        self.assertRedirects(response, self.plugin.get_absolute_url())

        # Plugin should no longer be marked as deleted
        plugin = Plugin.objects.get(pk=self.plugin.pk)
        self.assertFalse(plugin.is_deleted)
        self.assertIsNone(plugin.deleted_on)

    def test_plugin_permanent_delete(self):
        """Test permanently deleting a soft-deleted plugin (staff only)."""
        # Soft delete first
        self.plugin.is_deleted = True
        self.plugin.deleted_on = timezone.now()
        self.plugin.save()

        # Permanently delete the plugin using staff user
        self.client.force_login(self.staff)
        response = self.client.post(
            self.permanent_delete_url, {"permanent_delete_confirm": "1"}
        )

        # Should redirect to my plugins
        self.assertRedirects(response, reverse("my_plugins"))

        # Plugin should be completely removed from database
        self.assertFalse(Plugin.objects.filter(pk=self.plugin.pk).exists())

    def test_only_soft_deleted_plugins_can_be_restored(self):
        """Test that restore URL only works for soft-deleted plugins."""
        # Try to restore a non-deleted plugin
        self.client.force_login(self.creator)
        response = self.client.get(self.restore_url)

        # Should get 404
        self.assertEqual(response.status_code, 404)

    def test_only_soft_deleted_plugins_can_be_permanently_deleted(self):
        """Test that permanent delete URL only works for soft-deleted plugins."""
        # Try to permanently delete a non-deleted plugin
        self.client.force_login(self.creator)
        response = self.client.get(self.permanent_delete_url)

        # Should get 404
        self.assertEqual(response.status_code, 404)


class TestDeleteMarkedPluginsTask(SetupMixin, TestCase):
    """Test the Celery task for permanent deletion of marked plugins."""

    def test_task_deletes_old_marked_plugins(self):
        """Test that the task deletes plugins marked for deletion 30+ days ago."""
        # Mark plugin for deletion 31 days ago
        old_date = timezone.now() - datetime.timedelta(days=31)
        self.plugin.is_deleted = True
        self.plugin.deleted_on = old_date
        self.plugin.save()

        # Run the task
        result = delete_marked_plugins(days=30)

        # Plugin should be deleted
        self.assertFalse(Plugin.objects.filter(pk=self.plugin.pk).exists())
        self.assertEqual(result["plugins_deleted"], 1)
        self.assertIn(self.plugin.name, result["plugin_names"])

    def test_task_does_not_delete_recent_marked_plugins(self):
        """Test that the task doesn't delete recently marked plugins."""
        # Mark plugin for deletion 20 days ago (less than 30)
        recent_date = timezone.now() - datetime.timedelta(days=20)
        self.plugin.is_deleted = True
        self.plugin.deleted_on = recent_date
        self.plugin.save()

        # Run the task
        result = delete_marked_plugins(days=30)

        # Plugin should NOT be deleted
        self.assertTrue(Plugin.objects.filter(pk=self.plugin.pk).exists())
        self.assertEqual(result["plugins_deleted"], 0)

    def test_task_with_custom_days_parameter(self):
        """Test that the task respects custom days parameter."""
        # Mark plugin for deletion 5 days ago
        date_5_days_ago = timezone.now() - datetime.timedelta(days=5)
        self.plugin.is_deleted = True
        self.plugin.deleted_on = date_5_days_ago
        self.plugin.save()

        # Run the task with days=3 (should delete)
        result = delete_marked_plugins(days=3)
        self.assertFalse(Plugin.objects.filter(pk=self.plugin.pk).exists())
        self.assertEqual(result["plugins_deleted"], 1)

    def test_task_handles_multiple_plugins(self):
        """Test that the task can handle multiple plugins."""
        # Create another plugin
        plugin2 = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-soft-delete-2",
            name="test plugin soft delete 2",
            about="second test plugin",
            author="author plugin",
        )

        # Mark both plugins for deletion 31 days ago
        old_date = timezone.now() - datetime.timedelta(days=31)

        self.plugin.is_deleted = True
        self.plugin.deleted_on = old_date
        self.plugin.save()

        plugin2.is_deleted = True
        plugin2.deleted_on = old_date
        plugin2.save()

        # Run the task
        result = delete_marked_plugins(days=30)

        # Both plugins should be deleted
        self.assertEqual(result["plugins_deleted"], 2)


class TestPermanentDeletePermissions(SetupMixin, TestCase):
    """Test that only staff users can permanently delete plugins."""

    def setUp(self):
        super().setUp()
        # Create a non-staff user who is an owner
        self.owner = User.objects.create_user(
            username="plugin_owner", email="owner@example.com", password="test123"
        )
        self.plugin.owners.add(self.owner)

        # Mark plugin as deleted
        self.plugin.is_deleted = True
        self.plugin.deleted_on = timezone.now()
        self.plugin.save()

    def test_non_staff_cannot_permanently_delete_plugin(self):
        """Test that non-staff users cannot permanently delete plugins."""
        self.client.force_login(self.owner)
        url = reverse("plugin_permanent_delete", args=[self.plugin.package_name])

        response = self.client.post(url, {"permanent_delete_confirm": "1"})

        # Should redirect to plugin detail with error message
        self.assertRedirects(response, self.plugin.get_absolute_url())

        # Plugin should still exist
        self.assertTrue(Plugin.objects.filter(pk=self.plugin.pk).exists())

        # Check error message
        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertIn("Only staff users can permanently delete", str(messages[0]))

    def test_staff_can_permanently_delete_plugin(self):
        """Test that staff users can permanently delete plugins."""
        self.client.force_login(self.staff)
        url = reverse("plugin_permanent_delete", args=[self.plugin.package_name])

        response = self.client.post(url, {"permanent_delete_confirm": "1"})

        # Should redirect to my plugins
        self.assertRedirects(response, reverse("my_plugins"))

        # Plugin should be deleted
        self.assertFalse(Plugin.objects.filter(pk=self.plugin.pk).exists())

    def test_creator_cannot_permanently_delete_plugin(self):
        """Test that even the creator (non-staff) cannot permanently delete plugins."""
        self.client.force_login(self.creator)
        url = reverse("plugin_permanent_delete", args=[self.plugin.package_name])

        response = self.client.post(url, {"permanent_delete_confirm": "1"})

        # Should redirect to plugin detail with error message
        self.assertRedirects(response, self.plugin.get_absolute_url())

        # Plugin should still exist
        self.assertTrue(Plugin.objects.filter(pk=self.plugin.pk).exists())


class TestAwaitingDeletionList(SetupMixin, TestCase):
    """Test the Awaiting Deletion plugins list view."""

    def test_awaiting_deletion_list_shows_deleted_plugins(self):
        """Test that the awaiting deletion list shows soft-deleted plugins."""
        # Mark plugin for deletion
        self.plugin.is_deleted = True
        self.plugin.deleted_on = timezone.now()
        self.plugin.save()

        # Login as staff
        self.client.force_login(self.staff)
        response = self.client.get(reverse("awaiting_deletion_plugins"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.plugin.name)
        self.assertIn(self.plugin, response.context["object_list"])

    def test_awaiting_deletion_list_does_not_show_active_plugins(self):
        """Test that active (non-deleted) plugins are not shown."""
        # Plugin is not deleted
        self.client.force_login(self.staff)
        response = self.client.get(reverse("awaiting_deletion_plugins"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.plugin.name)
        self.assertNotIn(self.plugin, response.context["object_list"])

    def test_awaiting_deletion_list_requires_staff_access(self):
        """Test that non-staff users cannot access the awaiting deletion list."""
        # Mark plugin for deletion
        self.plugin.is_deleted = True
        self.plugin.deleted_on = timezone.now()
        self.plugin.save()

        # Login as non-staff user (creator)
        self.client.force_login(self.creator)
        response = self.client.get(reverse("awaiting_deletion_plugins"))

        # Should get 404 for non-staff users
        self.assertEqual(response.status_code, 404)

    def test_awaiting_deletion_list_shows_multiple_deleted_plugins(self):
        """Test that multiple deleted plugins are shown in the list."""
        # Create another plugin
        plugin2 = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-soft-delete-2",
            name="test plugin soft delete 2",
            about="second test plugin",
            author="author plugin",
        )

        # Mark both plugins for deletion
        self.plugin.is_deleted = True
        self.plugin.deleted_on = timezone.now()
        self.plugin.save()

        plugin2.is_deleted = True
        plugin2.deleted_on = timezone.now()
        plugin2.save()

        # Login as staff
        self.client.force_login(self.staff)
        response = self.client.get(reverse("awaiting_deletion_plugins"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.plugin.name)
        self.assertContains(response, plugin2.name)
        self.assertEqual(len(response.context["object_list"]), 2)

    def test_awaiting_deletion_list_ordered_by_deletion_date(self):
        """Test that plugins are ordered by deletion date (most recent first)."""
        # Create another plugin
        plugin2 = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-soft-delete-2",
            name="test plugin soft delete 2",
            about="second test plugin",
            author="author plugin",
        )

        # Mark first plugin for deletion 2 days ago
        old_date = timezone.now() - datetime.timedelta(days=2)
        self.plugin.is_deleted = True
        self.plugin.deleted_on = old_date
        self.plugin.save()

        # Mark second plugin for deletion today
        plugin2.is_deleted = True
        plugin2.deleted_on = timezone.now()
        plugin2.save()

        # Login as staff
        self.client.force_login(self.staff)
        response = self.client.get(reverse("awaiting_deletion_plugins"))

        self.assertEqual(response.status_code, 200)
        plugins = list(response.context["object_list"])

        # Most recently deleted should be first
        self.assertEqual(plugins[0].package_name, "test-soft-delete-2")
        self.assertEqual(plugins[1].package_name, "test-soft-delete")
