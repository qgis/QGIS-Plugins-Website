"""The plugin.vote XML-RPC method is retired but must keep answering.

Ratings were removed from plugins.qgis.org (QGIS PSC, September 2026) after
sustained vote manipulation. The endpoint cannot simply be deleted: QGIS Desktop
installs keep calling it for years after a release, and
``QgsPluginInstaller.sendVote()`` checks only the HTTP status code::

    if reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) == 200:
        return True
    else:
        return False

so anything other than 200 makes the plugin manager show the user a failure they
can do nothing about. The whole contract is therefore: stay registered, answer
200, change nothing.

``test_vote_touches_no_database`` is the test that actually pins "no-op". The
others pin the response shape, which matters far less.
"""

import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from plugins.api import plugin_vote
from plugins.models import Plugin


class PluginVoteNoOpTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="vote_author", email="author@example.com", password="password"
        )
        self.plugin = Plugin.objects.create(
            package_name="vote_plugin",
            name="Vote Plugin",
            description="A test plugin",
            about="About text",
            author="Test Author",
            email="author@example.com",
            created_by=self.user,
            maintainer=self.user,
        )

    def test_vote_returns_success_shape(self):
        """An array of one struct, as the method always returned."""
        result = plugin_vote(self.plugin.pk, 5)

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], dict)

    def test_vote_touches_no_database(self):
        """No query at all, not even the plugin lookup.

        The old implementation did ``Plugin.objects.get(pk=plugin_id)``, which
        on an endpoint under active abuse is both a per-request query and an
        unauthenticated existence oracle for plugin ids.
        """
        with self.assertNumQueries(0):
            plugin_vote(self.plugin.pk, 5)

    def test_vote_never_raises(self):
        """Any argument shape at all, including what the desktop really sends.

        QGIS sends the parameters as strings ("5", not 5) and rpc4django does
        not coerce them, so the string case is the realistic one rather than the
        edge case.
        """
        cases = [
            (None, None),
            (0, 0),
            (-1, 99),
            ("abc", "xyz"),
            (self.plugin.pk, "5"),
            (self.plugin.pk + 10000, 3),
        ]
        for plugin_id, vote in cases:
            with self.subTest(plugin_id=plugin_id, vote=vote):
                result = plugin_vote(plugin_id, vote)
                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)

    def test_vote_accepts_no_arguments(self):
        """A client sending no params must not produce a TypeError."""
        self.assertEqual(len(plugin_vote()), 1)

    def test_rpc_endpoint_returns_200(self):
        """The only thing QgsPluginInstaller.sendVote() actually checks.

        This is the exact JSON-RPC body QGIS Desktop posts.
        """
        response = self.client.post(
            "/plugins/RPC2/",
            data=json.dumps(
                {
                    "id": "djangorpc",
                    "method": "plugin.vote",
                    "params": [str(self.plugin.pk), "5"],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)

    def test_rpc_endpoint_returns_200_for_unknown_plugin(self):
        """A stale plugin id from an old install is still a success."""
        response = self.client.post(
            "/plugins/RPC2/",
            data=json.dumps(
                {
                    "id": "djangorpc",
                    "method": "plugin.vote",
                    "params": ["999999", "5"],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
