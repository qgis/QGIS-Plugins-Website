from django.test import SimpleTestCase


class LegacyPublishRedirectTests(SimpleTestCase):
    def test_publish_url_redirects_to_current_docs(self):
        for path in ("/publish", "/publish/"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 301)
                self.assertEqual(response["Location"], "/docs/publish")
