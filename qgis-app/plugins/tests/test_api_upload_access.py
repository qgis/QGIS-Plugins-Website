"""Who may upload a new version of an existing plugin through plugin.upload."""

import os
from unittest.mock import patch
from xmlrpc.client import Fault

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase
from plugins.api import plugin_upload
from plugins.models import Plugin, PluginVersion

TESTFILE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "testfiles"))


def do_nothing(*args, **kwargs) -> None:
    pass


@patch("plugins.tasks.generate_plugins_xml", new=do_nothing)
@patch("plugins.validator._check_url_link", new=do_nothing)
@patch("plugins.tasks.run_security_scan.run_security_scan_task.delay", new=do_nothing)
class RpcUploadAccessTest(TestCase):
    def setUp(self) -> None:
        self.owner = User.objects.create_user(
            username="owner", email="owner@example.com", password="password"
        )
        self.outsider = User.objects.create_user(
            username="outsider", email="outsider@example.com", password="password"
        )
        # Same package name as valid_plugin.zip_, with no versions yet.
        self.plugin = Plugin.objects.create(
            package_name="test_modul",
            name="Original name",
            description="Original description",
            about="About text",
            author="Test Author",
            email="author@example.com",
            created_by=self.owner,
            maintainer=self.owner,
        )
        with open(os.path.join(TESTFILE_DIR, "valid_plugin.zip_"), "rb") as package:
            self.package = package.read()

    def _upload(self, user: User, **kwargs) -> tuple[int, int]:
        request = RequestFactory().post("/plugins/RPC2/")
        request.user = user
        return plugin_upload(self.package, request=request, **kwargs)

    def _assert_plugin_untouched(self) -> None:
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.name, "Original name")
        self.assertEqual(self.plugin.description, "Original description")
        self.assertFalse(PluginVersion.objects.filter(plugin=self.plugin).exists())

    def test_outsider_is_refused(self) -> None:
        with self.assertRaises(Fault) as raised:
            self._upload(self.outsider)

        self.assertIn("permission", raised.exception.faultString)
        self._assert_plugin_untouched()

    def test_trusted_outsider_cannot_auto_approve(self) -> None:
        ct = ContentType.objects.get_for_model(Plugin)
        perm = Permission.objects.get(codename="can_approve", content_type=ct)
        self.outsider.user_permissions.add(perm)
        trusted_outsider = User.objects.get(pk=self.outsider.pk)

        with self.assertRaises(Fault) as raised:
            self._upload(trusted_outsider, auto_approve=True)

        self.assertIn("permission", raised.exception.faultString)
        self._assert_plugin_untouched()

    def test_owner_can_upload(self) -> None:
        plugin_pk, version_pk = self._upload(self.owner)

        self.assertEqual(plugin_pk, self.plugin.pk)
        version = PluginVersion.objects.get(pk=version_pk)
        self.assertEqual(version.created_by, self.owner)
        self.plugin.refresh_from_db()
        self.assertEqual(self.plugin.name, "Test Plugin")

    def test_staff_can_upload(self) -> None:
        staff = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="password",
            is_staff=True,
        )

        plugin_pk, version_pk = self._upload(staff)

        self.assertEqual(plugin_pk, self.plugin.pk)
        self.assertEqual(PluginVersion.objects.get(pk=version_pk).created_by, staff)
