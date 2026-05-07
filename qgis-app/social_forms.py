from allauth.socialaccount.forms import SignupForm as AllauthSocialSignupForm


class SocialSignupForm(AllauthSocialSignupForm):
    """
    Extends allauth's social signup form to make the email field non-editable
    server-side. Setting disabled=True causes Django to ignore any submitted
    value and use the form's initial value (from the OAuth provider) instead,
    preventing users from bypassing the readonly attribute via DevTools.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "email" in self.fields:
            self.fields["email"].disabled = True
