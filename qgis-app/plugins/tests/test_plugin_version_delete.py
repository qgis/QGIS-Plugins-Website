from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from plugins.models import Plugin, PluginVersion


class SetupMixin:
    fixtures = ["fixtures/auth.json"]

    def setUp(self) -> None:
        self.creator = User.objects.get(id=2)
        self.staff = User.objects.get(id=3)
        self.plugin = Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name="test-delete",
            name="test plugin delete",
            about="this is a test for plugin delete",
            author="author plugin",
        )
        self.version1 = PluginVersion.objects.create(
            plugin=self.plugin,
            created_by=self.creator,
            min_qg_version="0.0.0",
            max_qg_version="99.99.99",
            version="0.1",
            approved=False,
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


class TestPluginVersionDeleteView(SetupMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse(
            "version_delete", args=[self.plugin.package_name, self.version1.version]
        )

    def test_delete_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_only_editor_or_staff_can_delete(self):
        user = User.objects.create(username="otheruser")
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "You cannot create or modify versions of this plugin."
        )

    def test_delete_confirm_page_loads(self):
        self.client.force_login(self.creator)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delete version")

    def test_delete_version(self):
        self.client.force_login(self.creator)
        response = self.client.post(self.url, {"delete_confirm": "1"})
        self.assertRedirects(response, self.plugin.get_absolute_url())
        self.assertFalse(PluginVersion.objects.filter(pk=self.version1.pk).exists())


class TestPluginVersionBulkDeleteView(SetupMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("versions_bulk_delete", args=[self.plugin.package_name])

    def test_bulk_delete_requires_login(self):
        response = self.client.post(
            self.url, {"selected_versions": [self.version1.pk, self.version2.pk]}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_only_editor_or_staff_can_bulk_delete(self):
        user = User.objects.create(username="otheruser")
        self.client.force_login(user)
        response = self.client.post(
            self.url, {"selected_versions": [self.version1.pk, self.version2.pk]}
        )
        self.assertRedirects(response, self.plugin.get_absolute_url())
        self.assertTrue(PluginVersion.objects.filter(pk=self.version1.pk).exists())

    def test_bulk_delete_confirm_page(self):
        self.client.force_login(self.creator)
        response = self.client.post(
            self.url, {"selected_versions": [self.version1.pk, self.version2.pk]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delete selected versions")
        self.assertContains(response, self.version1.version)
        self.assertContains(response, self.version2.version)

    def test_bulk_delete_versions(self):
        self.client.force_login(self.creator)
        # First, show confirm page
        response = self.client.post(
            self.url, {"selected_versions": [self.version1.pk, self.version2.pk]}
        )
        self.assertEqual(response.status_code, 200)
        # Then, confirm deletion
        response = self.client.post(
            self.url,
            {
                "selected_versions": [self.version1.pk, self.version2.pk],
                "confirm_bulk_delete": "1",
            },
        )
        self.assertRedirects(response, self.plugin.get_absolute_url())
        self.assertFalse(PluginVersion.objects.filter(pk=self.version1.pk).exists())
        self.assertFalse(PluginVersion.objects.filter(pk=self.version2.pk).exists())
