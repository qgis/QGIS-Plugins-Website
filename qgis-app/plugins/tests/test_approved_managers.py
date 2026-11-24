"""
Tests for the managers that list approved and stable plugins.
"""

from django.contrib.auth.models import User
from django.db.models import QuerySet
from django.test import TestCase
from plugins.models import Plugin, PluginVersion


class ApprovedPluginManagersTestCase(TestCase):
    fixtures = ["fixtures/auth.json"]

    def setUp(self) -> None:
        self.creator = User.objects.get(id=2)

        self.many_versions = self._create_plugin("many-approved-versions")
        self._create_version(self.many_versions, "1.0", approved=True)
        self._create_version(self.many_versions, "1.1", approved=True)
        self._create_version(
            self.many_versions, "1.2", approved=True, experimental=True
        )

        self.unapproved = self._create_plugin("only-unapproved-versions")
        self._create_version(self.unapproved, "1.0", approved=False)

        self.stable_unapproved = self._create_plugin("stable-version-unapproved")
        self._create_version(self.stable_unapproved, "1.0", approved=False)
        self._create_version(
            self.stable_unapproved, "1.1", approved=True, experimental=True
        )

    def _create_plugin(self, package_name: str) -> Plugin:
        return Plugin.objects.create(
            created_by=self.creator,
            repository="http://example.com",
            tracker="http://example.com",
            package_name=package_name,
            name=package_name,
            about="A plugin for testing the list managers",
            author="author plugin",
        )

    def _create_version(
        self,
        plugin: Plugin,
        version: str,
        approved: bool,
        experimental: bool = False,
    ) -> PluginVersion:
        return PluginVersion.objects.create(
            plugin=plugin,
            created_by=self.creator,
            min_qg_version="3.0.0",
            max_qg_version="3.99.99",
            version=version,
            approved=approved,
            experimental=experimental,
        )

    def _rows_for(self, queryset: QuerySet[Plugin], plugin: Plugin) -> int:
        return sum(1 for row in queryset if row.pk == plugin.pk)

    def test_plugin_with_several_approved_versions_is_listed_once(self) -> None:
        for manager in (
            "approved_objects",
            "stable_objects",
            "popular_objects",
            "most_downloaded_objects",
        ):
            with self.subTest(manager=manager):
                queryset = getattr(Plugin, manager).all()
                self.assertEqual(self._rows_for(queryset, self.many_versions), 1)

    def test_plugin_without_approved_version_is_not_listed(self) -> None:
        for manager in ("approved_objects", "stable_objects"):
            with self.subTest(manager=manager):
                queryset = getattr(Plugin, manager).all()
                self.assertEqual(self._rows_for(queryset, self.unapproved), 0)

    def test_stable_needs_one_version_that_is_approved_and_stable(self) -> None:
        self.assertEqual(
            self._rows_for(Plugin.approved_objects.all(), self.stable_unapproved), 1
        )
        self.assertEqual(
            self._rows_for(Plugin.stable_objects.all(), self.stable_unapproved), 0
        )

    def test_chained_version_filter_still_lists_plugin_once(self) -> None:
        queryset = Plugin.approved_objects.filter(pluginversion__experimental=False)
        self.assertEqual(self._rows_for(queryset, self.many_versions), 1)
        self.assertEqual(
            queryset.get(package_name="many-approved-versions"), self.many_versions
        )
