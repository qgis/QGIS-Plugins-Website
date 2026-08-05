from django.contrib.auth.models import AnonymousUser, User
from django.template import Context
from django.test import RequestFactory, TestCase
from django.urls import ResolverMatch, reverse
from plugins.models import Plugin, PluginVersion
from plugins.templatetags.plugin_breadcrumbs import plugin_breadcrumbs


class BreadcrumbsTestBase(TestCase):
    def setUp(self):
        self.creator = User.objects.create(
            username="breadcrumb_creator", email="breadcrumb@example.com"
        )
        self.creator.set_password("password")
        self.creator.is_staff = True
        self.creator.save()
        self.plugin = Plugin.objects.create(
            created_by=self.creator,
            name="Breadcrumb Plugin",
            package_name="breadcrumb_plugin",
        )
        self.version = PluginVersion.objects.create(
            plugin=self.plugin,
            created_by=self.creator,
            version="1.1.0",
            min_qg_version="0.0.1",
            max_qg_version="2.2.0",
            approved=True,
        )


class TestPluginBreadcrumbsTag(BreadcrumbsTestBase):
    """Unit tests driving the tag directly with a faked resolver match."""

    def _render(self, url_name, kwargs, extra_context=None, user=None):
        request = RequestFactory().get("/")
        request.user = user if user is not None else AnonymousUser()
        request.resolver_match = ResolverMatch(
            func=lambda r: None, args=(), kwargs=kwargs, url_name=url_name
        )
        context = Context({"request": request})
        if extra_context:
            context.update(extra_context)
        return plugin_breadcrumbs(context)

    def _crumbs(self, url_name, kwargs, extra_context=None):
        return self._render(url_name, kwargs, extra_context)["breadcrumbs"]

    def _titles(self, crumbs):
        return [str(crumb["title"]) for crumb in crumbs]

    def test_plugin_detail_has_no_breadcrumbs(self):
        # The detail page is the root of the trail, so a lone crumb naming it
        # would add no navigation.
        self.assertEqual(
            self._crumbs("plugin_detail", {"package_name": self.plugin.package_name}),
            [],
        )

    def test_plugin_update_appends_leaf(self):
        crumbs = self._crumbs(
            "plugin_update", {"package_name": self.plugin.package_name}
        )
        self.assertEqual(self._titles(crumbs), ["Breadcrumb Plugin", "Edit"])
        self.assertEqual(
            crumbs[0]["url"],
            reverse("plugin_detail", args=[self.plugin.package_name]),
        )
        # Deepest crumb is the current page and must not be a link.
        self.assertIsNone(crumbs[-1]["url"])

    def test_version_detail_has_no_leaf_crumb(self):
        crumbs = self._crumbs(
            "version_detail",
            {"package_name": self.plugin.package_name, "version": "1.1.0"},
        )
        self.assertEqual(self._titles(crumbs), ["Breadcrumb Plugin", "1.1.0"])
        self.assertIsNone(crumbs[-1]["url"])

    def test_version_pages_link_up_to_the_versions_tab(self):
        crumbs = self._crumbs(
            "version_update",
            {"package_name": self.plugin.package_name, "version": "1.1.0"},
        )
        self.assertEqual(
            crumbs[0]["url"],
            reverse("plugin_detail", args=[self.plugin.package_name])
            + "#plugin-versions",
        )

    def test_plugin_level_pages_link_up_without_anchor(self):
        crumbs = self._crumbs(
            "plugin_update", {"package_name": self.plugin.package_name}
        )
        self.assertEqual(
            crumbs[0]["url"],
            reverse("plugin_detail", args=[self.plugin.package_name]),
        )

    def test_version_feedback_nests_under_version(self):
        crumbs = self._crumbs(
            "version_feedback",
            {"package_name": self.plugin.package_name, "version": "1.1.0"},
        )
        self.assertEqual(
            self._titles(crumbs),
            ["Breadcrumb Plugin", "1.1.0", "Feedback"],
        )
        self.assertEqual(
            crumbs[1]["url"],
            reverse("version_detail", args=[self.plugin.package_name, "1.1.0"]),
        )

    def test_token_pages_nest_under_token_list(self):
        crumbs = self._crumbs(
            "plugin_token_create", {"package_name": self.plugin.package_name}
        )
        self.assertEqual(
            self._titles(crumbs),
            ["Breadcrumb Plugin", "Tokens", "New token"],
        )
        self.assertEqual(
            crumbs[1]["url"],
            reverse("plugin_token_list", args=[self.plugin.package_name]),
        )

    def test_token_list_is_the_current_page(self):
        crumbs = self._crumbs(
            "plugin_token_list", {"package_name": self.plugin.package_name}
        )
        self.assertEqual(self._titles(crumbs), ["Breadcrumb Plugin", "Tokens"])
        self.assertIsNone(crumbs[-1]["url"])

    def test_unknown_url_name_yields_no_leaf(self):
        crumbs = self._crumbs(
            "plugin_versions_json", {"package_name": self.plugin.package_name}
        )
        self.assertEqual(self._titles(crumbs), ["Breadcrumb Plugin"])

    def test_no_package_name_yields_no_breadcrumbs(self):
        self.assertEqual(self._crumbs("approved_plugins", {}), [])

    def test_no_resolver_match_yields_no_breadcrumbs(self):
        self.assertEqual(plugin_breadcrumbs(Context({}))["breadcrumbs"], [])

    def test_unknown_package_falls_back_to_package_name(self):
        crumbs = self._crumbs("plugin_update", {"package_name": "ghost_plugin"})
        self.assertEqual(self._titles(crumbs)[0], "ghost_plugin")

    def test_plugin_name_taken_from_context_without_query(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        request.resolver_match = ResolverMatch(
            func=lambda r: None,
            args=(),
            kwargs={"package_name": self.plugin.package_name},
            url_name="plugin_update",
        )
        context = Context({"request": request, "plugin": self.plugin})
        with self.assertNumQueries(0):
            crumbs = plugin_breadcrumbs(context)["breadcrumbs"]
        self.assertEqual(str(crumbs[0]["title"]), self.plugin.name)


class TestQuickLinks(BreadcrumbsTestBase):
    """The tab deep-links offered alongside the trail on plugin sub-pages."""

    def _links(self, url_name, kwargs, user=None):
        request = RequestFactory().get("/")
        request.user = user if user is not None else AnonymousUser()
        request.resolver_match = ResolverMatch(
            func=lambda r: None, args=(), kwargs=kwargs, url_name=url_name
        )
        result = plugin_breadcrumbs(Context({"request": request}))
        return [str(link["title"]) for link in result["quick_links"]]

    def test_detail_page_has_no_quick_links(self):
        # The detail page already renders the real tab bar.
        self.assertEqual(
            self._links("plugin_detail", {"package_name": self.plugin.package_name}),
            [],
        )

    def test_anonymous_gets_only_public_tabs(self):
        self.assertEqual(
            self._links("plugin_update", {"package_name": self.plugin.package_name}),
            ["Details", "Versions"],
        )

    def test_about_tab_only_when_plugin_has_about(self):
        self.plugin.about = "About this plugin"
        self.plugin.save()
        self.assertEqual(
            self._links("plugin_update", {"package_name": self.plugin.package_name}),
            ["About", "Details", "Versions"],
        )

    def test_editor_gets_stats_and_tokens(self):
        self.assertEqual(
            self._links(
                "plugin_update",
                {"package_name": self.plugin.package_name},
                user=self.creator,
            ),
            ["Details", "Versions", "Stats", "Tokens"],
        )

    def test_other_user_gets_no_privileged_tabs(self):
        other = User.objects.create(username="other", email="other@example.com")
        self.assertEqual(
            self._links(
                "plugin_update",
                {"package_name": self.plugin.package_name},
                user=other,
            ),
            ["Details", "Versions"],
        )

    def test_quick_links_point_at_tab_anchors(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        request.resolver_match = ResolverMatch(
            func=lambda r: None,
            args=(),
            kwargs={"package_name": self.plugin.package_name},
            url_name="plugin_update",
        )
        links = plugin_breadcrumbs(Context({"request": request}))["quick_links"]
        plugin_url = reverse("plugin_detail", args=[self.plugin.package_name])
        self.assertEqual(links[-1]["url"], plugin_url + "#plugin-versions")


class TestBreadcrumbsRendering(BreadcrumbsTestBase):
    """Integration tests asserting the trail reaches the rendered page."""

    def setUp(self):
        super().setUp()
        self.client.login(username=self.creator.username, password="password")
        self.plugin_url = reverse("plugin_detail", args=[self.plugin.package_name])

    def assertBreadcrumbs(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="breadcrumb plugin-breadcrumb"')
        self.assertContains(response, 'aria-current="page"', count=1)
        return response

    def test_plugin_detail_has_no_breadcrumbs(self):
        response = self.client.get(self.plugin_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "plugin-breadcrumb")

    def test_plugin_update_links_back_to_plugin(self):
        response = self.assertBreadcrumbs(
            reverse("plugin_update", args=[self.plugin.package_name])
        )
        self.assertContains(response, 'href="%s"' % self.plugin_url)

    def test_version_detail_links_up_to_versions_tab(self):
        response = self.assertBreadcrumbs(
            reverse(
                "version_detail",
                args=[self.plugin.package_name, self.version.version],
            )
        )
        self.assertContains(response, 'href="%s#plugin-versions"' % self.plugin_url)

    def test_sub_page_renders_quick_links(self):
        response = self.assertBreadcrumbs(
            reverse("plugin_update", args=[self.plugin.package_name])
        )
        self.assertContains(response, "plugin-quick-links")
        self.assertContains(response, 'href="%s#plugin-details"' % self.plugin_url)

    def test_version_feedback_renders_breadcrumbs(self):
        response = self.assertBreadcrumbs(
            reverse(
                "version_feedback",
                args=[self.plugin.package_name, self.version.version],
            )
        )
        self.assertContains(
            response,
            'href="%s"'
            % reverse(
                "version_detail",
                args=[self.plugin.package_name, self.version.version],
            ),
        )

    def test_token_list_renders_breadcrumbs(self):
        self.assertBreadcrumbs(
            reverse("plugin_token_list", args=[self.plugin.package_name])
        )

    def test_plugin_list_has_no_breadcrumbs(self):
        response = self.client.get(reverse("approved_plugins"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "plugin-breadcrumb")

    def test_plugin_name_is_escaped(self):
        self.plugin.name = "<script>alert(1)</script>"
        self.plugin.save()
        response = self.client.get(
            reverse("plugin_update", args=[self.plugin.package_name])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<script>alert(1)</script>")
