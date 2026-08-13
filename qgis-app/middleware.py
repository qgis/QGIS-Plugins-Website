# -*- coding:utf-8 -*-
# myapp/middleware.py

import logging

import sentry_sdk
from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.shortcuts import render
from django.template import TemplateDoesNotExist
from django.utils.deprecation import MiddlewareMixin

"""
    QGIS-DJANGO - MIDDLEWARE

    Middlewares to fix behind proxy IP problems

    @license: GNU AGPL, see COPYING for details.
"""

logger = logging.getLogger(__name__)


def XForwardedForMiddleware(get_response):
    # One-time configuration and initialization.

    def middleware(request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.

        # X-Forwarded-For is appended to by each proxy it passes through, so
        # only the entries added by proxies we control can be trusted. Anything
        # to the left of those was supplied by the client and is forgeable.
        # TRUSTED_PROXY_DEPTH is the number of proxies we run in front of the
        # application; we therefore read the entry that our outermost trusted
        # proxy appended, counting from the right.
        #
        # A depth of 0 means no trusted proxy sets the header, so it is ignored
        # entirely and REMOTE_ADDR is left as the peer address. That is the
        # correct setting when nginx faces clients directly.
        trusted_depth = getattr(settings, "TRUSTED_PROXY_DEPTH", 0)
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")

        if trusted_depth and forwarded_for:
            parts = [part.strip() for part in forwarded_for.split(",") if part.strip()]
            if len(parts) >= trusted_depth:
                request.META["HTTP_X_PROXY_REMOTE_ADDR"] = request.META.get(
                    "REMOTE_ADDR", ""
                )
                request.META["REMOTE_ADDR"] = parts[-trusted_depth]

        response = get_response(request)

        # Code to be executed for each request/response after
        # the view is called.

        return response

    return middleware


class HandleTemplateDoesNotExistMiddleware(MiddlewareMixin):
    """Handle missing templates"""

    def process_exception(self, request, exception):
        if isinstance(exception, TemplateDoesNotExist):
            return render(request, "404.html", status=404)
        return None


class HandleOSErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
        except OSError as e:
            logger.error("OSError occurred", exc_info=True)
            sentry_sdk.capture_exception(e)
            raise e
        return response


class HandleRequestDataTooBigMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
            return response
        except RequestDataTooBig:
            return JsonResponse(
                {"error": "Request data is too large. Please upload smaller files."},
                status=413,
            )
