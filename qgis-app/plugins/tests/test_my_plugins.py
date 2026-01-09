"""
Tests for MyPluginsList view to ensure it only shows user's own plugins
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from plugins.models import Plugin

User = get_user_model()


class TestMyPluginsList(TestCase):
    """Test the My Plugins list view"""

    @classmethod
    def setUpTestData(cls):
        # Create users
        cls.user1 = User.objects.create_user(
            username="user1", email="user1@example.com", password="password123"
        )
        cls.user2 = User.objects.create_user(
            username="user2", email="user2@example.com", password="password123"
        )

        # Create plugins for user1
        cls.plugin1 = Plugin.objects.create(
            name="User1 Plugin 1",
            package_name="user1_plugin1",
            created_by=cls.user1,
            description="Test plugin 1",
        )
        cls.plugin1.owners.add(cls.user1)

        cls.plugin2 = Plugin.objects.create(
            name="User1 Plugin 2",
            package_name="user1_plugin2",
            created_by=cls.user1,
            description="Test plugin 2",
        )
        cls.plugin2.owners.add(cls.user1)

        # Create a deleted plugin for user1
        cls.plugin3 = Plugin.objects.create(
            name="User1 Deleted Plugin",
            package_name="user1_deleted",
            created_by=cls.user1,
            description="Deleted test plugin",
            is_deleted=True,
        )
        cls.plugin3.owners.add(cls.user1)

        # Create plugin for user2
        cls.plugin4 = Plugin.objects.create(
            name="User2 Plugin",
            package_name="user2_plugin",
            created_by=cls.user2,
            description="User2's plugin",
        )
        cls.plugin4.owners.add(cls.user2)

    def test_my_plugins_shows_only_users_plugins(self):
        """Test that My Plugins only shows the logged-in user's plugins"""
        self.client.login(username="user1", password="password123")
        response = self.client.get(reverse("my_plugins"))

        self.assertEqual(response.status_code, 200)

        # Get the plugins in the context
        plugins = list(response.context["object_list"])

        # Should have 3 plugins (including the deleted one)
        self.assertEqual(len(plugins), 3)

        # All plugins should belong to user1
        plugin_names = [p.package_name for p in plugins]
        self.assertIn("user1_plugin1", plugin_names)
        self.assertIn("user1_plugin2", plugin_names)
        self.assertIn("user1_deleted", plugin_names)

        # Should NOT include user2's plugin
        self.assertNotIn("user2_plugin", plugin_names)

    def test_my_plugins_includes_deleted_plugins(self):
        """Test that My Plugins includes soft-deleted plugins"""
        self.client.login(username="user1", password="password123")
        response = self.client.get(reverse("my_plugins"))

        plugins = list(response.context["object_list"])
        deleted_plugins = [p for p in plugins if p.is_deleted]

        # Should have 1 deleted plugin
        self.assertEqual(len(deleted_plugins), 1)
        self.assertEqual(deleted_plugins[0].package_name, "user1_deleted")

    def test_my_plugins_requires_login(self):
        """Test that My Plugins requires authentication"""
        response = self.client.get(reverse("my_plugins"))
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_different_user_sees_only_their_plugins(self):
        """Test that user2 only sees their own plugins"""
        self.client.login(username="user2", password="password123")
        response = self.client.get(reverse("my_plugins"))

        plugins = list(response.context["object_list"])

        # Should have only 1 plugin
        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0].package_name, "user2_plugin")

        # Should NOT see user1's plugins
        plugin_names = [p.package_name for p in plugins]
        self.assertNotIn("user1_plugin1", plugin_names)
        self.assertNotIn("user1_plugin2", plugin_names)
        self.assertNotIn("user1_deleted", plugin_names)
