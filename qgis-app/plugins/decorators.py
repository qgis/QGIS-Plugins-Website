import datetime
from functools import wraps

from django.http import HttpResponseForbidden
from plugins.models import Plugin, PluginOutstandingToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)


def validate_plugin_token(request, plugin):
    """
    Validate the Bearer JWT in the request against the given plugin.

    On success, sets ``request.plugin_token`` (a PluginOutstandingToken
    instance), updates its ``last_used_on`` timestamp, and returns True.
    Returns False for any missing, invalid, blacklisted, or mismatched token.
    Unlike ``has_valid_token`` this never raises or returns an HTTP response,
    making it safe to call from views that should remain publicly accessible.
    """
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return False
    try:
        authentication = JWTAuthentication()
        validated_token = authentication.get_validated_token(auth_header[7:])
        plugin_id = validated_token.payload.get("plugin_id")
        jti = validated_token.payload.get("refresh_jti")
        outstanding = OutstandingToken.objects.get(jti=jti)
        if BlacklistedToken.objects.filter(token=outstanding).exists():
            return False
        if not plugin_id or plugin.pk != plugin_id:
            return False
        plugin_token = PluginOutstandingToken.objects.get(
            token=outstanding, plugin=plugin
        )
        plugin_token.last_used_on = datetime.datetime.now()
        plugin_token.save()
        request.plugin_token = plugin_token
        return True
    except (
        InvalidToken,
        TokenError,
        OutstandingToken.DoesNotExist,
        PluginOutstandingToken.DoesNotExist,
    ):
        return False


def has_valid_token(function):
    @wraps(function)
    def wrap(request, *args, **kwargs):
        package_name = kwargs.get("package_name")
        plugin = Plugin.objects.filter(package_name=package_name).first()
        if plugin is None or not validate_plugin_token(request, plugin):
            return HttpResponseForbidden("Invalid token")
        return function(request, *args, **kwargs)

    return wrap
