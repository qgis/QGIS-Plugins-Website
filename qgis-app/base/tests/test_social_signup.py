from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialLogin
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.test import RequestFactory, TestCase
from django.urls import reverse


class SocialSignupTest(TestCase):
    """New users sign up through a social provider, never with a local password."""

    def setUp(self) -> None:
        self.app = SocialApp.objects.create(
            provider="github",
            name="GitHub",
            client_id="test-client-id",
            secret="test-secret",
        )
        self.app.sites.add(Site.objects.get_current())

    def _stash_pending_social_signup(self) -> None:
        """Puts a GitHub login for an unknown user in the session, as the
        OAuth callback does before redirecting to the social signup form."""
        provider = self.app.get_provider(RequestFactory().get("/"))
        sociallogin = SocialLogin(
            user=User(username="newcomer", email="newcomer@example.com"),
            account=SocialAccount(provider="github", uid="4242", extra_data={}),
            email_addresses=[
                EmailAddress(email="newcomer@example.com", verified=True, primary=True)
            ],
            provider=provider,
        )
        session = self.client.session
        session["socialaccount_sociallogin"] = sociallogin.serialize()
        session.save()

    def test_social_signup_form_is_shown(self) -> None:
        self._stash_pending_social_signup()

        response = self.client.get(reverse("socialaccount_signup"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "socialaccount/signup.html")
        self.assertTemplateNotUsed(response, "account/signup_closed.html")

    def test_social_signup_creates_linked_user(self) -> None:
        self._stash_pending_social_signup()

        response = self.client.post(
            reverse("socialaccount_signup"), {"username": "newcomer"}
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newcomer")
        self.assertEqual(user.email, "newcomer@example.com")
        self.assertTrue(
            SocialAccount.objects.filter(
                user=user, provider="github", uid="4242"
            ).exists()
        )

    def test_local_signup_stays_closed(self) -> None:
        response = self.client.post(
            reverse("account_signup"),
            {
                "username": "localuser",
                "email": "localuser@example.com",
                "password1": "a-Long-unusual-pass-91",
                "password2": "a-Long-unusual-pass-91",
            },
        )

        self.assertTemplateUsed(response, "account/signup_closed.html")
        self.assertFalse(User.objects.filter(username="localuser").exists())
