# -*- coding:utf-8 -*-
"""
QGIS-PLUGINS - ANONYMOUS VOTE THROTTLING

Voting is open to anonymous users because the QGIS Desktop plugin manager
submits ratings over XML-RPC without credentials. djangoratings identifies
an anonymous voter by a cookie it issues itself, so a client that discards
cookies is seen as a new voter on every request and can vote without limit.

To close that, an anonymous vote arriving without a cookie we recognise is
matched against recent votes from the same address on the same plugin. If
one is found, its cookie is replayed so djangoratings treats the new vote as
a change to the existing vote rather than an additional one.

The cookie is checked against the votes we hold rather than merely being
present, because the client controls what it sends: a made-up value would
otherwise be enough to look like a returning voter and skip the throttle.
settings.RATINGS_VOTES_PER_IP is enforced by djangoratings independently of
this module and caps the same behaviour should this logic ever be wrong.

This was originally written inline for the XML-RPC path only
(plugins/api.py, 2014). It lives here so the web path shares exactly the
same behaviour.

@license: GNU AGPL, see COPYING for details.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.utils import timezone
from djangoratings.views import AddRatingFromModel


def vote_cookie_name(plugin):
    """Name of the cookie djangoratings issues for votes on this plugin."""
    return "vote-%s.%s.%s" % (
        ContentType.objects.get_for_model(plugin.__class__).pk,
        plugin.pk,
        plugin.rating.field.key[:6],
    )


def anonymous_vote_cookies(request, plugin):
    """Cookies to record a vote on ``plugin`` with.

    Returns ``request.COOKIES`` unchanged for authenticated users and for
    anonymous users whose vote cookie matches a vote we actually hold. Anything
    else the client sends under that cookie name is discarded and the voter is
    identified by address instead, replaying the cookie of their recent vote so
    it is counted as a change rather than an additional vote.
    """
    cookies = request.COOKIES

    if not request.user.is_anonymous:
        return cookies

    cookie_name = vote_cookie_name(plugin)
    ratings = plugin.rating.get_ratings()

    # A cookie is only evidence of a previous vote if it names one. Trusting
    # its mere presence let a client defeat the throttle entirely by sending a
    # different made-up value on every request.
    supplied_cookie = cookies.get(cookie_name)
    if supplied_cookie and ratings.filter(cookie=supplied_cookie).exists():
        return cookies

    # Whatever the client sent is not ours, so it must not reach djangoratings
    # and be written as the cookie of a fresh vote.
    cookies = {name: value for name, value in cookies.items() if name != cookie_name}

    ip_address = request.META.get("REMOTE_ADDR", "")
    if not ip_address:
        return cookies

    window = timedelta(days=getattr(settings, "ANONYMOUS_VOTE_WINDOW_DAYS", 10))
    recent_vote = (
        ratings.filter(
            cookie__isnull=False,
            ip_address=ip_address,
            date_changed__gte=timezone.now() - window,
        )
        .order_by("-date_changed")
        .first()
    )

    if not recent_vote:
        return cookies

    return {**cookies, cookie_name: recent_vote.cookie}


_add_rating_from_model = AddRatingFromModel()


def throttled_rating_view(request, object_id, score, **kwargs):
    """djangoratings' AddRatingFromModel with anonymous vote throttling.

    AddRatingFromModel reads request.COOKIES to identify the voter, so the
    replacement cookie mapping is put there before delegating to it.
    """
    from plugins.models import Plugin

    plugin = get_object_or_404(Plugin, pk=object_id)
    request.COOKIES = anonymous_vote_cookies(request, plugin)

    return _add_rating_from_model(request, object_id=object_id, score=score, **kwargs)
