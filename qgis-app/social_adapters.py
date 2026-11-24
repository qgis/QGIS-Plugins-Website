from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialLogin
from django.http import HttpRequest


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Keeps signup open for social providers. ACCOUNT_SIGNUP_ENABLED = False
    closes local username and password signup. Since allauth 65.22 it also
    closes social signup, and this adapter opens that path again.
    """

    def is_open_for_signup(
        self, request: HttpRequest, sociallogin: SocialLogin
    ) -> bool:
        return True
